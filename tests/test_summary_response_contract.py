"""The Summary example sent to the model must satisfy the real output validator."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_summary_policy_sets import FLOWS, POLICIES, load_module, model_result


class SummaryResponseContractTests(unittest.TestCase):
    def test_model_following_the_advertised_item_shape_can_return_general_analysis(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                module = load_module(flow / "summary_full_doc.py")

                def follow_example(**kwargs):
                    prompt = kwargs["messages"][0]["content"]
                    example_text = prompt.split("Return JSON in exactly this structure:", 1)[1].lstrip()
                    result, _ = json.JSONDecoder().raw_decode(example_text)
                    # Fill narrative values, but retain exactly the advertised item fields.
                    values = model_result([])
                    result["Summary"] = values["Summary"]
                    result["KeyPoints"] = values["KeyPoints"]
                    result["Items"][0] = {
                        field: values["Items"][0][field]
                        for field in result["Items"][0]
                    }
                    return SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(result)), finish_reason="stop"
                    )])

                create = Mock(side_effect=follow_example)
                client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                with patch.object(module, "load_policies", return_value=POLICIES), \
                     patch.object(module, "get_chat_client_and_model", return_value=(client, "test-model")):
                    output = module.python_tool("The term is four years.", None, ["NDA"])
                self.assertNotIn("error", output)
                self.assertEqual(output["Items"][0]["policy_ids"], [])
                self.assertNotIn("Relevant Company Policy:", output["Items"][0]["notes"])
                create.assert_called_once()

    def test_examples_allow_selected_policy_citations_without_exposing_ids_in_notes(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                module = load_module(flow / "summary_full_doc.py")
                example_text = module.ORIGINAL_CLAUSE_PROMPT.split(
                    "Return JSON in exactly this structure:", 1
                )[1].lstrip()
                example, _ = json.JSONDecoder().raw_decode(example_text)
                self.assertIsInstance(example["Items"][0].get("policy_ids"), list)
                selected = dict(POLICIES[1], id="internal-rule-782")
                result = model_result([selected["id"]])
                enriched = module.append_policy_citations(result, {selected["id"]: selected})
                notes = enriched["Items"][0]["notes"]
                self.assertIn("根据 NDA-Term（Warning）", notes)
                self.assertIn("NDA_ONLY", notes)
                self.assertNotIn(selected["id"], notes)


if __name__ == "__main__":
    unittest.main()
