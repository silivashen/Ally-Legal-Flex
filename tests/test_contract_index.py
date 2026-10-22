"""Contract indexing preserves original text and labels without calling a model."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FLOWS = [ROOT / "backend/PromptFlow/legal-main-flow",
         ROOT / "backend/Docker/legal-main-flow-container/flow"]


def load_index(flow):
    spec = importlib.util.spec_from_file_location("contract_index_test", flow / "contract_index.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractIndexTests(unittest.TestCase):
    def test_original_labels_and_continuation_are_preserved(self):
        text = "合同标题\r\n第一条 保密\r\n不得披露合同。\r\n2.1 Payment\r\nPay in 30 days."
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, cache_dir=Path(temporary))
                self.assertEqual([chunk["clause_number"] for chunk in record["chunks"]],
                                 ["", "第一条", "第一条", "2.1", "2.1"])
                self.assertEqual([chunk["paragraph"] for chunk in record["chunks"]], text.splitlines())
                for chunk in record["chunks"]:
                    self.assertEqual(chunk["paragraph"], text[chunk["start"]:chunk["end"]])
                    self.assertIsNone(chunk["paragraph_start"])
                    self.assertNotRegex(chunk["paragraph"], r"[\r\n]")

    def test_word_automatic_labels_are_metadata_not_injected_text(self):
        text = "  Payment terms\r\n\r\nPay within thirty days.\r\nConfidentiality\r\nKeep it secret.  "
        paragraphs = [{"index": 0, "text": "Payment terms", "list_label": "4.2"},
                      {"index": 1, "text": "", "list_label": ""},
                      {"index": 2, "text": "Pay within thirty days.", "list_label": ""},
                      {"index": 3, "text": "Confidentiality", "list_label": "第六条"},
                      {"index": 4, "text": "Keep it secret.", "list_label": ""}]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, paragraphs, Path(temporary))
                self.assertEqual(record["chunks"][0]["clause_number"], "4.2")
                self.assertEqual(record["chunks"][0]["paragraph_start"], 0)
                self.assertEqual(record["chunks"][0]["paragraph_end"], 0)
                self.assertNotIn("4.2", record["chunks"][0]["paragraph"])
                citation = module.citations_for_text(record, "Pay within thirty days.")[0]
                self.assertEqual(citation["clause_number"], "4.2")
                self.assertEqual(citation["paragraph_start"], 2)
                self.assertEqual(citation["paragraph_end"], 2)
                self.assertFalse(citation["ambiguous"])
                with patch.object(module, "build_chunks", side_effect=AssertionError("must reuse")):
                    self.assertEqual(module.ensure_contract_index(text, paragraphs, Path(temporary)), record)

    def test_bad_metadata_is_rejected_before_cache_write(self):
        text = "Alpha\nBeta"
        invalid = ["bad", [None], [{"index": True, "text": "Alpha", "list_label": "1."}],
                   [{"index": 0, "text": "Beta", "list_label": "1."}],
                   [{"index": 0, "text": "Alpha", "list_label": "1."}],
                   [{"index": 0, "text": "Alpha", "list_label": "1."},
                    {"index": 0, "text": "Beta", "list_label": "2."}],
                   [{"index": 0, "text": "Alpha", "list_label": "1.\n2."}]]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                for paragraphs in invalid:
                    with self.subTest(paragraphs=paragraphs), self.assertRaises(ValueError):
                        module.ensure_contract_index(text, paragraphs, Path(temporary))
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_long_clause_chunks_inherit_number_and_repeated_text_is_ambiguous(self):
        text = "第十条 " + "甲" * 3300 + "\n第十一条 重复条款。\n第十二条 重复条款。"
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, cache_dir=Path(temporary))
                self.assertEqual([chunk["clause_number"] for chunk in record["chunks"][:3]],
                                 ["第十条"] * 3)
                self.assertTrue(all(len(chunk["paragraph"]) <= 1500 for chunk in record["chunks"]))
                citations = module.citations_for_text(record, "重复条款。")
                self.assertEqual([item["clause_number"] for item in citations], ["第十一条", "第十二条"])
                self.assertTrue(all(item["ambiguous"] for item in citations))
                self.assertEqual(module.citations_for_text(record, "不存在的条款"), [])

    def test_reuse_changes_and_corrupt_index_rebuild_are_content_addressed(self):
        paragraphs = [{"index": 0, "text": "Payment", "list_label": "1."}]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                directory = Path(temporary)
                first = module.ensure_contract_index("Payment", paragraphs, directory)
                with patch.object(module, "build_chunks", side_effect=AssertionError("must reuse")):
                    again = module.ensure_contract_index("Payment", paragraphs, directory)
                self.assertEqual(first, again)
                changed = module.ensure_contract_index("Payment", [dict(paragraphs[0], list_label="2.")], directory)
                self.assertNotEqual(first["identity"], changed["identity"])
                path = directory / (first["identity"] + ".json")
                path.write_text('{"schema_version": 0}', encoding="utf-8")
                rebuilt = module.ensure_contract_index("Payment", paragraphs, directory)
                self.assertEqual(rebuilt["chunks"], first["chunks"])
                self.assertEqual(len(list(directory.glob("*.json"))), 2)

    def test_status_never_accepts_old_fulltext_record_as_current_index(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                directory = Path(temporary)
                legacy = directory / "contract_index.json"
                legacy.write_text(json.dumps({"doc": {"text": "Old document"}}))
                before = legacy.read_bytes()
                cache = directory / ".ally-contract-index"
                status = module.check_contract_index("doc", "New document", cache_dir=cache,
                                                     legacy_path=legacy)
                self.assertFalse(status["Found"])
                self.assertEqual(status["Status"], "legacy")
                module.index_document("doc", "New document", cache_dir=cache)
                self.assertTrue(module.check_contract_index("doc", "New document", cache_dir=cache)["Found"])
                self.assertEqual(module.check_contract_index("doc", "Changed document", cache_dir=cache)["Status"], "stale")
                self.assertEqual(legacy.read_bytes(), before)

    def test_paragraph_chunk_version_invalidates_old_combined_clause_cache(self):
        text = "第一条 保密\r不得披露合同。"
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                self.assertNotEqual(module.CHUNK_VERSION, "original-clause-1500-v1")
                with patch.object(module, "CHUNK_VERSION", "original-clause-1500-v1"):
                    previous = module.ensure_contract_index(text, cache_dir=Path(temporary))
                current = module.ensure_contract_index(text, cache_dir=Path(temporary))
                self.assertNotEqual(current["identity"], previous["identity"])
                self.assertEqual([chunk["paragraph"] for chunk in current["chunks"]], text.splitlines())

    def test_fallback_does_not_invent_numbers_or_treat_decimal_as_heading(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index("No heading\n100.00% of fees applies.", cache_dir=Path(temporary))
                self.assertTrue(all(item["clause_number"] == "" for item in record["chunks"]))
                self.assertEqual(module.index_context(record), record["chunks"])

    def test_subclauses_without_spaces_and_roman_labels_are_preserved(self):
        text = "1.2货物质量\n1.2.1按照标准执行\n1.2. 付款\nIV. Confidentiality\nSection 2.3(a) Notices"
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, cache_dir=Path(temporary))
                self.assertEqual([item["clause_number"] for item in record["chunks"]],
                                 ["1.2", "1.2.1", "1.2.", "IV.", "Section 2.3(a)"])

    def test_unordered_symbols_and_amounts_do_not_invent_clause_numbers(self):
        text = "1.2万元\n100.00% of fees applies.\nAction item"
        paragraphs = [{"index": 0, "text": "1.2万元", "list_label": ""},
                      {"index": 1, "text": "100.00% of fees applies.", "list_label": ""},
                      {"index": 2, "text": "Action item", "list_label": "✓"}]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                record = load_index(flow).ensure_contract_index(text, paragraphs, Path(temporary))
                self.assertTrue(all(item["clause_number"] == "" for item in record["chunks"]))

    def test_spaced_amounts_percentages_and_quantity_units_are_not_clause_numbers(self):
        for flow in FLOWS:
            for text in ("1.2 万元", "100.00 %", "100.00　％", "1.2 kg", "1.2 公斤"):
                with self.subTest(flow=flow, text=text), tempfile.TemporaryDirectory() as temporary:
                    record = load_index(flow).ensure_contract_index(text, cache_dir=Path(temporary))
                    self.assertEqual(record["chunks"][0]["clause_number"], "")

    def test_dates_and_english_amounts_do_not_replace_the_original_clause_number(self):
        text = "第八条 付款\n2026.10.18\n1.2 million USD is payable."
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, cache_dir=Path(temporary))
                self.assertEqual([chunk["clause_number"] for chunk in record["chunks"]], ["第八条"] * 3)
                # Explicit Word numbering remains authoritative even if it resembles a date.
                automatic = module.ensure_contract_index("Payment", [
                    {"index": 0, "text": "Payment", "list_label": "2026.10.18"}], Path(temporary))
                self.assertEqual(automatic["chunks"][0]["clause_number"], "2026.10.18")

    def test_explicit_numbered_headings_keep_currency_words_but_decimal_multipliers_do_not(self):
        text = "第一条 人民币结算\nArticle 2 USD payment\n1.5 倍违约金"
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, cache_dir=Path(temporary))
                self.assertEqual([chunk["clause_number"] for chunk in record["chunks"]],
                                 ["第一条", "Article 2", "Article 2"])
                self.assertEqual("1.5 倍违约金", record["chunks"][2]["paragraph"])
                automatic = module.ensure_contract_index("倍违约金", [
                    {"index": 0, "text": "倍违约金", "list_label": "1.5"}], Path(temporary))
                self.assertEqual(automatic["chunks"][0]["clause_number"], "1.5")

    def test_word_table_separators_keep_offsets_and_allow_safe_cache_reuse(self):
        text = "Payment\r\u0007Confidentiality"
        paragraphs = [{"index": 0, "text": "Payment", "list_label": "1."},
                      {"index": 1, "text": "Confidentiality", "list_label": "2."}]
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                module = load_index(flow)
                record = module.ensure_contract_index(text, paragraphs, Path(temporary))
                self.assertEqual([chunk["clause_number"] for chunk in record["chunks"]], ["1.", "2."])
                self.assertEqual(record["chunks"][1]["start"], len("Payment\r\u0007"))
                for chunk in record["chunks"]:
                    self.assertEqual(chunk["paragraph"], text[chunk["start"]:chunk["end"]])
                with patch.object(module, "build_chunks", side_effect=AssertionError("must reuse")):
                    self.assertEqual(module.ensure_contract_index(text, paragraphs, Path(temporary)), record)
                with self.assertRaises(ValueError):
                    module.ensure_contract_index("Payment\rXConfidentiality", paragraphs, Path(temporary))

    def test_flow_copies_match(self):
        self.assertEqual((FLOWS[0] / "contract_index.py").read_bytes(),
                         (FLOWS[1] / "contract_index.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
