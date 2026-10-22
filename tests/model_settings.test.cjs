const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../src/shared/model-settings.js"), "utf8")
  .replace("export function mountModelSettings", "function mountModelSettings");

class ElementStub {
  constructor(tag, ownerDocument) {
    this.tagName = tag;
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.value = "";
    this.textContent = "";
    this.listeners = new Map();
    this.attributes = new Map();
  }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  async click() {
    assert.equal(this.disabled, false);
    await this.listeners.get("click")();
  }
}

function harness(fetchImpl) {
  const doc = { createElement: tag => new ElementStub(tag, doc) };
  const container = doc.createElement("div");
  const calls = [];
  const context = vm.createContext({
    fetch: async (url, options) => {
      calls.push({ url, options });
      const data = await fetchImpl(url, options);
      return { ok: data.ok !== false, status: data.ok === false ? 400 : 200, json: async () => data };
    },
  });
  vm.runInContext(source, context);
  function get(id, node = container) {
    if (node.id === id) return node;
    for (const child of node.children) {
      const found = get(id, child);
      if (found) return found;
    }
    return null;
  }
  return { container, calls, get, mount: () => context.mountModelSettings(container) };
}

function configResponse(url) {
  return { ok: true, base_url: "https://provider.example/v1", model: url.includes("embedding") ? "vector-model" : "chat-model", has_api_key: true };
}

test("loads both model configurations once and preserves unsaved input when remounted", async () => {
  const h = harness(configResponse);
  await h.mount();
  assert.equal(h.container.children.length, 2);
  assert.deepEqual(h.calls.map(call => call.url), ["/local-api/model/api/config", "/local-api/model/api/embedding-config"]);
  assert.equal(h.get("ally-model-name").value, "chat-model");
  assert.equal(h.get("ally-embedding-model").value, "vector-model");
  assert.equal(h.get("ally-model-key").value, "");
  assert.match(h.get("ally-model-key-status").textContent, /saved locally/);
  h.get("ally-model-name").value = "unsaved-model";
  h.get("ally-model-key").value = "unsaved-key";
  await h.mount();
  assert.equal(h.calls.length, 2);
  assert.equal(h.container.children.length, 2);
  assert.equal(h.get("ally-model-name").value, "unsaved-model");
  assert.equal(h.get("ally-model-key").value, "unsaved-key");
});

test("both save operations keep their API URL and send blank keys to retain saved keys", async () => {
  const h = harness((url, options) => options.method === "GET" ? configResponse(url) : { ok: true, message: "Saved" });
  await h.mount();
  h.get("ally-model-url").value = " https://provider.example/v1 ";
  h.get("ally-model-name").value = " new-chat ";
  await h.get("ally-model-apply").click();
  const chatSave = h.calls.find(call => call.url.endsWith("/api/apply"));
  assert.deepEqual(JSON.parse(chatSave.options.body), { base_url: "https://provider.example/v1", model: "new-chat", api_key: "" });
  h.get("ally-embedding-model").value = "new-vector";
  await h.get("ally-embedding-save").click();
  const vectorSave = h.calls.find(call => call.url.endsWith("/api/embedding-config") && call.options.method === "POST");
  assert.deepEqual(JSON.parse(vectorSave.options.body), { base_url: "https://provider.example/v1", model: "new-vector", api_key: "" });
  assert.equal(h.get("ally-embedding-status").textContent, "Saved");
  assert.equal(h.get("ally-model-status").textContent, "Saved");
});

test("testing uses form values without saving or replacing an unsaved key", async () => {
  const h = harness((url, options) => options.method === "GET" ? configResponse(url) : { ok: true, message: "Connected" });
  await h.mount();
  h.get("ally-model-key").value = "new-chat-key";
  h.get("ally-embedding-key").value = "new-vector-key";
  await h.get("ally-model-test").click();
  await h.get("ally-embedding-test").click();
  assert.deepEqual(h.calls.slice(2).map(call => call.url), ["/local-api/model/api/test", "/local-api/model/api/embedding-test"]);
  assert.equal(JSON.parse(h.calls[2].options.body).api_key, "new-chat-key");
  assert.equal(JSON.parse(h.calls[3].options.body).api_key, "new-vector-key");
  assert.equal(h.get("ally-model-key").value, "new-chat-key");
  assert.equal(h.get("ally-embedding-key").value, "new-vector-key");
});

test("successful save clears submitted key while failure preserves it and unlocks the form", async () => {
  let fail = false;
  const h = harness((url, options) => options.method === "GET" ? configResponse(url) : fail ? { ok: false, message: "Server unavailable" } : { ok: true, message: "Saved" });
  await h.mount();
  h.get("ally-model-key").value = "chat-key";
  await h.get("ally-model-apply").click();
  assert.equal(h.get("ally-model-key").value, "");
  fail = true;
  h.get("ally-embedding-key").value = "vector-key";
  await h.get("ally-embedding-save").click();
  assert.equal(h.get("ally-embedding-key").value, "vector-key");
  assert.equal(h.get("ally-embedding-save").disabled, false);
  assert.match(h.get("ally-embedding-status").textContent, /Save failed: Server unavailable/);
});

test("configuration load errors are visible and leave the form available for correction", async () => {
  const h = harness(() => { throw new Error("Offline"); });
  await h.mount();
  assert.match(h.get("ally-model-status").textContent, /Unable to load configuration: Offline/);
  assert.match(h.get("ally-embedding-status").textContent, /Unable to load configuration: Offline/);
  assert.equal(h.get("ally-model-apply").disabled, false);
  assert.equal(h.get("ally-embedding-save").disabled, false);
});
