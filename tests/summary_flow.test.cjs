const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const yaml = require("js-yaml");

const root = path.resolve(__dirname, "..");
for (const relative of [
  "backend/PromptFlow/legal-main-flow",
  "backend/Docker/legal-main-flow-container/flow",
]) {
  test(`${relative}: Summary uses only the selected-policy branch`, () => {
    const flow = yaml.load(fs.readFileSync(path.join(root, relative, "flow.dag.yaml"), "utf8"));
    const nodes = Object.fromEntries(flow.nodes.map(node => [node.name, node]));
    const summary = nodes.summary_full_doc;
    assert.deepEqual(flow.inputs.policySets.default, []);
    assert.equal(flow.inputs.reviewPerspective.default, "");
    for (const name of ["summary_full_doc", "selection_summary", "ask_result_format"]) {
      assert.equal(nodes[name].inputs.reviewPerspective, "${inputs.reviewPerspective}", name);
    }
    assert.equal(nodes.selection_summary.inputs.document_text, "${inputs.document_text}");
    assert.equal(summary.inputs.policySets, "${inputs.policySets}");
    assert.equal(summary.inputs.language, "${inputs.language}");
    assert.deepEqual(summary.activate, { when: "${inputs.query_type}", is: 1 });
    assert.equal(nodes.aggregation.inputs.query_type, "${inputs.query_type}");
    assert.equal(nodes.aggregation.inputs.input3, "${summary_full_doc.output}");
    for (const name of ["selection_summary", "summary_document", "search_policy", "search_doc", "ask_result_format"]) {
      assert.equal(nodes[name].activate.when, "${inputs.query_type}", name);
      assert.notEqual(nodes[name].activate.is, 1, name);
    }
    assert.equal(nodes.selection_summary.activate.is, 2);
    assert.equal(nodes.search_policy.activate.is, 2);
    assert.equal(nodes.summary_document.activate.is, 0);
    assert.equal(nodes.summary_document.inputs.policy_list, "${list_policys.output}");
    assert.equal(nodes.ask_result_format.activate.is, 3);
    assert.equal(nodes.search_doc.inputs.document_text, "${inputs.document_text}");
    assert.equal(nodes.ask_result_format.inputs.document_text, "${inputs.document_text}");
    assert.equal(nodes.ask_result_format.inputs.document_paragraphs, "${inputs.document_paragraphs}");
    assert.equal(nodes.ask_result_format.inputs.search_result_list, "${search_doc.output}");
    assert.equal(nodes.list_policys.inputs.policySets, "${inputs.policySets}");
    assert.equal(nodes.check_index.inputs.filename, "${inputs.filename}");
    assert.equal(nodes.index_contract.activate.is, 98);
    assert.equal(nodes.aggregation.inputs.input6, "${index_contract.output}");
    // Ask creates question and chunk vectors under a single configuration snapshot.
    assert.equal(flow.nodes.some(node => node.source.path === "python_text_embedding.py" && node.activate?.is === 3), false);
  });
}
