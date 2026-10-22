"""Ask uses the current document and frontend models without Azure or real API calls."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_summary_policy_sets import FLOWS


CONFIG = {
    "base_url": "https://chat.example.invalid/v1", "model": "chat-test", "api_key": "chat-secret",
    "embedding_base_url": "https://vectors.example.invalid/v1", "embedding_model": "vectors-test",
    "embedding_key": "vector-secret",
}
DOCUMENT = "第一条 付款：买方应在收到发票后 30 日内付款。\n第二条 保密：双方不得披露合同内容。"


class UnusedConnection:
    def __getattribute__(self, name):
        raise AssertionError("Ask must never read the old Azure connection")


def load_flow(flow, directory):
    core = ModuleType("promptflow.core")
    core.tool = lambda function: function
    connections = ModuleType("promptflow.connections")
    connections.CustomConnection = object
    openai = ModuleType("openai")
    factory = Mock()
    openai.OpenAI = factory
    modules = {"promptflow": ModuleType("promptflow"), "promptflow.core": core,
               "promptflow.connections": connections, "openai": openai}
    loaded = {}
    with patch.dict(sys.modules, modules):
        for name in ("model_config_loader", "prompt_settings", "embedding_config_loader", "python_text_embedding",
                     "review_perspective", "contract_index", "search_doc", "ask_result_format"):
            spec = importlib.util.spec_from_file_location(name, flow / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if name == "model_config_loader":
                def find_config(filename):
                    path = directory / filename
                    if not path.is_file():
                        raise FileNotFoundError(filename)
                    return path
                module.find_local_config = find_config
                module.get_local_config_dir = lambda: directory
            if name == "contract_index":
                module.default_cache_directory = lambda: directory / ".ally-contract-index"
            loaded[name] = module
            sys.modules[name] = module
    return SimpleNamespace(**loaded, factory=factory)


def write_config(directory, **changes):
    config = dict(CONFIG, **changes)
    (directory / "model_config.json").write_text(json.dumps(config), encoding="utf-8")
    return config


def vector_response(vectors, indexes=None):
    return SimpleNamespace(data=[SimpleNamespace(index=index, embedding=vector)
                                for index, vector in zip(indexes or range(len(vectors)), vectors)])


def vector_client(dimensions=2):
    create = Mock(side_effect=lambda **kwargs: vector_response(
        [[1.0] + [0.0] * (dimensions - 1) for _ in kwargs["input"]]
    ))
    return SimpleNamespace(embeddings=SimpleNamespace(create=create)), create


def answer_response(result):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(result, ensure_ascii=False)), finish_reason="stop"
    )])


def supported_answer():
    return {"Answer": "买方应在收到发票后 30 日内付款。", "AnswerSource": DOCUMENT.splitlines()[0],
            "MarkedText": "30 日内付款", "SearchResults": [
                {"source_id": 0, "summary": "付款期限是收到发票后 30 日。",
                 "title": "Invented title", "paragraph": "unrelated old contract",
                 "keyphrases": ["30 日", "not in contract"]}
            ]}


class LocalAskTests(unittest.TestCase):
    def test_embedding_settings_are_authoritative_with_no_defaults_or_connection_fallback(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                config = write_config(directory)
                modules = load_flow(flow, directory)
                actual = modules.embedding_config_loader.get_embedding_config(UnusedConnection())
                self.assertEqual(actual, {"base_url": config["embedding_base_url"],
                                          "model": config["embedding_model"], "api_key": config["embedding_key"]})
                for field in ("embedding_base_url", "embedding_model", "embedding_key"):
                    write_config(directory, **{field: ""})
                    with self.assertRaisesRegex(RuntimeError, "配置不完整"):
                        modules.embedding_config_loader.get_embedding_config(UnusedConnection())
                (directory / "model_config.json").unlink()
                with self.assertRaisesRegex(RuntimeError, "未找到"):
                    modules.embedding_config_loader.get_embedding_config(UnusedConnection())

    def test_query_and_chunks_use_frontend_configuration_and_reuse_only_current_cache(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                index = directory / "contract_index.json"
                index.write_text('{"old-contract": {"text": "unrelated old contract"}}')
                before = index.read_bytes()
                modules = load_flow(flow, directory)
                client, create = vector_client()
                modules.factory.return_value = client
                result = modules.search_doc.search_doc_tool("何时付款？", DOCUMENT, UnusedConnection())
                self.assertEqual([item["paragraph"] for item in result], DOCUMENT.splitlines())
                modules.factory.assert_called_with(base_url=CONFIG["embedding_base_url"],
                                                   api_key=CONFIG["embedding_key"])
                self.assertEqual(create.call_count, 2)
                self.assertTrue(all(call.kwargs["model"] == CONFIG["embedding_model"]
                                    for call in create.call_args_list))
                modules.search_doc.search_doc_tool("保密要求是什么？", DOCUMENT, UnusedConnection())
                self.assertEqual(create.call_count, 3, "Only the new question should need embedding")
                changed = "第九条 付款期限为 90 日。"
                result = modules.search_doc.search_doc_tool("何时付款？", changed, UnusedConnection())
                self.assertEqual(create.call_count, 5)
                self.assertEqual(result[0]["paragraph"], changed)
                self.assertEqual(index.read_bytes(), before)
                self.assertEqual(len(list((directory / ".ally-vector-cache").glob("*.json"))), 2)

    def test_endpoint_model_and_dimensions_each_invalidate_cache(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                client, create = vector_client()
                modules.factory.return_value = client
                modules.search_doc.search_doc_tool("question", DOCUMENT, None)
                write_config(directory, embedding_model="new-model")
                modules.search_doc.search_doc_tool("question", DOCUMENT, None)
                self.assertEqual(create.call_count, 4)
                write_config(directory, embedding_model="new-model",
                             embedding_base_url="https://other.example.invalid/v1")
                modules.search_doc.search_doc_tool("question", DOCUMENT, None)
                self.assertEqual(create.call_count, 6)
                client_three, create_three = vector_client(3)
                modules.factory.return_value = client_three
                modules.search_doc.search_doc_tool("question", DOCUMENT, None)
                self.assertEqual(create_three.call_count, 2)
                self.assertEqual(len(list((directory / ".ally-vector-cache").glob("*.json"))), 4)

    def test_search_reuses_shared_chunks_and_numbering_changes_invalidate_vectors(self):
        text = "Pay within thirty days.\nKeep it confidential."
        paragraphs = [{"index": 0, "text": text.splitlines()[0], "list_label": "4.2"},
                      {"index": 1, "text": text.splitlines()[1], "list_label": "第六条"}]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                record = modules.contract_index.ensure_contract_index(text, paragraphs)
                client, create = vector_client()
                modules.factory.return_value = client
                with patch.object(modules.contract_index, "build_chunks", side_effect=AssertionError("must reuse")):
                    results = modules.search_doc.search_doc_tool("Payment?", text, None, paragraphs, "snapshot")
                self.assertEqual([item["source_id"] for item in results],
                                 [chunk["source_id"] for chunk in record["chunks"]])
                self.assertTrue(all(set(item) == {"source_id", "title", "paragraph", "summary", "keyphrases"}
                                    for item in results))
                self.assertEqual([item["paragraph"] for item in results], text.splitlines())
                self.assertEqual(create.call_count, 2)
                modules.search_doc.search_doc_tool("Confidentiality?", text, None, paragraphs, "snapshot")
                self.assertEqual(create.call_count, 3, "The shared document vectors must be reused")
                changed = [dict(paragraphs[0], list_label="4.3"), paragraphs[1]]
                results = modules.search_doc.search_doc_tool("Payment?", text, None, changed, "snapshot")
                self.assertEqual(create.call_count, 5)
                updated = modules.contract_index.ensure_contract_index(text, changed)
                self.assertEqual(updated["chunks"][0]["clause_number"], "4.3")
                self.assertNotEqual(updated["identity"], record["identity"])
                self.assertEqual(results[0]["title"], text.splitlines()[0])
                self.assertEqual(record["chunks"][0]["clause_number"], "4.2")

    def test_search_rejects_misaligned_numbering_before_any_model_request(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                with self.assertRaises(ValueError):
                    modules.search_doc.search_doc_tool("Payment?", DOCUMENT, None,
                        [{"index": 0, "text": "A different contract", "list_label": "9."}])
                modules.factory.assert_not_called()

    def test_shared_search_keeps_baseline_paragraph_boundaries_and_reuses_vectors(self):
        text = "  第一条 保密\r\n不得披露合同。\r\n\r\n第二条 付款\r\n付款期限为三十日。  "
        expected = ["第一条 保密", "不得披露合同。", "第二条 付款", "付款期限为三十日。"]
        paragraphs = [{"index": i, "text": paragraph, "list_label": ""}
                      for i, paragraph in enumerate(expected)]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                self.assertEqual(modules.search_doc.split_document(text), expected)
                self.assertEqual(modules.search_doc.split_document("  ABCDEFG\r\nHIJKLMN  ", 4),
                                 ["ABCD", "EFG", "HIJK", "LMN"])
                client, create = vector_client()
                modules.factory.return_value = client
                first = modules.search_doc.search_doc_tool("保密要求？", text, None, paragraphs)
                self.assertEqual([result["paragraph"] for result in first], expected)
                self.assertTrue(all("\r" not in item["paragraph"] and "\n" not in item["paragraph"]
                                    for item in first))
                record = modules.contract_index.ensure_contract_index(text, paragraphs)
                self.assertEqual([chunk["clause_number"] for chunk in record["chunks"]],
                                 ["第一条", "第一条", "第二条", "第二条"])
                with patch.object(modules.contract_index, "build_chunks", side_effect=AssertionError("must reuse")):
                    second = modules.search_doc.search_doc_tool("付款期限？", text, None, paragraphs)
                self.assertEqual(second, first)
                self.assertEqual(create.call_count, 3)

    def test_corrupted_cache_is_rebuilt_and_config_is_read_once_per_request(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                client, create = vector_client()
                modules.factory.return_value = client
                get_config = modules.search_doc.get_embedding_config
                with patch.object(modules.search_doc, "get_embedding_config", wraps=get_config) as config:
                    modules.search_doc.search_doc_tool("question", DOCUMENT, None)
                    config.assert_called_once()
                cache = next((directory / ".ally-vector-cache").glob("*.json"))
                data = json.loads(cache.read_text())
                data["vectors"][0] = [float("nan"), 1]
                cache.write_text(json.dumps(data))
                modules.search_doc.search_doc_tool("question", DOCUMENT, None)
                self.assertEqual(create.call_count, 4)

    def test_vector_validation_rejects_bad_counts_indexes_dimensions_and_values(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                modules = load_flow(flow, Path(temporary))
                invalid = [vector_response([]), vector_response([[1, 2], [1, 2]]),
                           vector_response([[1, 2]], [1]), vector_response([[1]]),
                           vector_response([[float("nan"), 1]]), vector_response([[True, 1]]),
                           vector_response([[0, 0]]), vector_response([[float("inf"), 1]])]
                for response in invalid:
                    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(return_value=response)))
                    with self.assertRaises(ValueError):
                        modules.python_text_embedding.create_embeddings(client, "test", ["question"], 2)
                client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(return_value=
                    vector_response([[1, 2], [2, 1]], [0, 0]))))
                with self.assertRaises(ValueError):
                    modules.python_text_embedding.create_embeddings(client, "test", ["a", "b"], 2)

    def test_missing_document_and_question_never_call_providers(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                modules = load_flow(flow, Path(temporary))
                for query, document in (("question", ""), ("question", None), ("", DOCUMENT)):
                    with self.assertRaises(ValueError):
                        modules.search_doc.search_doc_tool(query, document, UnusedConnection())
                    with self.assertRaises(ValueError):
                        modules.ask_result_format.python_tool(query, [], document, UnusedConnection(), "Chinese")
                modules.factory.assert_not_called()

    def test_formatter_uses_current_document_and_configured_chat_model_with_safe_sources(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                create = Mock(return_value=answer_response(supported_answer()))
                modules.factory.return_value = SimpleNamespace(chat=SimpleNamespace(
                    completions=SimpleNamespace(create=create)))
                result = modules.ask_result_format.python_tool("何时付款？", [
                    {"source_id": 0, "paragraph": DOCUMENT.splitlines()[0]}],
                    DOCUMENT, UnusedConnection(), "Chinese")
                modules.factory.assert_called_with(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"])
                self.assertEqual(create.call_args.kwargs["model"], CONFIG["model"])
                payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
                self.assertEqual(payload["current_document"], DOCUMENT)
                self.assertEqual(payload["question"], "何时付款？")
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("Chinese", prompt)
                self.assertIn("sole authority", prompt)
                self.assertEqual(result["SearchResults"][0]["paragraph"], DOCUMENT.splitlines()[0])
                self.assertEqual(result["SearchResults"][0]["keyphrases"], ["30 日"])
                self.assertNotIn("Invented", json.dumps(result))
                self.assertEqual(set(result), {"Answer", "AnswerSource", "MarkedText", "SearchResults",
                                               "reviewPerspective"})
                self.assertEqual(result["reviewPerspective"], "")

    def test_formatter_rejects_other_document_before_model_and_fabricated_model_sources(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                modules = load_flow(flow, Path(temporary))
                with self.assertRaisesRegex(ValueError, "当前 Word 文档不一致"):
                    modules.ask_result_format.python_tool("question", [
                        {"source_id": 0, "paragraph": "another contract"}], DOCUMENT, None, "Chinese")
                modules.factory.assert_not_called()
                passages = {0: DOCUMENT.splitlines()[0]}
                for field, value in (("AnswerSource", "another contract"), ("MarkedText", "ninety days"),
                                     ("SearchResults", [{"source_id": 999, "summary": "wrong source"}])):
                    raw = supported_answer()
                    raw[field] = value
                    with self.assertRaises(ValueError):
                        modules.ask_result_format.parse_answer_response(json.dumps(raw), DOCUMENT, passages)
                unsupported = {"Answer": "当前合同未约定该事项。", "AnswerSource": "", "MarkedText": "", "SearchResults": []}
                self.assertEqual(modules.ask_result_format.parse_answer_response(
                    json.dumps(unsupported), DOCUMENT, passages), unsupported)

    def test_provider_failures_do_not_expose_document_or_credentials(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                failure = RuntimeError("secret-api-key private contract body")
                create = Mock(side_effect=failure)
                modules.factory.return_value = SimpleNamespace(
                    embeddings=SimpleNamespace(create=create),
                    chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                for invoke in (lambda: modules.search_doc.search_doc_tool("question", DOCUMENT, None),
                               lambda: modules.ask_result_format.python_tool("question", [], DOCUMENT, None, "Chinese")):
                    with self.assertRaises(RuntimeError) as error:
                        invoke()
                    self.assertNotIn("secret-api-key", str(error.exception))
                    self.assertNotIn("private contract", str(error.exception))


if __name__ == "__main__":
    unittest.main()
