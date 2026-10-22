"""Saving either model form must preserve the other form's configuration."""
import importlib.util
import json
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch


SERVER_PATH = Path(__file__).resolve().parents[1] / "model_config_server.py"
SPEC = importlib.util.spec_from_file_location("model_config_server_under_test", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class ModelConfigServerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config_file = Path(directory.name) / "model_config.json"
        config_patch = patch.object(SERVER, "CONFIG_FILE", self.config_file)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        network_patch = patch.object(
            SERVER, "open_model_request", side_effect=AssertionError("No model requests allowed")
        )
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)
        self.initial = {
            "provider": "OpenAI-compatible",
            "base_url": "https://chat.example.invalid/v1",
            "model": "old-chat-model",
            "api_key": "synthetic-chat-key",
            "embedding_base_url": "https://embedding.example.invalid/v1",
            "embedding_model": "old-embedding-model",
            "embedding_key": "synthetic-embedding-key",
            "additional_setting": {"enabled": True},
        }
        self.config_file.write_text(json.dumps(self.initial), encoding="utf-8")

    def post(self, path, body):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path = path
        handler.server = SimpleNamespace(server_port=8085)
        handler.headers = {"Host": "localhost:3000", "Origin": "https://localhost:3000", "Content-Type": "application/json"}
        handler.read_body = Mock(return_value=body)
        handler.send_json = Mock()
        handler.do_POST()
        self.network.assert_not_called()
        self.assertEqual(handler.send_json.call_count, 1)
        return handler.send_json.call_args.args

    def saved_config(self):
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def test_chat_apply_preserves_embedding_and_other_settings(self):
        for key in ("", "   ", "new-synthetic-chat-key"):
            with self.subTest(key_is_blank=not key.strip()):
                self.config_file.write_text(json.dumps(self.initial), encoding="utf-8")
                status, result = self.post("/api/apply", {
                    "base_url": " https://chat.example.invalid/v1/ ",
                    "model": " new-chat-model ",
                    "api_key": key,
                })
                self.assertEqual(status, 200)
                self.assertTrue(result["ok"])
                expected = {
                    **self.initial,
                    "base_url": "https://chat.example.invalid/v1",
                    "model": "new-chat-model",
                    "api_key": key.strip() or self.initial["api_key"],
                }
                self.assertEqual(self.saved_config(), expected)

    def test_embedding_save_preserves_chat_and_blank_key(self):
        status, result = self.post("/api/embedding-config", {
            "base_url": "https://embedding.example.invalid/v1/",
            "model": "new-embedding-model",
            "api_key": "   ",
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(self.saved_config(), {
            **self.initial,
            "embedding_base_url": "https://embedding.example.invalid/v1",
            "embedding_model": "new-embedding-model",
        })

    def test_invalid_chat_settings_do_not_change_saved_config(self):
        status, result = self.post("/api/apply", {
            "base_url": "https://new-chat.example.invalid/v1",
            "model": "",
            "api_key": "new-synthetic-chat-key",
        })
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])
        self.assertEqual(self.saved_config(), self.initial)


    def test_simultaneous_chat_and_embedding_saves_do_not_lose_either_update(self):
        save_entered = Event()
        allow_save = Event()
        embedding_finished = Event()
        results = {}
        real_write = SERVER.write_config

        def delayed_write(value):
            if value.get("model") == "new-chat" and value.get("embedding_model") == "old-embedding-model":
                save_entered.set()
                if not allow_save.wait(2):
                    raise RuntimeError("Test did not release save")
            real_write(value)

        def save_chat():
            results["chat"] = self.post("/api/apply", {
                "base_url": self.initial["base_url"], "model": "new-chat", "api_key": "",
            })

        def save_embedding():
            results["embedding"] = self.post("/api/embedding-config", {
                "base_url": self.initial["embedding_base_url"], "model": "new-vector", "api_key": "",
            })
            embedding_finished.set()

        chat_thread = Thread(target=save_chat)
        embedding_thread = Thread(target=save_embedding)
        with patch.object(SERVER, "write_config", side_effect=delayed_write):
            chat_thread.start()
            try:
                self.assertTrue(save_entered.wait(2))
                embedding_thread.start()
                self.assertFalse(embedding_finished.wait(0.05))
            finally:
                allow_save.set()
                chat_thread.join(2)
                if embedding_thread.ident is not None:
                    embedding_thread.join(2)
        self.assertFalse(chat_thread.is_alive())
        self.assertFalse(embedding_thread.is_alive())
        self.assertEqual(results["chat"][0], 200)
        self.assertEqual(results["embedding"][0], 200)
        self.assertEqual(self.saved_config(), {**self.initial, "model": "new-chat", "embedding_model": "new-vector"})
        self.assertEqual(list(self.config_file.parent.glob("*.tmp")), [])

    def test_failed_atomic_write_preserves_original_and_removes_temp_file(self):
        before = self.config_file.read_bytes()
        with patch.object(SERVER.os, "replace", side_effect=OSError("disk unavailable")):
            status, _ = self.post("/api/apply", {"base_url": self.initial["base_url"], "model": "new", "api_key": ""})
        self.assertEqual(status, 500)
        self.assertEqual(self.config_file.read_bytes(), before)
        self.assertEqual(list(self.config_file.parent.glob("*.tmp")), [])

if __name__ == "__main__":
    unittest.main()
