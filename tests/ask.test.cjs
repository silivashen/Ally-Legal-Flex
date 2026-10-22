const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { parseDocument } = require("htmlparser2");
const { createWordHarness, moduleSource } = require("./helpers/word-document-harness.cjs");
const { createPerspectiveHarness, PARTY_A, PARTY_B, MULTIPLE, HOSTILE, displayPerspective } = require("./helpers/review-perspective-harness.cjs");

const root = path.resolve(__dirname, "..");
const askSource = fs.readFileSync(path.join(root, "src/taskpane/Containers/aks.js"), "utf8")
  .replace(/^import .*;\s*$/gm, "")
  .replace("export async function ask", "async function ask");
const endpointSource = fs.readFileSync(path.join(root, "src/shared/local-endpoint.js"), "utf8")
  .replace(/export function /g, "function ");
const perspectiveSource = fs.readFileSync(path.join(root, "src/shared/review-perspective.js"), "utf8")
  .replace(/export function /g, "function ");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.style = {};
    this.classList = { add() {} };
    this.listeners = new Map();
    this.value = "";
    this._text = "";
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }
  insertBefore(child, reference) {
    const index = this.children.indexOf(reference);
    assert.notEqual(index, -1);
    this.children.splice(index, 0, child);
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(" "); }
  set innerHTML(html) {
    const convert = node => {
      const element = new Element(node.name || "#text");
      Object.assign(element, node.attribs || {});
      element._text = node.data || "";
      element.children = (node.children || []).map(convert);
      return element;
    };
    this._text = "";
    this.children = parseDocument(html).children.map(convert);
  }
  addEventListener(type, callback) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), callback]);
  }
  dispatchEvent(event) { for (const listener of this.listeners.get(event.type) || []) listener(event); }
  async click() { for (const listener of this.listeners.get("click") || []) await listener(); }
  focus() {}
  find(predicate) {
    if (predicate(this)) return this;
    for (const child of this.children) {
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }
}

function harness(responses, { perspective = "", wordSync } = {}) {
  const container = new Element("div");
  container.id = "ask-container";
  container.innerHTML = '<input id="ask-input"><button id="ask-button">Ask</button>';
  const form = createPerspectiveHarness();
  form.enhanceElement(Element);
  const byId = id => form.byId(id) || container.find(node => node.id === id);
  byId("ask-input").value = "What is the confidential termination term?";
  const calls = [];
  const logs = [];
  const state = { body: "Current confidential contract body, version one." };
  const stored = new Map([["pfendpoint", "http://localhost:8083/score"], ["language", "Chinese"], ["groups", "[]"]]);
  const sandbox = vm.createContext({
    URL, AbortController, Event,
    ...createWordHarness(state, wordSync),
    window: new Element("window"),
    localStorage: { getItem: key => stored.get(key) ?? null },
    document: { getElementById: byId, createElement: tag => new Element(tag) },
    console: Object.fromEntries(["log", "error", "warn"].map(level => [level, (...args) => logs.push(args)])),
    fetch: async (url, options) => {
      calls.push({ url, payload: JSON.parse(options.body) });
      const data = await responses[calls.length - 1];
      assert.notEqual(data, undefined, "unexpected additional backend request");
      return { ok: true, status: 200, text: async () => JSON.stringify(data) };
    },
  });
  vm.runInContext(moduleSource(), sandbox);
  vm.runInContext(endpointSource, sandbox);
  vm.runInContext(perspectiveSource, sandbox);
  form.setPerspective(perspective, false);
  vm.runInContext(askSource, sandbox);
  return {
    container, byId, calls, logs, state, form, run: () => sandbox.ask(),
    setPerspective: form.setPerspective,
  };
}

test("Ask sends the current Word body and displays the answer without logging contract content", async () => {
  const h = harness([{ answer: { Answer: "Confidential answer text.", SearchResults: [{ title: "Termination", paragraph: "Confidential clause.", summary: "Contract notice period." }] } }]);
  h.state.body = "The current Word body has changed before Ask.";
  await h.run();
  assert.equal(h.calls[0].url, "/local-api/flow/score");
  assert.equal(h.calls[0].payload.document_text, h.state.body);
  assert.equal(h.calls[0].payload.query_type, 3);
  assert.equal(h.calls[0].payload.question, "What is the confidential termination term?");
  assert.equal(h.byId("ask-answer-header").textContent, "▼ Answer");
  assert.match(h.container.textContent, /Confidential answer text\./);
  assert.match(h.container.textContent, /Termination/);
  const logged = JSON.stringify(h.logs);
  for (const privateText of [h.state.body, h.calls[0].payload.question, "Confidential answer text.", "Confidential clause."]) {
    assert.equal(logged.includes(privateText), false);
  }
});

for (const wrap of [data => ({ answer: data }), data => ({ answer: JSON.stringify(data) }), data => ({ answer: { answer: data } })]) {
  test("HTTP 200 with a backend error restores the question and supports retry with the latest document", async () => {
    const h = harness([wrap({ error: "Model connection unavailable.", Answer: "" }), { answer: { Answer: "Recovered answer." } }]);
    await h.run();
    assert.match(h.container.textContent, /Ask failed: Model connection unavailable\./);
    assert.equal(h.byId("ask-answer-header"), null);
    assert.equal(h.byId("ask-input").value, "What is the confidential termination term?");
    h.state.body = "Edited contract before the retry.";
    await h.byId("ask-button").click();
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[1].payload.document_text, h.state.body);
    assert.match(h.container.textContent, /Recovered answer\./);
    assert.doesNotMatch(h.container.textContent, /Ask failed/);
  });
}

test("an empty Answer is a retryable failure", async () => {
  const h = harness([{ answer: { Answer: " " } }]);
  await h.run();
  assert.match(h.container.textContent, /Ask failed: The backend did not provide an answer/);
  assert.equal(h.byId("ask-answer-header"), null);
  assert.ok(h.byId("ask-button"));
});


function deferred() {
  let resolve;
  const promise = new Promise(res => { resolve = res; });
  return { promise, resolve };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

for (const perspective of ["", MULTIPLE, HOSTILE]) {
  test(`Ask transmits and safely displays the current perspective: ${perspective || "neutral"}`, async () => {
    const h = harness([{ answer: { Answer: "Scoped answer", reviewPerspective: perspective } }], { perspective: `  ${perspective}  ` });
    await h.run();
    assert.equal(h.calls[0].payload.reviewPerspective, perspective);
    assert.ok(h.container.textContent.includes(`Review Perspective: ${displayPerspective(perspective)}`));
    assert.equal(h.container.find(node => node.tagName === "img"), null);
    assert.match(h.container.textContent, /Scoped answer/);
  });
}

for (const echo of [undefined, PARTY_B]) {
  test(`Ask rejects an unconfirmed perspective: ${echo}`, async () => {
    const h = harness([{ answer: { Answer: "UNVERIFIED ANSWER", reviewPerspective: echo } }], { perspective: PARTY_A });
    await h.run();
    assert.match(h.container.textContent, /Ask failed:/);
    assert.doesNotMatch(h.container.textContent, /UNVERIFIED ANSWER/);
  });
}

test("changing perspective clears an existing Ask answer", async () => {
  const h = harness([{ answer: { Answer: "OLD ANSWER", reviewPerspective: PARTY_A } }], { perspective: PARTY_A });
  await h.run();
  h.setPerspective(PARTY_B);
  assert.doesNotMatch(h.container.textContent, /OLD ANSWER/);
  assert.match(h.container.textContent, /perspective.*changed/i);
  assert.ok(h.byId("ask-input"));
});

test("Ask does not send an incomplete party mapping", async () => {
  const h = harness([], { perspective: JSON.stringify([{ contractParty: "甲方", policyParty: "" }]) });
  await h.run();
  assert.equal(h.calls.length, 0);
  assert.match(h.byId("review-perspective-error").textContent, /Complete both fields/);
});

test("removing a represented party clears an existing Ask answer", async () => {
  const h = harness([{ answer: { Answer: "OLD MAPPING ANSWER", reviewPerspective: MULTIPLE } }], { perspective: MULTIPLE });
  await h.run();
  h.form.rows()[1].querySelector("button").click();
  assert.doesNotMatch(h.container.textContent, /OLD MAPPING ANSWER/);
  assert.match(h.container.textContent, /perspective.*changed/i);
});

test("Ask does not send the old perspective if it changes while Word is loading", async () => {
  const word = deferred();
  const h = harness([], { perspective: PARTY_A, wordSync: () => word.promise });
  const pending = h.run();
  h.setPerspective(PARTY_B);
  word.resolve();
  await pending;
  assert.equal(h.calls.length, 0);
});

test("a late Ask answer cannot replace a newer answer after perspective A to B to A", async () => {
  const oldResponse = deferred();
  const h = harness([oldResponse.promise, { answer: { Answer: "NEW ANSWER", reviewPerspective: PARTY_A } }], { perspective: PARTY_A });
  const first = h.run();
  await tick();
  h.setPerspective(PARTY_B);
  h.setPerspective(PARTY_A);
  h.byId("ask-input").value = "Latest question";
  await h.run();
  oldResponse.resolve({ answer: { Answer: "OLD ANSWER", reviewPerspective: PARTY_A } });
  await first;
  assert.match(h.container.textContent, /NEW ANSWER/);
  assert.doesNotMatch(h.container.textContent, /OLD ANSWER/);
});

test("Ask sends automatic index metadata and retains the original clickable passage behavior", async () => {
  const h = harness([{ answer: { Answer: "Answer", SearchResults: [{ title: "Termination", paragraph: "Same clause.", summary: "A matching passage" }] } }]);
  h.state.body = "Same clause.\nSame clause.";
  h.state.labels = ["1.", "2."];
  await h.run();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].payload.document_text, h.state.body);
  assert.equal(h.calls[0].payload.document_paragraphs[1].list_label, "2.");
  assert.match(h.calls[0].payload.filename, /^sha256-/);
  const passage = h.container.find(node => node.tagName === "div" && node._text === "Termination");
  assert.ok(passage);
  await passage.click();
  await tick();
  assert.equal(h.state.selectedRanges[0].text, "Same clause.");
  assert.doesNotMatch(h.container.textContent, /Contract References:/);
});
