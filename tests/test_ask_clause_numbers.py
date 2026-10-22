"""Ask preserves semantic retrieval and resolves explicit original clause labels."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_local_ask import FLOWS, answer_response, load_flow, vector_client, write_config


class AskClauseNumberTests(unittest.TestCase):
    def test_ninth_clause_is_prioritized_without_removing_vector_retrieval(self):
        for flow in FLOWS:
            for automatic in (False, True):
                with self.subTest(flow=flow, automatic=automatic), tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary)
                    write_config(directory)
                    modules = load_flow(flow, directory)
                    labels = list("一二三四五六七八九十")
                    texts = [f"条款内容 {i + 1}" for i in range(10)]
                    texts[8] = "双方因本合同发生争议的，应先协商解决。"
                    if not automatic:
                        texts = [f"{label}、{text}" for label, text in zip(labels, texts)]
                    document = "\n".join(texts)
                    paragraphs = [{"index": i, "text": text, "list_label": labels[i] + "、" if automatic else ""}
                                  for i, text in enumerate(texts)]
                    client, embeddings = vector_client()
                    modules.factory.return_value = client
                    result = modules.search_doc.search_doc_tool("合同第九条规定了什么？", document, None, paragraphs)
                    self.assertEqual(result[0]["paragraph"], texts[8])
                    self.assertEqual(embeddings.call_count, 2, "Question and contract vectors must still be requested")
                    self.assertEqual(len(result), 8)

                    answer = {"Answer": "九、规定双方先协商解决争议。", "AnswerSource": texts[8],
                              "MarkedText": "", "SearchResults": [{"source_id": 8, "summary": "争议处理", "keyphrases": []}]}
                    create = Mock(return_value=answer_response(answer))
                    chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                    formatter = modules.ask_result_format
                    with patch.object(formatter, "get_chat_client_and_model", return_value=(chat, "test-model")):
                        output = formatter.python_tool("合同第九条规定了什么？", result, document, None,
                                                       "Chinese", document_paragraphs=paragraphs)
                    payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
                    self.assertEqual(payload["current_document"], document)
                    self.assertEqual(payload["requested_clauses"], [{"requested_as": "第九条", "source_id": 8,
                                                                    "clause_number": "九、", "paragraph": texts[8]}])
                    self.assertEqual(output["AnswerSource"], texts[8])
                    self.assertEqual(output["SearchResults"][0]["paragraph"], texts[8])

    def test_clause_aliases_do_not_guess_a_ninth_paragraph_or_use_chapter_numbers(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                index = modules.contract_index
                for label in ("九、", "第九条", "9.", "Article 9"):
                    record = index.ensure_contract_index(label + " 原文内容", cache_dir=directory / "index")
                    for query in ("第九条是什么？", "第9条是什么？"):
                        found = index.requested_clause_chunks(record, query)
                        self.assertEqual(len(found), 1)
                        self.assertEqual(found[0]["clause_number"], label)
                for text in ("\n".join("无编号段落" for _ in range(12)), "第九章 总则", "9.1 子条款", "（九）嵌套项目"):
                    record = index.ensure_contract_index(text, cache_dir=directory / "index")
                    self.assertEqual(index.requested_clause_chunks(record, "第九条是什么？"), [])
                record = index.ensure_contract_index("九、争议处理", cache_dir=directory / "index")
                self.assertEqual(index.requested_clause_chunks(record, "前九条有什么风险？"), [])

    def test_explicitly_requested_clause_keeps_all_its_paragraphs_even_beyond_eight_hits(self):
        text = "八、上一条\n九、争议处理\n" + "\n".join(f"争议处理的补充约定 {i}" for i in range(10)) + "\n十、其他"
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                modules = load_flow(flow, directory)
                client, embeddings = vector_client()
                modules.factory.return_value = client
                results = modules.search_doc.search_doc_tool("第九条规定什么？", text, None)
                self.assertEqual([row["paragraph"] for row in results], text.splitlines()[1:-1])
                self.assertEqual(embeddings.call_count, 2)

    def test_requested_parent_keeps_numbered_children_without_inventing_a_missing_parent(self):
        cases = (
            "八、其他\n九、违约责任\n（一）迟延交付\n（二）赔偿责任\n十、附则",
            "8. Other\n9. Liability\n9.1 Delay\n9.2 Damages\n10. Miscellaneous",
            "第八条 其他\n第九条 违约责任\n一、迟延交付\n二、赔偿责任\n第十条 附则",
        )
        for flow in FLOWS:
            for text in cases:
                with self.subTest(flow=flow, text=text), tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary)
                    write_config(directory)
                    index = load_flow(flow, directory).contract_index
                    record = index.ensure_contract_index(text, cache_dir=directory / "index")
                    selected = index.requested_clause_chunks(record, "第九条是什么？")
                    self.assertEqual([row["paragraph"] for row in selected], text.splitlines()[1:-1])

    def test_unparseable_numbers_never_match_each_other(self):
        for flow in FLOWS:
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_config(directory)
                index = load_flow(flow, directory).contract_index
                record = index.ensure_contract_index("第一9条 内容一\n第二8条 内容二", cache_dir=directory / "index")
                self.assertEqual(index.requested_clause_chunks(record, "第9十条是什么？"), [])


if __name__ == "__main__":
    unittest.main()
