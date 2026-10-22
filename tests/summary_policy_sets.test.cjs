const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createWordHarness, moduleSource } = require("./helpers/word-document-harness.cjs");
const { createPerspectiveHarness, PARTY_A, PARTY_B, MULTIPLE, HOSTILE, displayPerspective } = require("./helpers/review-perspective-harness.cjs");

const root = path.resolve(__dirname, "..");
const summarySource = fs.readFileSync(path.join(root, "src/taskpane/Containers/summary_document.js"), "utf8")
    .replace("export async function document_summary", "async function document_summary")
    .replace(/^import .*;\s*$/gm, "");
const selectorSource = fs.readFileSync(path.join(root, "src/taskpane/Containers/policy_sets_review.js"), "utf8");

class EventTargetStub {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, listener) {
        const listeners = this.listeners.get(type) || [];
        listeners.push(listener);
        this.listeners.set(type, listeners);
    }
    dispatchEvent(event) {
        for (const listener of this.listeners.get(event.type) || []) listener(event);
    }
    async click() { for (const listener of this.listeners.get("click") || []) await listener(); }
}

class ElementStub extends EventTargetStub {
    constructor(tagName) {
        super();
        this.tagName = tagName;
        this.children = [];
        this.style = {};
        this.dataset = {};
        this.classList = { add() {} };
        this._text = "";
    }
    appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
    replaceChildren() {
        for (const child of this.children) child.parentNode = null;
        this.children = [];
        this._text = "";
    }
    set innerHTML(value) {
        assert.equal(value, "", "test DOM only accepts safe container clearing");
        this.replaceChildren();
    }
    set textContent(value) { this.replaceChildren(); this._text = String(value); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(" "); }
    remove() {
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
        this.parentNode = null;
    }
    querySelectorAll() {
        const inputs = [];
        const visit = node => {
            if (node.tagName === "input" && node.type === "checkbox" && node.dataset.policySet && node.checked) inputs.push(node);
            node.children.forEach(visit);
        };
        this.children.forEach(visit);
        return inputs;
    }
}

function deferred() {
    let resolve, reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
}

function jsonResponse(data, status = 200) {
    return { ok: status < 400, status, text: async () => JSON.stringify(data), json: async () => data };
}

function harness({ selector = false, selected = ["A"], perspective = "", fetchImpl, wordSync } = {}) {
    const form = createPerspectiveHarness();
    form.enhanceElement(ElementStub);
    const roots = ["summary-container", "policy-set-options", "policy-set-error"].map(id => {
        const node = new ElementStub("div"); node.id = id; return node;
    });
    const document = new EventTargetStub();
    document.hidden = false;
    document.createElement = tag => new ElementStub(tag);
    document.createTextNode = text => { const node = new ElementStub("#text"); node.textContent = text; return node; };
    document.getElementById = id => {
        const search = nodes => {
            for (const node of nodes) {
                if (node.id === id) return node;
                const found = search(node.children);
                if (found) return found;
            }
            return null;
        };
        return form.byId(id) || search(roots);
    };
    const window = new EventTargetStub();
    let selection = selected;
    window.getSelectedPolicySets = () => selection;
    const calls = [];
    const stored = new Map([["pfendpoint", "http://summary.test"], ["language", "Chinese"]]);
    const state = { body: "Current contract" };
    const sandbox = vm.createContext({
        ...createWordHarness(state, wordSync),
        window, document, URL, Event,
        localStorage: { getItem: key => stored.get(key) ?? null, removeItem: key => stored.delete(key) },
        console: { log() {}, warn() {}, error() {} },
        AbortController,
        CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
        setTimeout, clearTimeout,
        fetch: async (url, options) => {
            calls.push({ url, options, payload: options?.body ? JSON.parse(options.body) : undefined });
            return fetchImpl ? fetchImpl(url, options, calls.length) : jsonResponse({ PolicySets: JSON.parse(options.body).policySets, Summary: "Verified summary", Items: [] });
        }
    });
    const endpointSource = fs.readFileSync(path.join(root, "src/shared/local-endpoint.js"), "utf8")
        .replace(/export function /g, "function ");
    vm.runInContext(moduleSource(), sandbox);
    vm.runInContext(endpointSource, sandbox);
    const perspectivePath = path.join(root, "src/shared/review-perspective.js");
    vm.runInContext(fs.readFileSync(perspectivePath, "utf8").replace(/export function /g, "function "), sandbox);
    form.setPerspective(perspective, false);
    vm.runInContext(summarySource, sandbox);
    if (selector) vm.runInContext(selectorSource, sandbox);
    return {
        calls, sandbox, window, document, state,
        run: () => vm.runInContext("document_summary()", sandbox),
        refresh: change => vm.runInContext(`initializePolicySetSelector(${JSON.stringify(change ?? null)})`, sandbox),
        setSelection: (next, notify = true) => {
            selection = next;
            if (notify) window.dispatchEvent({ type: "ally-policy-selection-changed" });
        },
        form, setPerspective: form.setPerspective,
        text: () => document.getElementById("summary-container").textContent,
        checked: () => Array.from(window.getSelectedPolicySets()),
        checkbox: name => document.getElementById("policy-set-options").children.map(label => label.children[0]).find(input => input.value === name)
    };
}

const tick = () => new Promise(resolve => setImmediate(resolve));

for (const selected of [["A"], ["A", "B"]]) {
    test(`sends and displays the exact selected sets: ${selected.join(",")}`, async () => {
        const h = harness({ selected });
        await h.run();
        assert.deepEqual(h.calls[0].payload.policySets, selected);
        assert.equal(h.calls[0].payload.query_type, 1);
        assert.match(h.text(), /Verified summary/);
        assert.match(h.text(), new RegExp(`Policy Sets: ${selected.join(", ")}`));
    });
}

test("no selection prevents a backend request", async () => {
    const h = harness({ selected: [] });
    await h.run();
    assert.equal(h.calls.length, 0);
    assert.match(h.text(), /select at least one Policy Set/);
});

test("selection changes clear an existing summary", async () => {
    const h = harness();
    await h.run();
    h.setSelection(["B"]);
    assert.doesNotMatch(h.text(), /Verified summary/);
    assert.match(h.text(), /selection changed/i);
});

test("changing selection while Word is loading prevents the old request", async () => {
    const word = deferred();
    const h = harness({ wordSync: () => word.promise });
    const pending = h.run();
    h.setSelection(["B"]);
    word.resolve();
    await pending;
    assert.equal(h.calls.length, 0);
    assert.doesNotMatch(h.text(), /Verified summary/);
});

test("a late response cannot replace a newer result, even when the original selection is restored", async () => {
    const responses = [deferred(), deferred()];
    const h = harness({ fetchImpl: (_url, _options, count) => responses[count - 1].promise });
    const first = h.run();
    await tick();
    h.setSelection(["B"]);
    h.setSelection(["A"]);
    const second = h.run();
    await tick();
    responses[1].resolve(jsonResponse({ PolicySets: ["A"], Summary: "NEW RESULT", Items: [] }));
    await second;
    responses[0].resolve(jsonResponse({ PolicySets: ["A"], Summary: "OLD RESULT", Items: [] }));
    await first;
    assert.match(h.text(), /NEW RESULT/);
    assert.doesNotMatch(h.text(), /OLD RESULT/);
});

test("an old request finishing cannot remove the newer request's spinner", async () => {
    const responses = [deferred(), deferred()];
    const h = harness({ fetchImpl: (_url, _options, count) => responses[count - 1].promise });
    const first = h.run(); await tick();
    const second = h.run(); await tick();
    const spinner = h.document.getElementById("summary-spinner");
    responses[0].reject(new Error("old request failed"));
    await first;
    assert.equal(h.document.getElementById("summary-spinner"), spinner);
    assert.equal(spinner.style.display, "block");
    assert.doesNotMatch(h.text(), /old request failed/);
    responses[1].resolve(jsonResponse({ PolicySets: ["A"], Summary: "NEW RESULT", Items: [] }));
    await second;
    assert.match(h.text(), /NEW RESULT/);
});

test("selection mismatch is rejected even if no selection event was delivered", async () => {
    const response = deferred();
    const h = harness({ fetchImpl: () => response.promise });
    const pending = h.run(); await tick();
    h.setSelection(["B"], false);
    response.resolve(jsonResponse({ PolicySets: ["A"], Summary: "STALE RESULT", Items: [] }));
    await pending;
    assert.doesNotMatch(h.text(), /STALE RESULT/);
});

for (const result of [
    { Summary: "UNVERIFIED RESULT", Items: [] },
    { PolicySets: ["B"], Summary: "UNVERIFIED RESULT", Items: [] },
    { PolicySets: ["A"], Summary: "UNVERIFIED RESULT", Items: [], error: "Policy lookup failed" }
]) {
    test(`rejects invalid or failed responses: ${JSON.stringify(result)}`, async () => {
        const h = harness({ fetchImpl: () => jsonResponse(result) });
        await h.run();
        assert.match(h.text(), /Summary failed:/);
        assert.doesNotMatch(h.text(), /UNVERIFIED RESULT/);
    });
}

test("selector refresh preserves changes made during the fetch and does not invalidate unchanged results", async () => {
    const refresh = deferred();
    let selectorCalls = 0;
    const h = harness({ selector: true, fetchImpl: url => {
        if (url.includes("policy-sets")) return ++selectorCalls === 1 ? jsonResponse({ policySets: ["A", "B"] }) : refresh.promise;
        return jsonResponse({ PolicySets: ["B"], Summary: "PRESERVED RESULT", Items: [] });
    } });
    await tick();
    h.checkbox("A").checked = true; h.checkbox("A").dispatchEvent({ type: "change" });
    const pending = h.refresh();
    h.checkbox("A").checked = false;
    h.checkbox("B").checked = true; h.checkbox("B").dispatchEvent({ type: "change" });
    await h.run();
    refresh.resolve(jsonResponse({ policySets: ["B", "A"] }));
    await pending;
    assert.deepEqual(h.checked(), ["B"]);
    assert.match(h.text(), /PRESERVED RESULT/);
});

test("selector rename/removal invalidates the previous summary and stale refreshes cannot restore old sets", async () => {
    const refreshes = [deferred(), deferred()];
    let selectorCalls = 0;
    const h = harness({ selector: true, fetchImpl: url => {
        if (url.includes("policy-sets")) return ++selectorCalls === 1 ? jsonResponse({ policySets: ["A", "B"] }) : refreshes[selectorCalls - 2].promise;
        return jsonResponse({ PolicySets: ["A"], Summary: "OLD SELECTION RESULT", Items: [] });
    } });
    await tick();
    h.checkbox("A").checked = true; h.checkbox("A").dispatchEvent({ type: "change" });
    await h.run();
    const oldRefresh = h.refresh({ action: "rename", oldName: "A", newName: "Renamed A" });
    const newRefresh = h.refresh();
    refreshes[1].resolve(jsonResponse({ policySets: ["Renamed A", "B"] }));
    await newRefresh;
    assert.deepEqual(h.checked(), ["Renamed A"]);
    assert.doesNotMatch(h.text(), /OLD SELECTION RESULT/);
    refreshes[0].resolve(jsonResponse({ policySets: ["A", "B"] }));
    await oldRefresh;
    assert.deepEqual(h.checked(), ["Renamed A"]);
});

test("removing a selected policy set clears the result and requires a new selection", async () => {
    let selectorCalls = 0;
    const h = harness({ selector: true, fetchImpl: url => {
        if (url.includes("policy-sets")) return jsonResponse({ policySets: ++selectorCalls === 1 ? ["A", "B"] : ["B"] });
        return jsonResponse({ PolicySets: ["A"], Summary: "REMOVED POLICY RESULT", Items: [] });
    } });
    await tick();
    h.checkbox("A").checked = true; h.checkbox("A").dispatchEvent({ type: "change" });
    await h.run();
    await h.refresh();
    assert.deepEqual(h.checked(), []);
    assert.doesNotMatch(h.text(), /REMOVED POLICY RESULT/);
    const count = h.calls.length;
    await h.run();
    assert.equal(h.calls.length, count);
    assert.match(h.text(), /select at least one Policy Set/);
});

test("Config removal notification clears only the removed checkbox and preserves the other selected sets", async () => {
    let policySets = ["A", "B", "C"];
    const h = harness({ selector: true, fetchImpl: url => {
        if (url.includes("policy-sets")) return jsonResponse({ policySets });
        return jsonResponse({ PolicySets: ["A", "B"], Summary: "OLD MULTI SET SUMMARY", Items: [] });
    } });
    await tick();
    h.checkbox("A").checked = true;
    h.checkbox("B").checked = true;
    h.checkbox("B").dispatchEvent({ type: "change" });
    await h.run();
    policySets = ["B", "C"];
    h.window.dispatchEvent({ type: "storage", key: "ally-policy-sets-updated",
        newValue: JSON.stringify({ type: "policy-sets-updated", action: "remove", oldName: "A" }) });
    await tick();
    assert.equal(h.checkbox("A"), undefined);
    assert.deepEqual(h.checked(), ["B"]);
    assert.equal(h.checkbox("C").checked, false);
    assert.doesNotMatch(h.text(), /OLD MULTI SET SUMMARY/);
    assert.equal(h.document.getElementById("policy-set-error").textContent, "");
});

test("deleting the last set clears selection and displays a normal empty state", async () => {
    let policySets = ["A"];
    const h = harness({ selector: true, fetchImpl: url => {
        if (url.includes("policy-sets")) return jsonResponse({ policySets });
        return jsonResponse({ PolicySets: ["A"], Summary: "LAST SET SUMMARY", Items: [] });
    } });
    await tick();
    h.checkbox("A").checked = true;
    h.checkbox("A").dispatchEvent({ type: "change" });
    await h.run();
    policySets = [];
    h.window.dispatchEvent({ type: "storage", key: "ally-policy-sets-updated",
        newValue: JSON.stringify({ type: "policy-sets-updated", action: "remove", oldName: "A" }) });
    await tick();
    assert.deepEqual(h.checked(), []);
    assert.equal(h.document.getElementById("policy-set-options").textContent, "No policy sets yet. Add one in Config.");
    assert.equal(h.document.getElementById("policy-set-error").style.display, "none");
    assert.equal(h.document.getElementById("policy-set-error").textContent, "");
    assert.doesNotMatch(h.text(), /LAST SET SUMMARY/);
    const count = h.calls.length;
    await h.run();
    assert.equal(h.calls.length, count);
    assert.match(h.text(), /select at least one Policy Set/);
});

test("failed selector refresh clears selected policies and the old result", async () => {
    let selectorCalls = 0;
    const h = harness({ selector: true, fetchImpl: url => {
        if (url.includes("policy-sets")) return ++selectorCalls === 1
            ? jsonResponse({ policySets: ["A"] }) : jsonResponse({ error: "offline" }, 500);
        return jsonResponse({ PolicySets: ["A"], Summary: "PREVIOUS RESULT", Items: [] });
    } });
    await tick();
    h.checkbox("A").checked = true; h.checkbox("A").dispatchEvent({ type: "change" });
    await h.run();
    await h.refresh();
    assert.deepEqual(h.checked(), []);
    assert.doesNotMatch(h.text(), /PREVIOUS RESULT/);
    assert.match(h.document.getElementById("policy-set-error").textContent, /local service/);
});


for (const perspective of ["", MULTIPLE, HOSTILE]) {
    test(`Summary transmits and safely displays the perspective: ${perspective || "neutral"}`, async () => {
        const h = harness({ perspective: `  ${perspective}  `, fetchImpl: () => jsonResponse({
            PolicySets: ["A"], Summary: "SCOPED SUMMARY", Items: [], reviewPerspective: perspective,
        }) });
        await h.run();
        assert.equal(h.calls[0].payload.reviewPerspective, perspective);
        assert.ok(h.text().includes(`Review Perspective: ${displayPerspective(perspective)}`));
        assert.match(h.text(), /SCOPED SUMMARY/);
    });
}

for (const echo of [undefined, PARTY_B]) {
    test(`Summary rejects an unconfirmed perspective: ${echo}`, async () => {
        const h = harness({ perspective: PARTY_A, fetchImpl: () => jsonResponse({
            PolicySets: ["A"], Summary: "UNVERIFIED SUMMARY", Items: [], reviewPerspective: echo,
        }) });
        await h.run();
        assert.match(h.text(), /Summary failed:/);
        assert.doesNotMatch(h.text(), /UNVERIFIED SUMMARY/);
    });
}

test("changing perspective clears an existing Summary", async () => {
    const h = harness({ perspective: PARTY_A, fetchImpl: () => jsonResponse({
        PolicySets: ["A"], Summary: "OLD SUMMARY", Items: [], reviewPerspective: PARTY_A,
    }) });
    await h.run();
    h.setPerspective(PARTY_B);
    assert.doesNotMatch(h.text(), /OLD SUMMARY/);
    assert.match(h.text(), /perspective.*changed/i);
});

test("Summary does not send an incomplete party mapping", async () => {
    const h = harness({ perspective: JSON.stringify([{ contractParty: "甲方", policyParty: "" }]) });
    await h.run();
    assert.equal(h.calls.length, 0);
    assert.match(h.document.getElementById("review-perspective-error").textContent, /Complete both fields/);
});

test("removing a represented party clears the previous Summary", async () => {
    const h = harness({ perspective: MULTIPLE, fetchImpl: () => jsonResponse({
        PolicySets: ["A"], Summary: "OLD MAPPING SUMMARY", Items: [], reviewPerspective: MULTIPLE,
    }) });
    await h.run();
    h.form.rows()[1].querySelector("button").click();
    assert.doesNotMatch(h.text(), /OLD MAPPING SUMMARY/);
    assert.match(h.text(), /perspective.*changed/i);
});

test("Summary does not send the old perspective if it changes while Word is loading", async () => {
    const word = deferred();
    const h = harness({ perspective: PARTY_A, wordSync: () => word.promise });
    const pending = h.run();
    h.setPerspective(PARTY_B);
    word.resolve();
    await pending;
    assert.equal(h.calls.length, 0);
});

test("a late Summary cannot replace a newer one after perspective A to B to A", async () => {
    const responses = [deferred(), deferred()];
    const h = harness({ perspective: PARTY_A, fetchImpl: (_url, _options, count) => responses[count - 1].promise });
    const first = h.run(); await tick();
    h.setPerspective(PARTY_B);
    h.setPerspective(PARTY_A);
    const second = h.run(); await tick();
    responses[1].resolve(jsonResponse({ PolicySets: ["A"], Summary: "NEW SUMMARY", Items: [], reviewPerspective: PARTY_A }));
    await second;
    responses[0].resolve(jsonResponse({ PolicySets: ["A"], Summary: "OLD SUMMARY", Items: [], reviewPerspective: PARTY_A }));
    await first;
    assert.match(h.text(), /NEW SUMMARY/);
    assert.doesNotMatch(h.text(), /OLD SUMMARY/);
});

test("Summary sends automatic index metadata while keeping its original result and Go to button", async () => {
    const h = harness({ fetchImpl: () => jsonResponse({ PolicySets: ["A"], Summary: "Original summary", Items: [{ title: "Clause", original_text: "Current contract" }] }) });
    h.state.labels = ["4.1"];
    await h.run();
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].payload.document_text, h.state.body);
    assert.equal(h.calls[0].payload.question, h.state.body.trim());
    assert.equal(h.calls[0].payload.document_paragraphs[0].list_label, "4.1");
    assert.match(h.calls[0].payload.filename, /^sha256-/);
    assert.match(h.text(), /Original summary/);
    const content = h.document.getElementById("doc-summary-content-0");
    const goto = content.children.find(node => node.tagName === "button" && node.textContent === "Go to");
    assert.ok(goto);
    await goto.click();
    await tick();
    assert.equal(h.state.selectedRanges[0].text, "Current contract");
    assert.doesNotMatch(h.text(), /Contract References:/);
});
