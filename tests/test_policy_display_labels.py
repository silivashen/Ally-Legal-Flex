"""Policy display cleanup must touch only verified references in generated analysis."""

import copy
import unittest

from test_policy_citations import execute_review, policy, review_result
from test_summary_policy_sets import FLOWS, execute, load_module, model_result


class PolicyDisplayLabelTests(unittest.TestCase):
    def test_summary_normalizes_generated_analysis_but_preserves_source_and_citations(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                configured = policy(5, "公司政策5", "Company Policy 5")
                configured["instruction"] = "公司政策5要求至少支付20%。Company Policy 5."
                raw = model_result([5])
                raw["Summary"] = "根据公司政策5，需核对付款比例。"
                raw["KeyPoints"] = ["Company Policy #5 requires payment of 20%."]
                raw["Items"][0].update({
                    "title": "公司政策 5与付款",
                    "summary": "Company Policy 5 requires payment of 20%.",
                    "notes": "根据公司政策编号5，核对第10.1条的30%与200%。",
                    "keyItems": ["公司政策5要求支付20%，合同金额100万元。"],
                    "original_text": "公司政策5；第10.1条：支付20%，违约金30%。",
                })
                output, _ = execute(
                    load_module(flow / "summary_full_doc.py"),
                    ["公司政策5"], raw, [configured],
                )
                self.assertNotIn("error", output)
                self.assertEqual(output["Summary"], "根据所选公司政策，需核对付款比例。")
                self.assertEqual(output["KeyPoints"], [
                    "the selected company policy requires payment of 20%."
                ])
                item = output["Items"][0]
                self.assertEqual(item["title"], "所选公司政策与付款")
                self.assertEqual(item["summary"],
                                 "the selected company policy requires payment of 20%.")
                self.assertEqual(item["keyItems"], [
                    "所选公司政策要求支付20%，合同金额100万元。"
                ])
                self.assertEqual(item["original_text"], raw["Items"][0]["original_text"])
                self.assertEqual(item["policy_ids"], [5])
                self.assertEqual(item["notes"],
                                 "根据所选公司政策，核对第10.1条的30%与200%。\n\n"
                                 "Relevant Company Policy:\n"
                                 "根据 公司政策5-Company Policy 5（Critical）\n"
                                 + configured["instruction"])

    def test_review_normalizes_analysis_without_changing_replacement_contract_text(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                configured = policy(5, "公司政策5", "Company Policy 5")
                configured["instruction"] = "Company Policy 5 requires at least 20%."
                raw = review_result([5])
                raw["PolicyItems"][0].update({
                    "title": "公司政策5与付款",
                    "summary": "根据公司政策编号5，付款不足20%。",
                    "suggested_correction": "Company Policy #5 requires payment of 20%.",
                    "keyItems": ["公司政策 5；合同第10.1条；30%；200%；100万元"],
                    "corrected_text": [
                        "公司政策5：买方支付20%。",
                        "Company Policy 5: pay 20%.",
                        "公司政策编号5，第10.1条责任不超过100万元。",
                    ],
                })
                output, _ = execute_review(load_module(flow / "documen_summary.py"),
                                           [configured], raw)
                item = output["PolicyItems"][0]
                self.assertEqual(item["title"], "所选公司政策与付款")
                self.assertEqual(item["summary"], "根据所选公司政策，付款不足20%。")
                self.assertEqual(item["suggested_correction"],
                                 "the selected company policy requires payment of 20%.")
                self.assertEqual(item["keyItems"], [
                    "所选公司政策；合同第10.1条；30%；200%；100万元"
                ])
                self.assertEqual(item["corrected_text"], raw["PolicyItems"][0]["corrected_text"])
                self.assertEqual(item["policy_ids"], [5])
                self.assertEqual(item["relevant_policy_item"],
                                 "根据 公司政策5-Company Policy 5（Critical）\n"
                                 + configured["instruction"])
                self.assertEqual(item["policy_citations"][0]["instruction"],
                                 configured["instruction"])
                self.assertEqual(item["policy_title"], "Company Policy 5")
                self.assertEqual(item["policySet"], "公司政策5")

    def test_numeric_boundaries_and_non_company_references_are_unchanged(self):
        unchanged = (
            "公司政策50；公司政策5.1；公司政策5%；公司政策第5条；政府政策5；"
            "Company Policy 50; Company Policy 5.1; Company Policy 5%; "
            "Government Policy 5; contract clause 10.1; 20%; 30%; 200%; 100万元。"
        )
        for flow in FLOWS:
            for filename in ("summary_full_doc.py", "documen_summary.py"):
                with self.subTest(flow=flow, filename=filename):
                    module = load_module(flow / filename)
                    item = self.enrich(module, filename, [5], unchanged, [policy(5)])
                    self.assertEqual(item["summary"], unchanged)

    def test_units_decimal_and_list_boundaries_preserve_numbers(self):
        unchanged = (
            "公司政策5年；公司政策5个月；公司政策5日；公司政策5万元；"
            "公司政策5项；公司政策5倍；公司政策5．1；公司政策5、6。"
        )
        source = unchanged + "公司政策5要求至少20%；公司政策5，支付时间未明确。"
        expected = unchanged + "所选公司政策要求至少20%；所选公司政策，支付时间未明确。"
        for flow in FLOWS:
            for filename in ("summary_full_doc.py", "documen_summary.py"):
                with self.subTest(flow=flow, filename=filename):
                    module = load_module(flow / filename)
                    item = self.enrich(module, filename, [5], source, [policy(5)])
                    self.assertEqual(item["summary"], expected)

    def test_chinese_identifier_does_not_match_a_longer_chinese_number(self):
        for flow in FLOWS:
            for filename in ("summary_full_doc.py", "documen_summary.py"):
                with self.subTest(flow=flow, filename=filename):
                    module = load_module(flow / filename)
                    item = self.enrich(module, filename, ["五"],
                                       "公司政策五十；公司政策五，要求付款。", [policy("五")])
                    self.assertEqual(item["summary"], "公司政策五十；所选公司政策，要求付款。")

    def test_explicit_parenthesized_policy_ids_are_normalized_only_in_analysis(self):
        unchanged = (
            "政策ID 5；公司政策（政策ID 6）；公司政策第5条；"
            "政府政策编号5；政府政策（ID5）；Government Policy (ID:5)。"
        )
        source = (
            "公司政策（政策ID 5）；公司政策（ID: 5）；Company Policy (ID: 5); "
            "公司政策（政策ID5）；公司政策(ID:5)；Company Policy(ID:5); " + unchanged
        )
        expected = (
            "所选公司政策；所选公司政策；the selected company policy; "
            "所选公司政策；所选公司政策；the selected company policy; " + unchanged
        )
        for flow in FLOWS:
            for filename in ("summary_full_doc.py", "documen_summary.py"):
                with self.subTest(flow=flow, filename=filename):
                    module = load_module(flow / filename)
                    policies = {"5": policy(5), "6": policy(6)}
                    if filename == "summary_full_doc.py":
                        raw = model_result([5])
                        raw["Items"][0].update({"summary": source, "original_text": source})
                        item = module.append_policy_citations(raw, policies)["Items"][0]
                        self.assertEqual(item["original_text"], source)
                    else:
                        raw = review_result([5])["PolicyItems"][0]
                        raw.update({"summary": source, "corrected_text": [source] * 3})
                        item = module.enrich_policy_item(raw, policies)
                        self.assertEqual(item["corrected_text"], [source] * 3)
                    self.assertEqual(item["summary"], expected)

    def test_only_ids_cited_by_that_item_can_be_normalized(self):
        for flow in FLOWS:
            for filename in ("summary_full_doc.py", "documen_summary.py"):
                with self.subTest(flow=flow, filename=filename):
                    module = load_module(flow / filename)
                    text = "公司政策5；公司政策6；公司政策99；Company Policy 6."
                    item = self.enrich(module, filename, [5], text, [policy(5), policy(6)])
                    self.assertEqual(item["summary"],
                                     "所选公司政策；公司政策6；公司政策99；Company Policy 6.")

    def test_string_and_multiple_cited_ids_are_supported_without_partial_matches(self):
        for flow in FLOWS:
            for filename in ("summary_full_doc.py", "documen_summary.py"):
                with self.subTest(flow=flow, filename=filename):
                    module = load_module(flow / filename)
                    text = (
                        "公司政策cap-v2；Company Policy #cap-v2; 公司政策5；"
                        "Company Policy cap-v20; 公司政策cap-v2.1。"
                    )
                    item = self.enrich(module, filename, ["cap-v2", "5", "cap-v2"], text,
                                       [policy("cap-v2"), policy(5)])
                    self.assertEqual(item["summary"],
                                     "所选公司政策；the selected company policy; 所选公司政策；"
                                     "Company Policy cap-v20; 公司政策cap-v2.1。")
                    self.assertEqual(item["policy_ids"], ["cap-v2", 5])

    def test_top_level_summary_uses_only_ids_verified_across_its_items(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                module = load_module(flow / "summary_full_doc.py")
                raw = model_result([5])
                second = copy.deepcopy(raw["Items"][0])
                second["policy_ids"] = [6]
                raw["Items"].append(second)
                raw["Summary"] = "公司政策5；公司政策6；公司政策7；公司政策99。"
                raw["KeyPoints"] = ["Company Policy #6; Company Policy 7."]
                output = module.append_policy_citations(raw, {
                    str(key): policy(key) for key in (5, 6, 7)
                })
                self.assertEqual(output["Summary"],
                                 "所选公司政策；所选公司政策；公司政策7；公司政策99。")
                self.assertEqual(output["KeyPoints"],
                                 ["the selected company policy; Company Policy 7."])

    def test_general_analysis_without_policy_ids_remains_present_and_unmodified(self):
        for flow in FLOWS:
            with self.subTest(flow=flow):
                module = load_module(flow / "summary_full_doc.py")
                raw = model_result([5])
                general = copy.deepcopy(raw["Items"][0])
                general.update({"policy_ids": [], "title": "付款安排不明",
                                "summary": "付款进度表为空；公司政策5并非本项依据。",
                                "notes": "一般风险：未约定付款时间。"})
                raw["Items"].append(general)
                output = module.append_policy_citations(raw, {"5": policy(5)})
                self.assertEqual(len(output["Items"]), 2)
                self.assertEqual(output["Items"][1], general)
                self.assertNotIn("Relevant Company Policy:", output["Items"][1]["notes"])

    @staticmethod
    def enrich(module, filename, ids, text, policies):
        policies_by_id = {str(configured["id"]): configured for configured in policies}
        if filename == "summary_full_doc.py":
            raw = model_result(ids)
            raw["Items"][0]["summary"] = text
            return module.append_policy_citations(raw, policies_by_id)["Items"][0]
        raw = review_result(ids)["PolicyItems"][0]
        raw["summary"] = text
        return module.enrich_policy_item(raw, policies_by_id)


if __name__ == "__main__":
    unittest.main()
