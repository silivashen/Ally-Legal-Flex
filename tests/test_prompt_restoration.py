"""Keep the user's original prompt tasks while preserving runtime output contracts."""

import json
import unittest

from test_ask_response_contract import CANDIDATES, execute as execute_ask
from test_policy_citations import execute_review, policy, review_result
from test_summary_policy_sets import FLOWS, ROOT, execute, load_module


class PromptRestorationTests(unittest.TestCase):
    def test_ask_restores_the_local_contract_prompt(self):
        original = (ROOT / "tests/fixtures/ask_original_contract_prompt.txt").read_text()
        for flow in FLOWS:
            with self.subTest(flow=flow):
                _, create = execute_ask(load_module(flow / "ask_result_format.py"), CANDIDATES)
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertTrue(prompt.startswith(original.replace("{language}", "English")))
                self.assertNotIn("Begin by interpreting and summarizing", prompt)

    def test_review_restores_original_task_with_verified_policy_ids(self):
        original = (ROOT / "tests/fixtures/review_original_clause_prompt.txt").read_text()
        original = original.replace(
            "Return the relevant policy item that matches the selected text.",
            "Return the exact policy_ids of the relevant supplied policy items.",
        ).replace('"relevant_policy_item": "Relevant policy text"', '"policy_ids": []')
        for flow in FLOWS:
            with self.subTest(flow=flow):
                _, create = execute_review(load_module(flow / "documen_summary.py"),
                                           [policy()], review_result([7]))
                prompt = create.call_args.kwargs["messages"][0]["content"]
                preserved = original.split("2. Title:", 1)[1].split("5. Comparison:", 1)[0]
                self.assertIn(preserved, prompt)
                self.assertIn("All output should be in Chinese.", prompt)
                self.assertIn("internally consistent", prompt)
                self.assertIn("all losses", prompt)
                self.assertIn("complete selected_text", prompt)

    def test_review_example_does_not_preselect_a_company_policy(self):
        for flow in FLOWS:
            for policy_id in (7, "test-rule-91"):
                with self.subTest(flow=flow, policy_id=policy_id):
                    module = load_module(flow / "documen_summary.py")
                    selected = policy(policy_id)
                    _, create = execute_review(module, [selected], review_result([policy_id]))
                    prompt = create.call_args.kwargs["messages"][0]["content"]
                    example_text = prompt.split("Use this JSON structure:", 1)[1].lstrip()
                    example, _ = json.JSONDecoder().raw_decode(example_text)
                    enriched = module.enrich_policy_item(
                        example["PolicyItems"][0], module.index_policies([selected])
                    )
                    self.assertEqual(enriched["policy_ids"], [])
                    self.assertEqual(enriched["review_basis"], "general")

    def test_policy_numbers_are_internal_in_summary_and_review(self):
        for flow in FLOWS:
            for filename, invoke in (
                ("summary_full_doc.py", lambda module: execute(module, ["NDA"])),
                ("documen_summary.py", lambda module: execute_review(
                    module, [policy()], review_result([7]))),
            ):
                with self.subTest(flow=flow, filename=filename):
                    _, create = invoke(load_module(flow / filename))
                    prompt = create.call_args.kwargs["messages"][0]["content"]
                    self.assertIn("Do not cite policy numbers in narrative text", prompt)
                    self.assertIn("policy_ids", prompt)


if __name__ == "__main__":
    unittest.main()
