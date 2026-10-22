"""Ask's model-facing JSON example must satisfy its real response validator."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_summary_policy_sets import FLOWS, load_module


PARAGRAPHS = [
    "Section 4.2: The Buyer must pay within thirty days.",
    "Section 8: Both parties must keep the agreement confidential.",
]
DOCUMENT = "\n".join(PARAGRAPHS)
CANDIDATES = [
    {"source_id": 17, "paragraph": PARAGRAPHS[0]},
    {"source_id": 4, "paragraph": PARAGRAPHS[1]},
]


def response(result):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(result)), finish_reason="stop"
    )])


def follow_json_example(**kwargs):
    """Fill natural-language fields but keep the source IDs given in the example."""
    prompt = kwargs["messages"][0]["content"]
    example_start = prompt.index('{"Answer"')
    result, _ = json.JSONDecoder().raw_decode(prompt[example_start:])
    payload = json.loads(kwargs["messages"][1]["content"])
    candidates = payload["candidate_passages"]
    result["Answer"] = "Payment is due within thirty days."
    result["AnswerSource"] = candidates[0]["paragraph"] if candidates else ""
    result["MarkedText"] = "thirty days" if candidates else ""
    for item in result["SearchResults"]:
        item["summary"] = "The Buyer must pay within thirty days."
        item["keyphrases"] = ["thirty days"]
    return response(result)


def execute(module, candidates, model_callback=follow_json_example):
    create = Mock(side_effect=model_callback)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(module, "get_chat_client_and_model", return_value=(client, "test-model")):
        result = module.python_tool(
            query="When is payment due?", search_result_list=candidates,
            document_text=DOCUMENT, ally=None, language="English",
        )
    return result, create


class AskResponseContractTests(unittest.TestCase):
    def test_model_following_example_can_cite_nonconsecutive_candidate_ids(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                result, create = execute(load_module(flow / "ask_result_format.py"), CANDIDATES)
                self.assertEqual(result["SearchResults"], [{
                    "title": PARAGRAPHS[0][:120], "paragraph": PARAGRAPHS[0],
                    "summary": "The Buyer must pay within thirty days.",
                    "keyphrases": ["thirty days"],
                }])
                self.assertNotIn("source_id", json.dumps(result))
                create.assert_called_once()

    def test_model_following_example_returns_no_references_without_candidates(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                result, create = execute(load_module(flow / "ask_result_format.py"), [])
                self.assertEqual(result["SearchResults"], [])
                self.assertEqual(result["AnswerSource"], "")
                self.assertEqual(result["MarkedText"], "")
                create.assert_called_once()

    def test_invalid_reference_ids_remain_rejected(self):
        # True compares equal to 1 in Python; keep that otherwise-valid ID present.
        candidates = CANDIDATES + [{"source_id": 1, "paragraph": PARAGRAPHS[0]}]
        for flow in FLOWS:
            module = load_module(flow / "ask_result_format.py")
            for reference in (
                {"source_id": 99}, {"source_id": "17"}, {"source_id": True}, {},
            ):
                with self.subTest(flow=flow, reference=reference):
                    result = {
                        "Answer": "Payment is due within thirty days.",
                        "AnswerSource": PARAGRAPHS[0], "MarkedText": "thirty days",
                        "SearchResults": [dict(reference, summary="Payment deadline", keyphrases=[])],
                    }
                    with self.assertRaisesRegex(ValueError, "模型援引了检索结果之外的条款"):
                        execute(module, candidates, lambda **kwargs: response(result))


if __name__ == "__main__":
    unittest.main()
