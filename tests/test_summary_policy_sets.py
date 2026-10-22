"""Policy isolation regression tests; no API credentials or model calls needed."""

import copy
from functools import partial
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
import weakref
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
FLOWS = [
    ROOT / "backend/PromptFlow/legal-main-flow",
    ROOT / "backend/Docker/legal-main-flow-container/flow",
]
POLICIES = [
    {"id": 1, "policySet": "General Policies", "title": "General cap",
     "instruction": "GENERAL_ONLY", "severity": 1},
    {"id": 2, "policySet": "NDA", "title": "Term",
     "instruction": "NDA_ONLY", "severity": 2},
    {"id": 3, "policySet": "Services", "title": "Service cap",
     "instruction": "SERVICES_ONLY", "severity": 1},
]


def load_module(path):
    """Replace only third-party integration boundaries, execute real app code."""
    core = ModuleType("promptflow.core")
    core.tool = lambda function: function
    connections = ModuleType("promptflow.connections")
    connections.CustomConnection = object
    openai = ModuleType("openai")
    openai.OpenAI = Mock()
    loader_spec = importlib.util.spec_from_file_location(
        "model_config_loader", path.parent / "model_config_loader.py"
    )
    loader = importlib.util.module_from_spec(loader_spec)
    with patch.dict(sys.modules, {"openai": openai}):
        loader_spec.loader.exec_module(loader)
    modules = {
        "promptflow": ModuleType("promptflow"),
        "promptflow.core": core,
        "promptflow.connections": connections,
        "model_config_loader": loader,
        "openai": openai,
    }
    prompt_spec = importlib.util.spec_from_file_location("prompt_settings", path.parent / "prompt_settings.py")
    prompt_module = importlib.util.module_from_spec(prompt_spec)
    prompt_spec.loader.exec_module(prompt_module)
    modules["prompt_settings"] = prompt_module
    display_path = path.parent / "policy_display.py"
    if display_path.is_file():
        display_spec = importlib.util.spec_from_file_location("policy_display", display_path)
        display_module = importlib.util.module_from_spec(display_spec)
        display_spec.loader.exec_module(display_module)
        modules["policy_display"] = display_module
    perspective_path = path.parent / "review_perspective.py"
    if perspective_path.is_file():
        perspective_spec = importlib.util.spec_from_file_location(
            "review_perspective", perspective_path
        )
        perspective = importlib.util.module_from_spec(perspective_spec)
        perspective_spec.loader.exec_module(perspective)
        modules["review_perspective"] = perspective
    index_path = path.parent / "contract_index.py"
    if index_path.is_file():
        index_spec = importlib.util.spec_from_file_location("contract_index", index_path)
        index_module = importlib.util.module_from_spec(index_spec)
        with patch.dict(sys.modules, modules):
            index_spec.loader.exec_module(index_module)
        modules["contract_index"] = index_module
    spec = importlib.util.spec_from_file_location("summary_test_module", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    if hasattr(module, "get_core_prompt"):
        prompt_directory = tempfile.TemporaryDirectory(prefix="ally-prompt-test-")
        module.get_local_config_dir = lambda: Path(prompt_directory.name)
        weakref.finalize(module, prompt_directory.cleanup)
    if hasattr(module, "ensure_contract_index"):
        # Exercise the real parser and file cache without ever writing user data.
        cache = tempfile.TemporaryDirectory(prefix="ally-citation-test-")
        module.ensure_contract_index = partial(
            module.ensure_contract_index, cache_dir=Path(cache.name)
        )
        weakref.finalize(module, cache.cleanup)
    return module


def model_result(ids):
    return {
        "Summary": "The agreement lasts four years.",
        "KeyPoints": ["The term exceeds the supplied policy."],
        "Items": [{
            "title": "Term", "summary": "Four years", "notes": "Check the term.",
            "original_text": "The term is four years.", "keyItems": ["4 years"],
            "policy_ids": ids,
        }],
    }


def execute(module, selected, result=None, policies=None,
            input_text="The term is four years.", **kwargs):
    result = model_result([2]) if result is None else result
    create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(result)), finish_reason="stop"
    )]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(module, "load_policies", return_value=copy.deepcopy(
        POLICIES if policies is None else policies
    )), patch.object(module, "get_chat_client_and_model", return_value=(client, "test-model")):
        output = module.python_tool(
            input_text=input_text, ally=None,
            policySets=selected, language="French", **kwargs,
        )
    return output, create


class SummaryPolicyTests(unittest.TestCase):
    def test_single_set_excludes_unselected_policies(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                output, create = execute(load_module(flow / "summary_full_doc.py"), ["NDA"])
                self.assertNotIn("error", output)
                self.assertEqual(output["PolicySets"], ["NDA"])
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("NDA_ONLY", prompt)
                self.assertNotIn("GENERAL_ONLY", prompt)
                self.assertNotIn("SERVICES_ONLY", prompt)
                self.assertIn("French", prompt)
                self.assertIn("NDA_ONLY", output["Items"][0]["notes"])

    def test_multiple_sets_include_full_union_and_trusted_citations(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                raw = model_result([2, "3", 2])
                raw["PolicySets"] = ["General Policies"]
                output, create = execute(load_module(flow / "summary_full_doc.py"),
                                         [" NDA ", "Services", "NDA"], raw)
                self.assertNotIn("error", output)
                self.assertEqual(output["PolicySets"], ["NDA", "Services"])
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("NDA_ONLY", prompt)
                self.assertIn("SERVICES_ONLY", prompt)
                self.assertNotIn("GENERAL_ONLY", prompt)
                notes = output["Items"][0]["notes"]
                self.assertEqual(notes.count("NDA_ONLY"), 1)
                self.assertEqual(notes.count("SERVICES_ONLY"), 1)

    def test_invalid_or_partially_missing_selection_never_calls_model(self):
        for flow in FLOWS:
            module = load_module(flow / "summary_full_doc.py")
            for selected in ([], None, "NDA", [" "], ["Missing"],
                             ["NDA", "Missing"], ["NDA", 123]):
                with self.subTest(flow=flow.name, selected=selected):
                    output, create = execute(module, selected)
                    self.assertIn("error", output)
                    self.assertEqual(output["Items"], [])
                    create.assert_not_called()

    def test_clause_content_and_order_are_preserved_without_review_categories(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                raw = model_result([2])
                general = model_result([])["Items"][0]
                general.update({"title": "Undefined payment deadline",
                                "notes": "The payment date is unclear; agree a specific deadline.",
                                "policySet": "Invented set", "severity": 1,
                                "severityLabel": "Critical", "policy_title": "Invented policy",
                                "policy_citations": [{"citation": "Invented citation"}],
                                "relevant_policy_item": "Invented policy reference",
                                "review_basis": "selected_policy"})
                raw["Items"].append(general)
                output, create = execute(load_module(flow / "summary_full_doc.py"),
                                         ["NDA"], raw)
                self.assertNotIn("error", output)
                self.assertEqual(output["PolicySets"], ["NDA"])
                self.assertNotIn("review_basis", output["Items"][0])
                self.assertIn("根据 NDA-Term（Warning）", output["Items"][0]["notes"])
                item = output["Items"][1]
                self.assertEqual(item["policy_ids"], [])
                self.assertNotIn("review_basis", item)
                self.assertEqual(item["notes"], general["notes"])
                self.assertEqual(item["title"], general["title"])
                self.assertEqual(item["original_text"], general["original_text"])
                self.assertNotIn("Relevant Company Policy:", item["notes"])
                self.assertNotIn("severity", item)
                self.assertNotIn("severityLabel", item)
                self.assertNotIn("Invented", json.dumps(item))
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertEqual([item["title"] for item in output["Items"]],
                                 [item["title"] for item in raw["Items"]])
                self.assertNotIn('"title": "Selected-policy review issue"', prompt)
                self.assertNotIn('"title": "General contract risk"', prompt)
                self.assertNotIn("GENERAL_ONLY", prompt)

    def test_clause_prompt_restores_original_analysis_with_only_the_id_example(self):
        fixture = ROOT / "tests/fixtures/summary_original_clause_prompt.txt"
        original = fixture.read_text(encoding="utf-8")
        complete_example = original.replace(
            '      "keyItems": [', '      "policy_ids": [],\n      "keyItems": [', 1
        )
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                module = load_module(flow / "summary_full_doc.py")
                _, create = execute(module, ["NDA"])
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertEqual(module.ORIGINAL_CLAUSE_PROMPT, complete_example)
                self.assertTrue(prompt.startswith(complete_example))
                # Let the configured service choose its budget, including reasoning.
                self.assertNotIn("max_tokens", create.call_args.kwargs)
                self.assertEqual(create.call_args.kwargs["response_format"], {"type": "json_object"})

    def test_existing_policy_id_prompt_is_preserved_without_a_second_output_schema(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                _, create = execute(load_module(flow / "summary_full_doc.py"), ["NDA"])
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("policy_ids", prompt)
                self.assertIn("exact IDs from the supplied policies", prompt)
                self.assertNotIn("FINAL OUTPUT REQUIREMENTS", prompt)
                self.assertNotIn("Final required JSON shape:", prompt)

    def test_general_only_findings_do_not_require_an_artificial_policy_reference(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                raw = model_result([])
                output, _ = execute(load_module(flow / "summary_full_doc.py"), ["NDA"], raw)
                self.assertNotIn("error", output)
                self.assertEqual(output["Summary"], raw["Summary"])
                self.assertEqual(output["KeyPoints"], raw["KeyPoints"])
                self.assertEqual(output["Items"][0]["policy_ids"], [])
                for field in ("title", "summary", "notes", "original_text", "keyItems"):
                    self.assertEqual(output["Items"][0][field], raw["Items"][0][field])
                self.assertNotIn("NDA_ONLY", output["Items"][0]["notes"])

    def test_unselected_missing_and_malformed_references_rejected(self):
        for flow in FLOWS:
            module = load_module(flow / "summary_full_doc.py")
            for ids in ([1], [2, 1], None, "2", [999], [True], [{}]):
                with self.subTest(flow=flow.name, ids=ids):
                    output, _ = execute(module, ["NDA"], model_result(ids))
                    self.assertIn("error", output)
                    self.assertEqual(output["Items"], [])
            raw = model_result([2])
            del raw["Items"][0]["policy_ids"]
            with self.subTest(flow=flow.name, ids="absent"):
                output, _ = execute(module, ["NDA"], raw)
                self.assertIn("error", output)

    def test_bad_policy_ids_rejected_before_model_call(self):
        for flow in FLOWS:
            module = load_module(flow / "summary_full_doc.py")
            for bad_id in (None, "", True, {}, []):
                policies = copy.deepcopy(POLICIES)
                policies[1]["id"] = bad_id
                with self.subTest(flow=flow.name, bad_id=bad_id):
                    output, create = execute(module, ["NDA"], policies=policies)
                    self.assertIn("error", output)
                    create.assert_not_called()
            policies = copy.deepcopy(POLICIES)
            policies[2]["id"] = "2"
            with self.subTest(flow=flow.name, duplicate=True):
                output, create = execute(module, ["NDA", "Services"], policies=policies)
                self.assertIn("error", output)
                create.assert_not_called()

    def test_repeated_calls_do_not_reuse_another_selection(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                module = load_module(flow / "summary_full_doc.py")
                execute(module, ["NDA"])
                output, create = execute(module, ["Services"], model_result([3]))
                self.assertEqual(output["PolicySets"], ["Services"])
                prompt = create.call_args.kwargs["messages"][0]["content"]
                self.assertNotIn("NDA_ONLY", prompt)
                self.assertIn("SERVICES_ONLY", prompt)


class AggregationTests(unittest.TestCase):
    def test_summary_cannot_be_shadowed_by_other_branch_output(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                aggregate = load_module(flow / "aggregation.py").my_python_tool
                expected = {"Summary": "Selected sets only", "Items": []}
                self.assertIs(aggregate(query_type=1, input1={"wrong": "review"},
                                        input2={"wrong": "legacy"}, input3=expected,
                                        input4={"wrong": "ask"}, input5=False), expected)
                output = aggregate(query_type=1, input1={"wrong": "review"},
                                   input2=None, input3=None, input4=None, input5=False)
                self.assertIn("error", output)

    def test_existing_routes_and_false_index_results_are_preserved(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name):
                aggregate = load_module(flow / "aggregation.py").my_python_tool
                for query_type, name in ((0, "input2"), (2, "input1"), (3, "input4")):
                    inputs = {f"input{i}": {"route": i} for i in range(1, 6)}
                    self.assertEqual(aggregate(query_type=query_type, **inputs), inputs[name])
                self.assertEqual(aggregate(query_type=99, input5=False), {"Found": False})
                self.assertEqual(aggregate(query_type=98, input6={"indexed": True}),
                                 {"indexed": True})


class LocalConfigurationTests(unittest.TestCase):
    def test_project_configuration_is_authoritative(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                (project / "src").mkdir()
                (project / "package.json").write_text("{}")
                deployed = project / "backend" / "flow"
                deployed.mkdir(parents=True)
                local_policy = project / "policy.json"
                local_policy.write_text("[]")
                (deployed / "policy.json").write_text('[{"stale": true}]')
                loader = load_module(flow / "model_config_loader.py")
                with patch.object(loader, "__file__", str(deployed / "model_config_loader.py")):
                    self.assertEqual(loader.find_local_config("policy.json"), local_policy.resolve())
                    local_policy.unlink()
                    with self.assertRaises(FileNotFoundError):
                        loader.find_local_config("policy.json")

    def test_standalone_flow_uses_its_mounted_configuration(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name), tempfile.TemporaryDirectory() as directory:
                deployed = Path(directory)
                policy_file = deployed / "policy.json"
                policy_file.write_text("[]")
                loader = load_module(flow / "model_config_loader.py")
                with patch.object(loader, "__file__", str(deployed / "model_config_loader.py")):
                    self.assertEqual(loader.find_local_config("policy.json"), policy_file.resolve())

    def test_policy_file_supports_utf8_bom_and_value_wrapper(self):
        for flow in FLOWS:
            with self.subTest(flow=flow.name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "policy.json"
                path.write_text(json.dumps({"value": POLICIES}), encoding="utf-8-sig")
                module = load_module(flow / "summary_full_doc.py")
                with patch.object(module, "find_policy_file", return_value=path):
                    self.assertEqual(module.load_policies(), POLICIES)


if __name__ == "__main__":
    unittest.main()
