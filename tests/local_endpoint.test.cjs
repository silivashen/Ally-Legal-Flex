const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../src/shared/local-endpoint.js"), "utf8")
  .replace("export function ", "function ");
const sandbox = vm.createContext({ URL });
vm.runInContext(source, sandbox);
const resolve = value => sandbox.resolveLocalEndpoint(value);

test("local endpoints use the HTTPS page's proxy without losing path or query", () => {
  assert.equal(resolve("http://localhost:8083/score?mode=review"), "/local-api/flow/score?mode=review");
  assert.equal(resolve("http://127.0.0.1:8084/policy-sets"), "/local-api/policy/policy-sets");
  assert.equal(resolve("https://localhost:8085/api/config"), "/local-api/model/api/config");
});

test("custom remote endpoints and unrelated URLs are preserved", () => {
  for (const value of [
    "https://review.example.com:8083/score", "http://localhost:9000/score",
    "http://localhost.example.com:8083/score", "ftp://localhost:8083/score",
    "http://user:password@localhost:8083/score", "/local-api/flow/score", null, "",
  ]) assert.equal(resolve(value), value);
});
