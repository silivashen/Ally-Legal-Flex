"""Both review modes must render citation labels from trusted policy metadata."""

import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_summary_policy_sets import FLOWS, execute, load_module, model_result


def policy(policy_id=7, policy_set="General Policies", title="cap", severity=1):
    return {"id": policy_id, "policySet": policy_set, "title": title,
            "severity": severity, "instruction": "Trusted instruction"}


def review_result(ids):
    return {"PolicyItems": [{
        "title": "Clause issue", "summary": "Analysis", "iscompliant": "no",
        "keyItems": [], "suggested_correction": "Correction",
        "corrected_text": ["One", "Two", "Three"],
        "policy_ids": ids,
        "relevant_policy_item": "Invented set-invented rule（Invented severity）",
        "policy_citations": [{"citation": "Invented citation"}],
        "policySet": "Invented set", "policy_title": "Invented title",
        "severity": 999, "severityLabel": "Invented severity",
    }]}


def execute_review(module, policies, result, **kwargs):
    create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(result)), finish_reason="stop"
    )]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(module, "get_chat_client_and_model", return_value=(client, "configured-model")):
        output = module.python_tool(language="Chinese", input_text="Selected clause",
                                    policy_list=policies, ally=None, **kwargs)
    return output, create


class CitationTests(unittest.TestCase):
    def test_summary_labels_use_exact_names_and_configured_severity(self):
        for flow in FLOWS:
            for severity, label in ((1, "Critical"), ("2", "Warning"), (3, "Informational")):
                with self.subTest(flow=flow.name, severity=severity):
                    policies = [policy(severity=severity)]
                    output, _ = execute(load_module(flow / "summary_full_doc.py"),
                                        ["General Policies"], model_result([7]), policies)
                    self.assertNotIn("error", output)
                    self.assertIn(f"根据 General Policies-cap（{label}）",
                                  output["Items"][0]["notes"])

    def test_summary_discards_model_written_citation_metadata(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                raw = model_result([7])
                raw["Items"][0].update({
                    "policySet": "Invented set", "policy_title": "Invented title",
                    "severity": 999, "severityLabel": "Invented severity",
                    "policy_citations": [{"citation": "Invented citation"}],
                    "relevant_policy_item": "Invented requirement",
                })
                output, _ = execute(load_module(flow / "summary_full_doc.py"),
                                    ["General Policies"], raw, [policy()])
                item = output["Items"][0]
                self.assertNotIn("Invented", json.dumps(item))
                self.assertNotIn("severity", item)
                self.assertEqual(item["policy_ids"], [7])
                self.assertIn("根据 General Policies-cap（Critical）", item["notes"])

    def test_review_labels_overwrite_model_metadata_and_preserve_alternatives(self):
        for flow in FLOWS:
            for severity, label in ((1, "Critical"), ("2", "Warning"), (3, "Informational")):
                with self.subTest(flow=flow.name, severity=severity):
                    output, create = execute_review(load_module(flow / "documen_summary.py"),
                                                    [policy(severity=severity)], review_result([7]))
                    item = output["PolicyItems"][0]
                    self.assertEqual(item["relevant_policy_item"],
                                     f"根据 General Policies-cap（{label}）\nTrusted instruction")
                    self.assertEqual(item["policy_citations"][0]["severityLabel"], label)
                    self.assertEqual(item["corrected_text"], ["One", "Two", "Three"])
                    self.assertNotIn("Invented", json.dumps(item))
                    self.assertEqual(create.call_args.kwargs["model"], "configured-model")

    def test_review_resolves_same_title_in_different_sets_by_id(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                policies = [policy(), policy(8, "Service purchase agreement", "cap", 2)]
                output, _ = execute_review(load_module(flow / "documen_summary.py"),
                                            policies, review_result([8, 7, 8]))
                item = output["PolicyItems"][0]
                self.assertEqual(item["relevant_policy_item"].count("根据 "), 2)
                self.assertIn("根据 General Policies-cap（Critical）", item["relevant_policy_item"])
                self.assertIn("根据 Service purchase agreement-cap（Warning）", item["relevant_policy_item"])
                self.assertNotIn("Invented", json.dumps(item))

    def test_review_rejects_unknown_and_missing_ids_even_when_title_matches(self):
        for flow in FLOWS:
            for ids in ([999], [7, 999], None, "7"):
                with self.subTest(flow=flow.name, ids=ids):
                    result = review_result(ids)
                    result["PolicyItems"][0]["title"] = "cap"
                    with self.assertRaises(ValueError):
                        execute_review(load_module(flow / "documen_summary.py"), [policy()], result)

    def test_summary_rejects_incomplete_citation_metadata(self):
        for flow in FLOWS:
            for field in ("title", "severity"):
                with self.subTest(flow=flow.name, field=field):
                    invalid = policy()
                    del invalid[field]
                    output, create = execute(load_module(flow / "summary_full_doc.py"),
                                             ["General Policies"], model_result([7]), [invalid])
                    self.assertIn("error", output)
                    create.assert_not_called()

    def test_review_rejects_incomplete_or_ambiguous_citation_metadata(self):
        for flow in FLOWS:
            module = load_module(flow / "documen_summary.py")
            invalid_policies = []
            for field in ("id", "policySet", "title", "severity"):
                invalid = policy()
                del invalid[field]
                invalid_policies.append([invalid])
            for severity in (None, True, 1.5, "high"):
                invalid_policies.append([policy(severity=severity)])
            invalid_policies.append([policy(), policy("7", "Services")])
            for policies in invalid_policies:
                with self.subTest(flow=flow.name, policies=policies):
                    with patch.object(module, "get_chat_client_and_model") as get_client:
                        with self.assertRaises(ValueError):
                            module.python_tool(language="Chinese", input_text="clause",
                                               policy_list=policies, ally=None)
                        get_client.assert_not_called()

    def test_policy_search_preserves_citation_metadata_for_both_flows(self):
        embedding = ModuleType("embedding_config_loader")
        embedding.get_embedding_config = lambda _: {
            "base_url": "https://example.invalid/v1", "model": "test", "api_key": "test"
        }
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                with patch.dict(sys.modules, {"embedding_config_loader": embedding}):
                    module = load_module(flow / "search_policy.py")
                policies = [policy(), policy(8, "Services", "cap", 2)]
                with patch.object(module, "find_policy_file", return_value=Path("/unused/policy.json")), \
                     patch.object(module, "load_policies", return_value=policies), \
                     patch.object(module, "get_policy_embeddings", return_value={"0": [1], "1": [1]}):
                    result = module.list_policy_tool(
                        query="clause", embeding=[1], searchconnection=None,
                        groups=[], policySets=["Services"],
                    )
                self.assertEqual(len(result), 1)
                for field in ("id", "policySet", "title", "severity", "instruction"):
                    self.assertEqual(result[0][field], policies[1][field])


if __name__ == "__main__":
    unittest.main()
