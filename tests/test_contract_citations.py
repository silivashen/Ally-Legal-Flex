"""Automatic indexing must not alter the established three-feature contracts."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_policy_citations import policy, review_result
from test_summary_policy_sets import FLOWS, load_module, model_result


DOCUMENT = "付款应在三十日内完成。\n双方应对合同内容保密。"
PARAGRAPHS = [
    {"index": 0, "text": DOCUMENT.splitlines()[0], "list_label": "7."},
    {"index": 1, "text": DOCUMENT.splitlines()[1], "list_label": "8."},
]
FEATURES = (("ask", "ask_result_format.py"), ("summary", "summary_full_doc.py"),
            ("review", "documen_summary.py"))


def invoke(module, feature, raw=None, selected=None, paragraphs=PARAGRAPHS):
    """Use the real index/parser with temporary storage and a fake chat boundary."""
    source = selected if selected is not None else DOCUMENT.splitlines()[0]
    if raw is None:
        if feature == "ask":
            raw = {"Answer": "付款期限为三十日。", "AnswerSource": source,
                   "MarkedText": "", "SearchResults": [
                       {"source_id": 0, "summary": "付款期限", "keyphrases": []}]}
        elif feature == "summary":
            raw = model_result([7])
            raw["Items"][0]["original_text"] = source
        else:
            raw = review_result([7])
    create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(raw)), finish_reason="stop")]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(module, "get_chat_client_and_model", return_value=(client, "test-model")):
        if feature == "ask":
            output = module.python_tool(
                "付款期限？", [{"source_id": 0, "paragraph": DOCUMENT.splitlines()[0]}],
                DOCUMENT, None, "Chinese",
            )
        elif feature == "summary":
            with patch.object(module, "load_policies", return_value=[policy()]):
                output = module.python_tool(
                    DOCUMENT, None, ["General Policies"], document_paragraphs=paragraphs,
                )
        else:
            output = module.python_tool(
                "Chinese", source, [policy()], None, document_text=DOCUMENT,
                document_paragraphs=paragraphs,
            )
    return output, create


class AutomaticIndexCompatibilityTests(unittest.TestCase):
    def test_summary_and_review_prepare_index_without_changing_model_input(self):
        for flow in FLOWS:
            for feature, filename in FEATURES[1:]:
                with self.subTest(flow=flow, feature=feature):
                    module = load_module(flow / filename)
                    real_ensure = module.ensure_contract_index
                    with patch.object(module, "ensure_contract_index", wraps=real_ensure) as ensure:
                        result, create = invoke(module, feature)
                    self.assertNotIn("error", result)
                    ensure.assert_called_once_with(DOCUMENT, PARAGRAPHS)
                    record = real_ensure(DOCUMENT, PARAGRAPHS)
                    self.assertEqual([chunk["clause_number"] for chunk in record["chunks"]],
                                     ["7.", "8."])
                    payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
                    self.assertEqual(payload["current_document"], DOCUMENT)
                    self.assertNotIn("contract_index", payload)
                    self.assertNotIn("selection_citations", payload)

    def test_all_three_features_keep_their_existing_model_payload_and_output_contracts(self):
        expected_payload_fields = {
            "ask": {"question", "current_document", "reviewPerspective", "candidate_passages"},
            "summary": {"current_document", "reviewPerspective"},
            "review": {"selected_text", "current_document", "reviewPerspective"},
        }
        expected_result_fields = {
            "ask": {"Answer", "AnswerSource", "MarkedText", "SearchResults", "reviewPerspective"},
            "summary": {"Summary", "KeyPoints", "Items", "PolicySets", "reviewPerspective"},
            "review": {"PolicyItems", "reviewPerspective"},
        }
        for flow in FLOWS:
            for feature, filename in FEATURES:
                with self.subTest(flow=flow, feature=feature):
                    result, create = invoke(load_module(flow / filename), feature)
                    self.assertNotIn("error", result)
                    messages = create.call_args.kwargs["messages"]
                    payload = json.loads(messages[1]["content"])
                    self.assertEqual(set(payload), expected_payload_fields[feature])
                    self.assertEqual(set(result), expected_result_fields[feature])
                    self.assertNotIn("CONTRACT CITATION METADATA", messages[0]["content"])
                    self.assertNotIn("FINAL OUTPUT REQUIREMENTS", messages[0]["content"])
                    self.assertNotIn("clause_citations", json.dumps(result))
                    if feature == "ask":
                        self.assertEqual(set(payload["candidate_passages"][0]),
                                         {"source_id", "paragraph"})
                        self.assertEqual(set(result["SearchResults"][0]),
                                         {"title", "paragraph", "summary", "keyphrases"})

    def test_summary_keeps_all_items_when_model_excerpt_has_a_minor_difference(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                raw = model_result([7])
                raw["Items"][0]["original_text"] = DOCUMENT.splitlines()[0]
                second = dict(raw["Items"][0], original_text="双方应对合同内容保密。 ")
                raw["Items"].append(second)
                result, _ = invoke(load_module(flow / "summary_full_doc.py"), "summary", raw=raw)
                self.assertNotIn("error", result)
                self.assertEqual(len(result["Items"]), 2)
                self.assertEqual(result["Items"][1]["original_text"], second["original_text"])
                self.assertEqual(result["Items"][1]["policy_ids"], [7])

    def test_summary_indexes_raw_document_but_keeps_trimmed_model_input(self):
        raw_document = "  " + DOCUMENT + "\n\n"
        for flow in FLOWS:
            with self.subTest(flow=flow):
                module = load_module(flow / "summary_full_doc.py")
                create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(model_result([7]))),
                    finish_reason="stop",
                )]))
                client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                with patch.object(module, "load_policies", return_value=[policy()]), \
                        patch.object(module, "get_chat_client_and_model", return_value=(client, "test-model")), \
                        patch.object(module, "ensure_contract_index", wraps=module.ensure_contract_index) as ensure:
                    result = module.python_tool(
                        raw_document.strip(), None, ["General Policies"],
                        document_paragraphs=PARAGRAPHS, document_text=raw_document,
                    )
                self.assertNotIn("error", result)
                ensure.assert_called_once_with(raw_document, PARAGRAPHS)
                payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
                self.assertEqual(payload, {"current_document": raw_document.strip(), "reviewPerspective": ""})

    def test_review_keeps_selected_text_without_the_added_full_document_match_gate(self):
        selected = DOCUMENT.splitlines()[0] + " "
        self.assertNotIn(selected, DOCUMENT)
        for flow in FLOWS:
            with self.subTest(flow=flow):
                result, create = invoke(load_module(flow / "documen_summary.py"),
                                        "review", selected=selected)
                self.assertTrue(result["PolicyItems"])
                payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
                self.assertEqual(payload["selected_text"], selected)

    def test_ask_retains_existing_retrieved_source_id_validation(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                raw = {"Answer": "付款期限", "AnswerSource": DOCUMENT.splitlines()[0],
                       "MarkedText": "", "SearchResults": [
                           {"source_id": 99, "summary": "付款期限", "keyphrases": []}]}
                with self.assertRaisesRegex(ValueError, "模型援引了检索结果之外的条款"):
                    invoke(load_module(flow / "ask_result_format.py"), "ask", raw=raw)

    def test_invalid_index_metadata_does_not_reach_summary_or_review_models(self):
        paragraphs = [{"index": 0, "text": "another document", "list_label": "7."}]
        for flow in FLOWS:
            for feature, filename in FEATURES[1:]:
                with self.subTest(flow=flow, feature=feature):
                    module = load_module(flow / filename)
                    if feature == "summary":
                        result, create = invoke(module, feature, paragraphs=paragraphs)
                        self.assertIn("error", result)
                        create.assert_not_called()
                    else:
                        with patch.object(module, "get_chat_client_and_model") as get_client:
                            with self.assertRaises(ValueError):
                                module.python_tool("Chinese", DOCUMENT.splitlines()[0],
                                    [policy()], None, document_text=DOCUMENT,
                                    document_paragraphs=paragraphs)
                            get_client.assert_not_called()

    def test_flow_routes_metadata_to_index_and_ask_clause_context(self):
        for flow in FLOWS:
            text = (flow / "flow.dag.yaml").read_text()
            self.assertIn("  document_paragraphs:\n    type: list\n    default: []", text)
            for node_name in ("selection_summary", "summary_full_doc", "search_doc",
                              "index_contract", "check_index"):
                node = text.split("  - name: " + node_name + "\n", 1)[1].split("  - name:", 1)[0]
                self.assertIn("document_paragraphs: '${inputs.document_paragraphs}'", node)
            formatter = text.split("  - name: ask_result_format\n", 1)[1].split("  - name:", 1)[0]
            self.assertIn("document_paragraphs: '${inputs.document_paragraphs}'", formatter)
            summary = text.split("  - name: summary_full_doc\n", 1)[1].split("  - name:", 1)[0]
            self.assertIn("document_text: '${inputs.document_text}'", summary)
        for filename in ("ask_result_format.py", "summary_full_doc.py", "documen_summary.py",
                         "search_doc.py", "flow.dag.yaml"):
            self.assertEqual((FLOWS[0] / filename).read_bytes(), (FLOWS[1] / filename).read_bytes())


if __name__ == "__main__":
    unittest.main()
