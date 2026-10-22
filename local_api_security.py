"""Browser access rules shared by the loopback configuration services."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

TRUSTED_ORIGINS = frozenset({
    "https://localhost:3000",
    "https://127.0.0.1:3000",
    "https://[::1]:3000",
})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class LocalAPIHandler(BaseHTTPRequestHandler):
    """Accept the local Word task pane, never arbitrary browser origins."""

    server: HTTPServer

    def single_header(self, name: str) -> Tuple[Optional[str], bool]:
        if hasattr(self.headers, "get_all"):
            values = self.headers.get_all(name, [])
            if len(values) > 1:
                return None, False
            return (values[0] if values else None), True
        return self.headers.get(name), True

    def valid_host(self) -> bool:
        host, unique = self.single_header("Host")
        if not unique or not host or any(char.isspace() for char in host):
            return False
        try:
            parsed = urlsplit("//" + host)
            return (
                parsed.hostname in LOOPBACK_HOSTS
                and parsed.port in {3000, self.server.server_port}
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
            )
        except ValueError:
            return False

    def validate_request(self, method: str) -> bool:
        self._cors_origin = None
        origin, unique_origin = self.single_header("Origin")
        if not self.valid_host() or not unique_origin:
            self.send_json(403, {"ok": False, "error": "Local request rejected.", "message": "请求来源不受信任。请从本机 Word 插件访问。"})
            return False
        if origin is not None and origin not in TRUSTED_ORIGINS:
            self.send_json(403, {"ok": False, "error": "Origin not allowed.", "message": "请求来源不受信任。请从本机 Word 插件访问。"})
            return False
        if method in {"POST", "OPTIONS"} and origin not in TRUSTED_ORIGINS:
            self.send_json(403, {"ok": False, "error": "Origin required.", "message": "请求缺少可信来源。请从本机 Word 插件访问。"})
            return False
        self._cors_origin = origin
        if method == "POST":
            content_type, unique_type = self.single_header("Content-Type")
            if not unique_type or (content_type or "").split(";", 1)[0].strip().lower() != "application/json":
                self.send_json(415, {"ok": False, "error": "JSON content required.", "message": "请求必须使用 application/json。"})
                return False
        return True

    def send_json(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Vary", "Origin")
        origin = getattr(self, "_cors_origin", None)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        if not self.validate_request("OPTIONS"):
            return
        method, unique_method = self.single_header("Access-Control-Request-Method")
        headers, unique_headers = self.single_header("Access-Control-Request-Headers")
        requested_headers = {item.strip().lower() for item in (headers or "").split(",") if item.strip()}
        if not unique_method or method not in {"GET", "POST"} or not unique_headers or requested_headers - {"content-type"}:
            self._cors_origin = None
            self.send_json(403, {"ok": False, "error": "Preflight rejected."})
            return
        self.send_json(200, {"ok": True})
