const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { createWordHarness, moduleSource } = require("./helpers/word-document-harness.cjs");
const { createPerspectiveHarness, PARTY_A, PARTY_B, MULTIPLE, HOSTILE, displayPerspective } = require("./helpers/review-perspective-harness.cjs");

const root = path.resolve(__dirname, "..");
const readModule = relative => fs.readFileSync(path.join(root, relative), "utf8")
  .replace(/^import .*;\s*$/gm, "")
  .replace(/export (async )?function /g, "$1function ");

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
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(" "); }
  set innerHTML(value) {
    assert.equal(value, "", "Review content must use text nodes, never untrusted HTML");
    this.children = [];
    this._text = "";
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }
  addEventListener(type, listener) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
  }
  dispatchEvent(event) { for (const listener of this.listeners.get(event.type) || []) listener(event); }
  async click() { for (const listener of this.listeners.get("click") || []) await listener(); }
  find(predicate) {
    if (predicate(this)) return this;
    for (const child of this.children) {
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }
}

function deferred() {
  let resolve;
  const promise = new Promise(res => { resolve = res; });
  return { promise, resolve };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const reviewAnswer = (title, reviewPerspective = PARTY_A) => ({
  answer: { reviewPerspective, PolicyItems: [{ title, iscompliant: "yes", summary: "Applicable requirement", relevant_policy_item: "Exact rule" }] },
});

function harness(responses, { perspective = "", wordSync, policySets = ["A"] } = {}) {
  const form = createPerspectiveHarness();
  form.enhanceElement(Element);
  const roots = ["policy-results", "fetchPolicyData"].map(id => {
    const node = new Element(id === "review-perspective-input" ? "textarea" : "div");
    node.id = id;
    return node;
  });
  const byId = id => form.byId(id) || roots.map(node => node.find(child => child.id === id)).find(Boolean) || null;
  const calls = [];
  const state = { body: "ABC is Party A. CBD is Party C. Entire contract body.\nParty A must pay within 30 days.", selection: "Party A must pay within 30 days." };
  const stored = new Map([["pfendpoint", "http://localhost:8083/score"], ["language", "Chinese"]]);
  const window = new Element("window");
  window.getSelectedPolicySets = () => policySets;
  const sandbox = vm.createContext({
    URL, window, AbortController, Event,
    ...createWordHarness(state, wordSync),
    document: { getElementById: byId, createElement: tag => new Element(tag) },
    localStorage: { getItem: key => stored.get(key) ?? null },
    console: { log() {}, warn() {}, error() {} },
    Office: {
      CoercionType: { Ooxml: "ooxml" }, AsyncResultStatus: { Succeeded: "succeeded" },
      context: { requirements: { isSetSupported: () => true }, document: { getSelectedDataAsync: (_type, callback) => callback({ status: "succeeded", value: "<w:p/>" }) } },
    },
    fetch: async (url, options) => {
      calls.push({ url, payload: JSON.parse(options.body) });
      const data = await responses[calls.length - 1];
      assert.notEqual(data, undefined, "unexpected additional backend request");
      return { ok: true, status: 200, text: async () => JSON.stringify(data) };
    },
  });
  vm.runInContext(moduleSource(), sandbox);
  vm.runInContext(readModule("src/shared/local-endpoint.js"), sandbox);
  vm.runInContext(readModule("src/shared/review-perspective.js"), sandbox);
  form.setPerspective(perspective, false);
  vm.runInContext(readModule("src/taskpane/Containers/summary_selected.js"), sandbox);
  return {
    byId, calls, state, sandbox, form,
    run: () => sandbox.summary(),
    text: () => byId("policy-results").textContent,
    setPerspective: form.setPerspective,
  };
}

for (const perspective of ["", MULTIPLE, HOSTILE]) {
  test(`Review sends the selected clause, full contract and safe perspective: ${perspective || "neutral"}`, async () => {
    const h = harness([reviewAnswer("SCOPED REVIEW", perspective)], { perspective: `  ${perspective}  ` });
    await h.run();
    assert.equal(h.calls[0].payload.reviewPerspective, perspective);
    assert.equal(h.calls[0].payload.query_type, 2);
    assert.equal(h.calls[0].payload.question, h.state.selection);
    assert.equal(h.calls[0].payload.document_text, h.state.body);
    assert.deepEqual(h.calls[0].payload.policySets, ["A"]);
    assert.ok(h.text().includes(`Review Perspective: ${displayPerspective(perspective)}`));
    assert.match(h.text(), /SCOPED REVIEW/);
  });
}

for (const echo of [undefined, PARTY_B]) {
  test(`Review rejects an unconfirmed perspective: ${echo}`, async () => {
    const result = reviewAnswer("UNVERIFIED REVIEW");
    result.answer.reviewPerspective = echo;
    const h = harness([result], { perspective: PARTY_A });
    await h.run();
    assert.match(h.text(), /Review failed:/);
    assert.doesNotMatch(h.text(), /UNVERIFIED REVIEW/);
  });
}

test("changing perspective removes the previous Review and requests a rerun", async () => {
  const h = harness([reviewAnswer("OLD REVIEW")], { perspective: PARTY_A });
  await h.run();
  h.setPerspective(PARTY_B);
  assert.doesNotMatch(h.text(), /OLD REVIEW/);
  assert.match(h.text(), /perspective.*changed/i);
});

test("Review does not send an incomplete party mapping", async () => {
  const h = harness([], { perspective: JSON.stringify([{ contractParty: "", policyParty: "Seller" }]) });
  await h.run();
  assert.equal(h.calls.length, 0);
  assert.match(h.byId("review-perspective-error").textContent, /Complete both fields/);
  assert.equal(h.byId("fetchPolicyData").style.display, undefined);
});

test("removing a represented party clears the previous Review", async () => {
  const h = harness([reviewAnswer("OLD MAPPING REVIEW", MULTIPLE)], { perspective: MULTIPLE });
  await h.run();
  h.form.rows()[1].querySelector("button").click();
  assert.doesNotMatch(h.text(), /OLD MAPPING REVIEW/);
  assert.match(h.text(), /perspective.*changed/i);
});

test("Review does not send a stale request if perspective changes while Word is loading", async () => {
  const word = deferred();
  const h = harness([], { perspective: PARTY_A, wordSync: () => word.promise });
  const pending = h.run();
  h.setPerspective(PARTY_B);
  word.resolve();
  await pending;
  assert.equal(h.calls.length, 0);
});

test("a late Review cannot replace a newer one after perspective A to B to A", async () => {
  const oldResponse = deferred();
  const h = harness([oldResponse.promise, reviewAnswer("NEW REVIEW")], { perspective: PARTY_A });
  const first = h.run(); await tick();
  h.setPerspective(PARTY_B);
  h.setPerspective(PARTY_A);
  await h.run();
  oldResponse.resolve(reviewAnswer("OLD REVIEW"));
  await first;
  assert.match(h.text(), /NEW REVIEW/);
  assert.doesNotMatch(h.text(), /OLD REVIEW/);
});

test("neutral Review supports an older backend without an echoed perspective", async () => {
  const result = reviewAnswer("NEUTRAL REVIEW");
  delete result.answer.reviewPerspective;
  const h = harness([result]);
  await h.run();
  assert.match(h.text(), /NEUTRAL REVIEW/);
});

test("Review requires a selected policy set before calling the backend", async () => {
  const h = harness([], { policySets: [] });
  await h.run();
  assert.equal(h.calls.length, 0);
  assert.match(h.text(), /Please select at least one Policy Set in General Settings/);
  assert.equal(h.byId("fetchPolicyData").style.display, "");
});

test("Review with no applicable policy shows general analysis and editable wording", async () => {
  const result = { answer: { reviewPerspective: "", PolicyItems: [{
    title: "Payment deadline", summary: "The payment deadline is unclear.",
    iscompliant: "no", policy_ids: [], policy_citations: [], review_basis: "general",
    suggested_correction: "Specify the deadline.", corrected_text: ["Pay within thirty days."],
  }] } };
  const h = harness([result]);
  await h.run();
  assert.deepEqual(h.calls[0].payload.policySets, ["A"]);
  assert.match(h.text(), /General risk analysis/);
  assert.match(h.text(), /No matching company policy/);
  assert.match(h.text(), /Suggested Wording/);
  assert.doesNotMatch(h.text(), /Relevant Company Policy Item|company knowledge base/);
  const markup = h.byId("policy-results").find(node => node.tagName === "button" && node.textContent === "Mark-up");
  assert.ok(markup);
  await markup.click();
  assert.match(h.state.body, /Pay within thirty days\./);
});

test("a general Review without an identified issue does not offer Mark-up", async () => {
  const result = { answer: { reviewPerspective: "", PolicyItems: [{
    title: "Payment deadline", summary: "No obvious issue identified; no change is needed.",
    iscompliant: "yes", policy_ids: [], review_basis: "general", corrected_text: [],
  }] } };
  const h = harness([result]);
  await h.run();
  assert.match(h.text(), /No obvious issue identified/);
  assert.match(h.text(), /No matching company policy/);
  assert.doesNotMatch(h.text(), /Suggested Correction|Mark-up|company knowledge base/);
});

test("perspective helper tolerates a missing input and validates response identity", () => {
  const h = harness([]);
  h.sandbox.document.getElementById = () => null;
  assert.equal(h.sandbox.getReviewPerspective(), "");
  assert.doesNotThrow(() => h.sandbox.onReviewPerspectiveChange(() => {}));
  assert.doesNotThrow(() => h.sandbox.validateReviewPerspective({}, ""));
  assert.doesNotThrow(() => h.sandbox.validateReviewPerspective({ reviewPerspective: PARTY_A }, PARTY_A));
  for (const result of [null, {}, { reviewPerspective: null }, { reviewPerspective: [] }, { reviewPerspective: PARTY_B }]) {
    assert.throws(() => h.sandbox.validateReviewPerspective(result, PARTY_A), /backend did not confirm/);
  }
});

test("Review sends automatic index metadata and retains Mark-up of the current Word selection", async () => {
  const result = { answer: { reviewPerspective: PARTY_A, PolicyItems: [{ title: "Payment", iscompliant: "no", corrected_text: ["Revised wording."] }] } };
  const h = harness([result], { perspective: PARTY_A });
  h.state.labels = ["", "8."];
  await h.run();
  assert.equal(h.calls[0].payload.document_text, h.state.body);
  assert.equal(h.calls[0].payload.document_paragraphs[1].list_label, "8.");
  assert.match(h.calls[0].payload.filename, /^sha256-/);
  assert.equal(h.calls[0].payload.question, h.state.selection.trim());
  assert.ok(h.byId("policy-results").find(node => node.tagName === "button" && node.textContent === "Go To"));
  h.state.selection = "ABC is Party A.";
  const button = h.byId("policy-results").find(node => node.tagName === "button" && node.textContent === "Mark-up");
  await button.click();
  assert.match(h.state.body, /^Revised wording\./);
  assert.match(h.state.body, /Party A must pay within 30 days\.$/);
  assert.match(h.text(), /Mark-up/);
  assert.doesNotMatch(h.text(), /Contract References:/);
});
