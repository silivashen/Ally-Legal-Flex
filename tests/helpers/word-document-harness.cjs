const { createHash } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

function moduleSource() {
  return fs.readFileSync(path.join(__dirname, "../../src/shared/word-document.js"), "utf8")
    .replace(/^export /gm, "");
}

function createWordHarness(state, syncHook) {
  state.selectedRanges = [];
  state.replacements = [];
  function range(start, end) {
    return {
      start, end,
      get text() { return state.body.slice(this.start, this.end); },
      load() {},
      getRange(location) {
        return range(location === "End" ? this.end : this.start, location === "Start" ? this.start : this.end);
      },
      expandTo(other) { return range(Math.min(this.start, other.start), Math.max(this.end, other.end)); },
      search(text) {
        if (text.length > 255 || /[\r\n\u0007\u000b]/.test(text)) throw new Error("Unsupported Word search query");
        const items = [];
        let offset = 0;
        while ((offset = this.text.indexOf(text, offset)) !== -1) {
          items.push(range(this.start + offset, this.start + offset + text.length));
          offset += Math.max(1, text.length);
        }
        return { items, load() {} };
      },
      select() { state.selectedRanges.push({ start: this.start, end: this.end, text: this.text }); },
      insertText(text) {
        state.replacements.push({ start: this.start, end: this.end, text });
        state.body = state.body.slice(0, this.start) + text + state.body.slice(this.end);
      },
    };
  }
  function context() {
    let offset = 0;
    const items = state.body.split(/\r\n|\r|\n/).map((text, index) => {
      const start = state.body.indexOf(text, offset);
      offset = start + text.length + (state.body.slice(start + text.length).startsWith("\r\n") ? 2 : 1);
      const listString = state.labels?.[index] || "";
      return { text, isListItem: !!listString, listItem: { listString, load() {} }, getRange: () => range(start, start + text.length) };
    });
    return {
      document: {
        body: { text: state.body, load() {}, paragraphs: { items, load() {} }, search: text => range(0, state.body.length).search(text) },
        getSelection() {
          const start = state.selectionStart ?? state.body.indexOf(state.selection || "");
          return range(Math.max(0, start), Math.max(0, start) + (state.selection || "").length);
        },
      },
      sync: syncHook || (async () => {}),
    };
  }
  return {
    crypto: { subtle: { digest: async (_algorithm, bytes) => Uint8Array.from(createHash("sha256").update(bytes).digest()).buffer } }, TextEncoder,
    Office: { context: { requirements: { isSetSupported: () => true } } },
    Word: { InsertLocation: { replace: "Replace" }, run: (first, second) => (second || first)(context()) },
  };
}

module.exports = { createWordHarness, moduleSource };
