"""General clause analysis must not acquire an unrelated company-policy citation."""

import unittest
from pathlib import Path
import tempfile

from test_local_ask import load_flow, UnusedConnection
from test_policy_citations import execute_review, policy, review_result
from test_summary_policy_sets import FLOWS, load_module


class GeneralReviewTests(unittest.TestCase):
    def test_general_review_without_policy_sets_does_not_require_embedding_configuration(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                modules = load_flow(flow, Path(temporary))
                result = modules.python_text_embedding.my_python_tool(
                    "Selected clause", UnusedConnection(), policySets=[])
                self.assertEqual(result, [])
                modules.factory.assert_not_called()
                node = (flow / "flow.dag.yaml").read_text().split(
                    "  - name: python_text_embedding_search\n", 1)[1].split("  - name:", 1)[0]
                self.assertIn("policySets: '${inputs.policySets}'", node)

    def test_no_policies_still_calls_chat_and_preserves_general_analysis(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                raw = review_result([])
                output, create = execute_review(load_module(flow / "documen_summary.py"), [], raw,
                                                reviewPerspective=" Party A ")
                create.assert_called_once()
                self.assertEqual(output["reviewPerspective"], "Party A")
                item = output["PolicyItems"][0]
                self.assertEqual(item["summary"], "Analysis")
                self.assertEqual(item["corrected_text"], ["One", "Two", "Three"])
                self.assertEqual(item["review_basis"], "general")
                self.assertEqual(item["policy_citations"], [])
                self.assertEqual(item["relevant_policy_item"], "")
                self.assertNotIn("Invented", str(item))

    def test_unmatched_candidates_do_not_replace_general_findings(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                output, _ = execute_review(load_module(flow / "documen_summary.py"),
                                           [policy()], review_result([]))
                self.assertEqual(output["PolicyItems"][0]["review_basis"], "general")
                self.assertEqual(output["PolicyItems"][0]["suggested_correction"], "Correction")

    def test_matching_and_general_findings_keep_separate_bases(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                raw = review_result([])
                raw["PolicyItems"].extend(review_result([7])["PolicyItems"])
                output, _ = execute_review(load_module(flow / "documen_summary.py"), [policy()], raw)
                general, matched = output["PolicyItems"]
                self.assertEqual(general["review_basis"], "general")
                self.assertEqual(matched["review_basis"], "company_policy")
                self.assertEqual(matched["policy_citations"][0]["id"], 7)

    def test_no_identified_issue_does_not_return_unnecessary_corrections(self):
        for flow in FLOWS:
            for ids in ([], [7]):
                with self.subTest(flow=flow, ids=ids):
                    raw = review_result(ids)
                    raw["PolicyItems"][0]["iscompliant"] = "yes"
                    output, _ = execute_review(load_module(flow / "documen_summary.py"), [policy()], raw)
                    item = output["PolicyItems"][0]
                    self.assertEqual(item["suggested_correction"], "")
                    self.assertEqual(item["corrected_text"], [])


if __name__ == "__main__":
    unittest.main()
