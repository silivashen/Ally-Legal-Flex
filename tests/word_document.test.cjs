const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const { createWordHarness, moduleSource } = require("./helpers/word-document-harness.cjs");

function harness(body, labels = []) {
  const state = { body, labels };
  const sandbox = vm.createContext(createWordHarness(state));
  vm.runInContext(moduleSource(), sandbox);
  return { state, sandbox, read: options => sandbox.readWordDocument(options) };
}

test("automatic indexing preserves raw body and captures original numbering separately", async () => {
  const h = harness("第十条 保密\nKeep the contract confidential.\n", ["", "10.1", ""]);
  const snapshot = await h.read();
  const payload = h.sandbox.documentRequestFields(snapshot);
  assert.equal(payload.document_text, h.state.body);
  assert.equal(payload.document_paragraphs[0].text, "第十条 保密");
  assert.equal(payload.document_paragraphs[1].list_label, "10.1");
  assert.match(payload.filename, /^sha256-[a-f0-9]{64}$/);
  h.state.labels[1] = "10.2";
  assert.notEqual((await h.read()).documentId, snapshot.documentId);
});

test("Review reads its selection as text without retaining a location or Word object", async () => {
  const h = harness("Heading\nOriginal clause.\nNext clause.");
  h.state.selection = "Original clause.\n";
  const snapshot = await h.read({ captureSelection: true });
  assert.equal(snapshot.selectionText, h.state.selection);
  assert.deepEqual(Object.keys(snapshot).sort(), ["documentId", "paragraphs", "selectionText", "text"]);
});

test("automatic indexing reports unsupported Word paragraph APIs explicitly", async () => {
  const h = harness("Original clause.");
  h.sandbox.Office.context.requirements.isSetSupported = () => false;
  await assert.rejects(h.read(), /Word API 1.3/);
});
