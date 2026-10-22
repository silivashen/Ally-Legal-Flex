"""Legacy flow routes must use the same local files and chat settings as the UI."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_summary_policy_sets import FLOWS, POLICIES, load_module


class LocalServiceTests(unittest.TestCase):
    def test_policy_listing_only_uses_selected_sets(self):
        for flow in FLOWS:
            with self.subTest(flow=str(flow)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "policy.json"
                path.write_text(json.dumps(POLICIES))
                module = load_module(flow / "list_policys.py")
                with patch.object(module, "find_local_config", return_value=path):
                    result = module.list_policy_tool("unused", object(), ["NDA"])
                    self.assertEqual([p["id"] for p in result], [2])
                    with self.assertRaises(ValueError):
                        module.list_policy_tool("unused", object(), ["NDA", "Missing"])
                    with self.assertRaises(ValueError):
                        module.list_policy_tool("unused", object(), [])

    def test_local_index_and_check_round_trip_preserves_existing_records(self):
        for flow in FLOWS:
            with self.subTest(flow=str(flow)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                previous = {"old": {"text": "Previously indexed text"}}
                (path / "contract_index.json").write_text(json.dumps(previous))
                indexer = load_module(flow / "index_contract.py")
                checker = load_module(flow / "check_index.py")
                with patch.object(indexer, "get_local_config_dir", return_value=path), \
                     patch.object(checker, "get_local_config_dir", return_value=path):
                    self.assertFalse(checker.my_python_tool("new", "Synthetic contract text"))
                    result = indexer.my_python_tool("new", "Synthetic contract text")
                    self.assertTrue(result["Indexed"])
                    self.assertEqual(result["Chunks"], 1)
                    self.assertTrue(checker.my_python_tool("new", "Synthetic contract text"))
                    self.assertFalse(checker.my_python_tool("new", "Changed contract text"))
                    self.assertFalse(checker.my_python_tool("old", "Previously indexed text"))
                    self.assertFalse(checker.my_python_tool(""))
                    records = json.loads((path / "contract_index.json").read_text())
                    self.assertEqual(records, previous)
                    cached = list((path / ".ally-contract-index").glob("*.json"))
                    self.assertEqual(len(cached), 1)
                    self.assertEqual(json.loads(cached[0].read_text())["text"], "Synthetic contract text")

    def test_missing_or_old_invalid_index_never_counts_as_verified(self):
        for flow in FLOWS:
            with self.subTest(flow=str(flow)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)
                checker = load_module(flow / "check_index.py")
                with patch.object(checker, "get_local_config_dir", return_value=path):
                    self.assertFalse(checker.my_python_tool("new"))
                    (path / "contract_index.json").write_text("[]")
                    self.assertFalse(checker.my_python_tool("new"))
                    self.assertEqual((path / "contract_index.json").read_text(), "[]")

    def test_legacy_summary_uses_configured_chat_client(self):
        for flow in FLOWS:
            with self.subTest(flow=str(flow)):
                module = load_module(flow / "summary_document.py")
                create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"PolicyItems": []}')
                )]))
                client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                # A plain object has no Azure or legacy connection attributes.
                connection = object()
                with patch.object(module, "get_chat_client_and_model", return_value=(client, "ui-model")) as get_model:
                    self.assertEqual(module.python_tool("Synthetic contract", POLICIES[1:2], connection, "Chinese"),
                                     {"PolicyItems": []})
                get_model.assert_called_once_with(connection)
                self.assertEqual(create.call_args.kwargs["model"], "ui-model")
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("Chinese", prompt)
                self.assertIn("NDA_ONLY", prompt)
                self.assertNotIn("GENERAL_ONLY", prompt)


if __name__ == "__main__":
    unittest.main()
