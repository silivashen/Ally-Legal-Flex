const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { createPerspectiveHarness, MULTIPLE, HOSTILE, displayPerspective } = require("./helpers/review-perspective-harness.cjs");

function harness() {
  const form = createPerspectiveHarness();
  const sandbox = vm.createContext({ document: form.document, Event });
  const source = fs.readFileSync(path.resolve(__dirname, "../src/shared/review-perspective.js"), "utf8").replace(/export function /g, "function ");
  vm.runInContext(source, sandbox);
  return { ...form, sandbox };
}

test("starts with one blank mapping and a neutral perspective", () => {
  const h = harness();
  assert.equal(h.rows().length, 1);
  assert.equal(h.sandbox.getReviewPerspective(), "");
  assert.equal(h.sandbox.validateReviewPerspectiveInputs(), true);
});

test("multiple Unicode mappings reach the request as unambiguous structured data", () => {
  const h = harness();
  h.setPerspective(MULTIPLE);
  assert.equal(h.sandbox.getReviewPerspective(), MULTIPLE);
  assert.equal(h.sandbox.validateReviewPerspectiveInputs(), true);
  const label = new h.Element("div");
  h.sandbox.appendReviewPerspective(label, MULTIPLE);
  assert.equal(label.textContent, "Review Perspective: " + displayPerspective(MULTIPLE));
});

test("add and remove preserve other mappings, notify subscribers and focus a usable field", () => {
  const h = harness();
  h.setPerspective(MULTIPLE);
  let changes = 0;
  h.sandbox.onReviewPerspectiveChange(() => changes++);
  h.byId("add-mapping").click();
  assert.equal(h.rows().length, 3);
  assert.equal(h.document.activeElement, h.rows()[2].querySelector("input"));
  h.rows()[0].querySelector("button").click();
  assert.equal(h.rows()[0].querySelector('[name="policyParty"]').value, "CBD 公司");
  assert.equal(changes, 2);
  h.rows()[1].querySelector("button").click();
  h.rows()[0].querySelector("button").click();
  assert.equal(h.rows().length, 1);
  assert.equal(h.sandbox.getReviewPerspective(), "");
});

for (const mapping of [{ contractParty: "甲方", policyParty: "" }, { contractParty: "", policyParty: "Seller" }]) {
  test(`an incomplete mapping blocks requests and identifies the missing field: ${JSON.stringify(mapping)}`, () => {
    const h = harness();
    h.setPerspective(JSON.stringify([mapping]));
    assert.equal(h.sandbox.validateReviewPerspectiveInputs(), false);
    assert.match(h.byId("review-perspective-error").textContent, /both.*mapping 1/i);
    assert.equal(h.document.activeElement.value, "");
    h.document.activeElement.value = "Completed";
    h.document.activeElement.dispatchEvent({ type: "input", bubbles: true });
    assert.equal(h.sandbox.validateReviewPerspectiveInputs(), true);
    assert.equal(h.byId("review-perspective-error").textContent, "");
  });
}

test("blank rows are ignored and whitespace is trimmed without parsing names or equals signs", () => {
  const h = harness();
  h.setPerspective(JSON.stringify([{contractParty: "   ", policyParty: ""}, {contractParty: "  Party A  ", policyParty: " ABC = Group; Inc. "}]));
  assert.equal(h.sandbox.getReviewPerspective(), JSON.stringify([{contractParty: "Party A", policyParty: "ABC = Group; Inc."}]));
});

test("party names render as text, never HTML", () => {
  const h = harness(); h.setPerspective(HOSTILE);
  const label = new h.Element("div");
  h.sandbox.appendReviewPerspective(label, h.sandbox.getReviewPerspective());
  assert.equal(label.querySelectorAll("img").length, 0);
  assert.match(label.textContent, /<img src=x onerror=alert\(1\)>/);
});
