"""Browser boundary checks and credential routing; no real model calls."""
import importlib.util
import io
import json
from email.message import Message
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_server(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load_server("secure_model_test", "model_config_server.py")
POLICY = load_server("secure_policy_test", "index_server.py")
ORIGIN = "https://localhost:3000"


def invoke(module, method, path, body=None, headers=None):
    handler = module.Handler.__new__(module.Handler)
    encoded = json.dumps(body or {}).encode()
    handler.path = path
    handler.server = SimpleNamespace(server_port=8085 if module is MODEL else 8084)
    handler.headers = {
        "Host": "localhost:3000", "Origin": ORIGIN,
        "Content-Type": "application/json", "Content-Length": str(len(encoded)),
    }
    if headers:
        for name, value in headers.items():
            if value is None:
                handler.headers.pop(name, None)
            else:
                handler.headers[name] = value
    handler.rfile = io.BytesIO(encoded)
    handler.send_json = Mock()
    getattr(handler, "do_" + method)()
    handler.send_json.assert_called_once()
    return handler.send_json.call_args.args


class LocalBrowserBoundaryTests(unittest.TestCase):
    def test_posts_reject_foreign_null_and_missing_origin_before_reading_files(self):
        for module, route in ((MODEL, "/api/apply"), (POLICY, "/index")):
            for origin in ("https://attacker.invalid", "null", None, "http://localhost:3000", ORIGIN + ".attacker.invalid"):
                with self.subTest(route=route, origin=origin), \
                     patch.object(module, "read_config" if module is MODEL else "load_json", side_effect=AssertionError("Must not read private files")) as read:
                    status, _ = invoke(module, "POST", route, headers={"Origin": origin})
                    self.assertEqual(status, 403)
                    read.assert_not_called()

    def test_host_validation_blocks_rebinding_and_ignores_forwarded_headers(self):
        for module in (MODEL, POLICY):
            for host in ("attacker.invalid:8085", "localhost.attacker.invalid:8084", "127.0.0.1.attacker.invalid", "localhost:9999", "localhost:invalid", "user@localhost:3000", "[::1]:9999", None):
                with self.subTest(module=module.__name__, host=host):
                    status, _ = invoke(module, "GET", "/unknown", headers={
                        "Host": host, "X-Forwarded-Host": "localhost:3000", "X-Forwarded-Origin": ORIGIN,
                    })
                    self.assertEqual(status, 403)

    def test_trusted_proxy_and_direct_health_requests_are_accepted(self):
        for module, port in ((MODEL, 8085), (POLICY, 8084)):
            for host in ("localhost:3000", "127.0.0.1:3000", f"127.0.0.1:{port}", f"[::1]:{port}"):
                with self.subTest(host=host):
                    status, _ = invoke(module, "GET", "/unknown", headers={"Host": host, "Origin": None})
                    self.assertEqual(status, 404)
            status, _ = invoke(module, "POST", "/unknown")
            self.assertEqual(status, 404)

    def test_json_is_required_even_for_trusted_origin(self):
        for module in (MODEL, POLICY):
            for content_type in ("text/plain", "application/x-www-form-urlencoded", None):
                with self.subTest(module=module.__name__, content_type=content_type):
                    status, _ = invoke(module, "POST", "/unknown", headers={"Content-Type": content_type})
                    self.assertEqual(status, 415)

    def test_get_rejects_untrusted_origin(self):
        for module in (MODEL, POLICY):
            for origin in ("null", "https://attacker.invalid"):
                with self.subTest(origin=origin):
                    self.assertEqual(invoke(module, "GET", "/unknown", headers={"Origin": origin})[0], 403)

    def test_valid_model_read_reports_presence_without_returning_keys(self):
        config = {"base_url": "https://model.invalid/v1", "model": "chat", "api_key": "synthetic-secret", "embedding_key": "synthetic-vector"}
        with patch.object(MODEL, "read_config", return_value=config):
            for route in ("/api/config", "/api/embedding-config"):
                status, body = invoke(MODEL, "GET", route)
                self.assertEqual(status, 200)
                self.assertTrue(body["has_api_key"])
                self.assertNotIn("synthetic-secret", json.dumps(body))
                self.assertNotIn("synthetic-vector", json.dumps(body))
        with patch.object(MODEL, "read_config", side_effect=RuntimeError("synthetic-secret")):
            status, body = invoke(MODEL, "GET", "/api/config")
            self.assertEqual(status, 500)
            self.assertNotIn("synthetic-secret", json.dumps(body))

    def test_index_and_check_accept_trusted_frontend_and_block_foreign_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "contract_index.json"
            cache = Path(directory) / ".ally-contract-index"
            with patch.object(POLICY, "INDEX", index):
                payload = {"filename": "sample", "document_text": "Synthetic contract"}
                self.assertEqual(invoke(POLICY, "POST", "/index", payload, {"Origin": "https://attacker.invalid"})[0], 403)
                self.assertFalse(index.exists())
                self.assertFalse(cache.exists())
                status, body = invoke(POLICY, "POST", "/check", {"filename": "sample"})
                self.assertEqual(status, 200)
                self.assertFalse(body["Found"])
                status, body = invoke(POLICY, "POST", "/index", payload)
                self.assertEqual(status, 200)
                self.assertTrue(body["Indexed"])
                self.assertEqual(body["Chunks"], 1)
                self.assertFalse(index.exists(), "Do not replace legacy contract records")
                records = list(cache.glob("*.json"))
                self.assertEqual(len(records), 1)
                self.assertEqual(json.loads(records[0].read_text())["chunks"][0]["paragraph"], "Synthetic contract")
                self.assertTrue(invoke(POLICY, "POST", "/check", payload)[1]["Found"])
                self.assertFalse(invoke(POLICY, "POST", "/check", {"filename": "sample"})[1]["Found"])
                self.assertEqual(invoke(POLICY, "POST", "/check", dict(payload, document_text="Changed text"))[1]["Status"], "stale")
                self.assertEqual(invoke(POLICY, "POST", "/index", {"document_text": ""})[0], 400)
                index.write_text("[]")
                self.assertEqual(invoke(POLICY, "POST", "/index", payload)[0], 200)
                self.assertEqual(index.read_text(), "[]")
                malformed = dict(payload, document_paragraphs=[{"index": 0, "text": "Other contract", "list_label": "1."}])
                self.assertEqual(invoke(POLICY, "POST", "/index", malformed)[0], 400)
                self.assertEqual(invoke(POLICY, "POST", "/check", malformed)[0], 400)

    def test_policy_reads_and_set_initialization_work_on_isolated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.json"
            sets = Path(directory) / "policy_sets.json"
            with patch.object(POLICY, "POLICY", policy), patch.object(POLICY, "POLICY_SETS", sets):
                policy.write_text(json.dumps({"value": [{"policySet": "Sample", "title": "Term"}]}))
                status, body = invoke(POLICY, "GET", "/policies")
                self.assertEqual(status, 200)
                self.assertEqual(body["policies"][0]["title"], "Term")
                status, body = invoke(POLICY, "GET", "/policy-sets")
                self.assertEqual(status, 200)
                self.assertEqual(body["policySets"], ["Sample"])
                policy.write_text("null")
                self.assertEqual(invoke(POLICY, "GET", "/policies")[0], 500)
                sets.write_text("null")
                self.assertEqual(invoke(POLICY, "GET", "/policy-sets")[0], 500)

    def raw_request(self, module, headers):
        client, peer = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(peer.close)
        client.sendall(("OPTIONS /api/config HTTP/1.0\r\n" + headers + "\r\n\r\n").encode())
        client.shutdown(socket.SHUT_WR)
        with patch.object(module.Handler, "log_message"):
            module.Handler(peer, ("127.0.0.1", 1), SimpleNamespace(server_port=49152))
        peer.shutdown(socket.SHUT_WR)
        return client.makefile("rb").read().decode()

    def test_preflight_reflects_only_trusted_origin_with_real_header_parser(self):
        for module in (MODEL, POLICY):
            allowed = self.raw_request(module, "Host: localhost:49152\r\nOrigin: " + ORIGIN + "\r\nAccess-Control-Request-Method: POST\r\nAccess-Control-Request-Headers: content-type")
            self.assertIn(" 200 ", allowed.splitlines()[0])
            self.assertIn("Access-Control-Allow-Origin: " + ORIGIN, allowed)
            self.assertNotIn("Access-Control-Allow-Origin: *", allowed)
            for header in (
                "Origin: https://attacker.invalid",
                "Origin: null",
                "Origin: " + ORIGIN + "\r\nOrigin: https://attacker.invalid",
            ):
                denied = self.raw_request(module, "Host: localhost:49152\r\n" + header + "\r\nAccess-Control-Request-Method: POST")
                self.assertIn(" 403 ", denied.splitlines()[0])
                self.assertNotIn("Access-Control-Allow-Origin:", denied)
            for headers in (
                "Host: localhost:49152\r\nHost: attacker.invalid\r\nOrigin: " + ORIGIN + "\r\nAccess-Control-Request-Method: POST",
                "Host: localhost:49152\r\nOrigin: " + ORIGIN + "\r\nAccess-Control-Request-Method: DELETE",
                "Host: localhost:49152\r\nOrigin: " + ORIGIN + "\r\nAccess-Control-Request-Method: POST\r\nAccess-Control-Request-Headers: authorization",
            ):
                denied = self.raw_request(module, headers)
                self.assertIn(" 403 ", denied.splitlines()[0])
                self.assertNotIn("Access-Control-Allow-Origin:", denied)


class ModelCredentialRoutingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "model_config.json"
        self.initial = {
            "provider": "OpenAI-compatible", "base_url": "https://chat.example.invalid/v1",
            "model": "chat", "api_key": "synthetic-chat-key",
            "embedding_base_url": "https://vector.example.invalid/v1", "embedding_model": "vector",
            "embedding_key": "synthetic-vector-key", "extra": True,
        }
        self.path.write_text(json.dumps(self.initial))
        replacement = patch.object(MODEL, "CONFIG_FILE", self.path)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.network = Mock()
        # Both old and new transport entry points are intercepted during the red/green cycle.
        for name in ("open_model_request",):
            p = patch.object(MODEL, name, self.network, create=True)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(MODEL.urllib.request, "urlopen", self.network)
        p.start()
        self.addCleanup(p.stop)

    def enable_successful_network(self):
        response = SimpleNamespace(status=200, read=lambda size: b'{"data":[{"embedding":[1,2]}]}')
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        self.network.return_value = context

    def test_changed_url_with_blank_key_never_reads_old_key_into_request_or_disk(self):
        for route in ("/api/test", "/api/apply", "/api/embedding-test", "/api/embedding-config"):
            for key in ("", "   "):
                with self.subTest(route=route, key_is_blank=True):
                    before = self.path.read_bytes()
                    status, result = invoke(MODEL, "POST", route, {
                        "base_url": "https://attacker.invalid/v1", "model": "new", "api_key": key,
                    })
                    self.assertEqual(status, 400)
                    self.assertIn("Key", result["message"])
                    self.assertEqual(self.path.read_bytes(), before)
                    self.network.assert_not_called()

    def test_same_normalized_url_reuses_key_and_keeps_other_form(self):
        self.enable_successful_network()
        for route in ("/api/test", "/api/apply", "/api/embedding-test", "/api/embedding-config"):
            embedding = "embedding" in route
            base = self.initial["embedding_base_url" if embedding else "base_url"]
            key = self.initial["embedding_key" if embedding else "api_key"]
            status, _ = invoke(MODEL, "POST", route, {"base_url": base.replace("https://", "HTTPS://") + "/", "model": "new", "api_key": ""})
            self.assertEqual(status, 200)
            if "test" in route:
                self.assertEqual(self.network.call_args.args[0].get_header("Authorization"), "Bearer " + key)
            config = json.loads(self.path.read_text())
            self.assertEqual(config["api_key"], self.initial["api_key"])
            self.assertEqual(config["embedding_key"], self.initial["embedding_key"])

    def test_explicit_new_key_allows_new_https_or_local_http_endpoint(self):
        self.enable_successful_network()
        for route in ("/api/test", "/api/apply", "/api/embedding-test", "/api/embedding-config"):
            for endpoint in ("https://new.example.invalid/v1", "http://127.0.0.1:11434/v1"):
                status, _ = invoke(MODEL, "POST", route, {"base_url": endpoint, "model": "new", "api_key": "new-synthetic-key"})
                self.assertEqual(status, 200)
                if "test" in route:
                    self.assertEqual(self.network.call_args.args[0].get_header("Authorization"), "Bearer new-synthetic-key")

    def test_invalid_endpoint_is_rejected_before_network_or_save(self):
        for route in ("/api/test", "/api/apply", "/api/embedding-test", "/api/embedding-config"):
            for endpoint in ("file:///tmp/model", "ftp://host/v1", "https://user:pass@example.invalid/v1", "https://example.invalid:bad/v1", "https://example.invalid/v1\n", "https://example.invalid/v1?token=secret"):
                with self.subTest(route=route, endpoint=endpoint):
                    before = self.path.read_bytes()
                    status, _ = invoke(MODEL, "POST", route, {"base_url": endpoint, "model": "new", "api_key": "synthetic-new-key"})
                    self.assertEqual(status, 400)
                    self.network.assert_not_called()
                    self.assertEqual(self.path.read_bytes(), before)

    def test_transport_error_does_not_echo_credentials(self):
        self.network.side_effect = ValueError("Authorization: Bearer synthetic-vector-key")
        status, body = invoke(MODEL, "POST", "/api/embedding-test", {"base_url": self.initial["embedding_base_url"], "model": "vector", "api_key": ""})
        self.assertEqual(status, 502)
        self.assertNotIn("synthetic-vector-key", json.dumps(body))


class RedirectTests(unittest.TestCase):
    def test_redirect_never_sends_authorization_to_second_target(self):
        from urllib.error import HTTPError
        from urllib.request import HTTPHandler, ProxyHandler, Request, build_opener
        from urllib.response import addinfourl
        for code in (301, 302, 303, 307, 308):
            calls = []
            class FakeHTTP(HTTPHandler):
                def http_open(self, request):
                    calls.append(request)
                    headers = Message()
                    headers["Location"] = "http://attacker.invalid/stolen"
                    response = addinfourl(io.BytesIO(b""), headers, request.full_url, code if len(calls) == 1 else 200)
                    response.msg = "Synthetic response"
                    return response
            # An explicit empty ProxyHandler keeps a system proxy from rewriting the host.
            opener = build_opener(ProxyHandler({}), FakeHTTP(), MODEL.NoCredentialRedirect())
            with self.subTest(code=code), patch("socket.create_connection", side_effect=AssertionError("Unexpected real connection")), self.assertRaises(HTTPError):
                opener.open(Request("http://provider.invalid/v1", data=b"{}", headers={"Authorization": "Bearer synthetic-key"}), timeout=1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].host, "provider.invalid")


if __name__ == "__main__":
    unittest.main()
