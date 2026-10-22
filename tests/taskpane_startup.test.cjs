const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { webcrypto } = require("node:crypto");

const root = path.resolve(__dirname, "..");
const taskpaneSource = fs.readFileSync(path.join(root, "src/taskpane/taskpane.js"), "utf8")
  .replace(/^import .*;\s*$/gm, "")
  .replace(/^export /gm, "");
const endpointSource = fs.readFileSync(path.join(root, "src/shared/local-endpoint.js"), "utf8")
  .replace("export function ", "function ");

for (const [savedEndpoint, expectedEndpoint] of [
  [null, "/local-api/flow/score"],
  ["http://localhost:8083/score?mode=review", "/local-api/flow/score?mode=review"],
  ["https://review.example.com/score", "https://review.example.com/score"],
]) {
  test(`Word startup reveals the taskpane and wires actions with ${savedEndpoint || "the relative default endpoint"}`, async () => {
    const stored = new Map(savedEndpoint ? [["pfendpoint", savedEndpoint]] : []);
    const nodes = new Map();
    const element = id => {
      if (!nodes.has(id)) nodes.set(id, { style: { display: "none" }, textContent: "", innerHTML: "" });
      return nodes.get(id);
    };
    const requests = [];
    const errors = [];
    const timers = [];
    let ready;
    const ask = () => {};
    const summary = () => {};
    const documentSummary = () => {};
    const sandbox = vm.createContext({
      URL, TextEncoder, crypto: webcrypto,
      ask, summary, document_summary: documentSummary,
      localStorage: {
        getItem: key => stored.get(key) ?? null,
        setItem: (key, value) => stored.set(key, String(value)),
      },
      document: { getElementById: id => ["language-select", "title-with-name"].includes(id) ? null : element(id) },
      Office: { HostType: { Word: "Word" }, onReady: callback => { ready = callback; } },
      Word: {
        run: async callback => callback({
          document: { body: { text: "A contract for the startup check", load() {} } },
          sync: async () => {},
        }),
      },
      console: { log() {}, error: (...args) => errors.push(args) },
      setTimeout: callback => { timers.push(callback); },
      fetch: async url => {
        requests.push(url);
        if (url === "assets/config.json") return {
          ok: true,
          json: async () => ({ "prompt-flow-endpoint": "/local-api/flow/score", "sso-enabled": false }),
        };
        assert.fail("Startup must not read or index a contract: " + url);
      },
    });
    vm.runInContext(endpointSource, sandbox);
    vm.runInContext(taskpaneSource, sandbox);
    await ready({ host: "Word" });
    // The existing startup schedules UI activation after its promise resolves.
    await new Promise(resolve => setImmediate(resolve));
    timers.forEach(callback => callback());

    assert.equal(element("app-body").style.display, "flex", JSON.stringify(errors));
    assert.equal(element("sideload-msg").style.display, "none");
    assert.equal(element("fetchSummaryData").onclick, documentSummary);
    element("fetchPolicyData").onclick();
    assert.equal(typeof element("ask-button").onclick, "function");
    assert.equal(stored.get("pfendpoint"), expectedEndpoint);
    assert.equal(errors.length, 0);
    assert.deepEqual(requests, ["assets/config.json"]);
    assert.equal(nodes.has("index-doc-button"), false);
  });
}
