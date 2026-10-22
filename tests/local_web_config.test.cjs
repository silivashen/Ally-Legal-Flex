const assert = require("node:assert/strict");
const test = require("node:test");
const DevServer = require("webpack-dev-server");
const createConfig = require("../webpack.config.js");

test("local web server keeps APIs on loopback without wildcard CORS", async () => {
  const config = await createConfig({ WEBPACK_BUILD: true }, { mode: "development" });
  assert.equal(config.devServer.host, "127.0.0.1");
  assert.notEqual(config.devServer.headers?.["Access-Control-Allow-Origin"], "*");
  const server = { options: config.devServer };
  for (const host of ["localhost:3000", "127.0.0.1:3000"]) {
    assert.equal(DevServer.prototype.checkHeader.call(server, { host }, "host"), true);
  }
  for (const host of ["attacker.example:3000", "localhost.attacker.example:3000"]) {
    assert.equal(DevServer.prototype.checkHeader.call(server, { host }, "host"), false);
  }
});

test("production mode does not redirect the local add-in to the old Azure site", async () => {
  const config = await createConfig({ WEBPACK_BUILD: true }, { mode: "production" });
  const copy = config.plugins.find(plugin => Array.isArray(plugin.patterns));
  const manifest = copy.patterns.find(pattern => pattern.from === "manifest*.xml");
  const content = Buffer.from('<SourceLocation DefaultValue="https://localhost:3000/taskpane.html"/>');
  const output = manifest.transform ? await manifest.transform(content) : content;
  assert.match(output.toString(), /https:\/\/localhost:3000\/taskpane.html/);
  assert.doesNotMatch(output.toString(), /azurewebsites/);
});
