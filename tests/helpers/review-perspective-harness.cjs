const fs = require("node:fs");
const path = require("node:path");
const { parseDocument } = require("htmlparser2");

const PARTY_A = JSON.stringify([{ contractParty: "Party A", policyParty: "Seller" }]);
const PARTY_B = JSON.stringify([{ contractParty: "Party B", policyParty: "Buyer" }]);
const MULTIPLE = JSON.stringify([
  { contractParty: "甲方", policyParty: "ABC 公司" },
  { contractParty: "丙方", policyParty: "CBD 公司" },
]);
const HOSTILE = JSON.stringify([{ contractParty: "甲方", policyParty: "<img src=x onerror=alert(1)>" }]);
const displayPerspective = value => value ? JSON.parse(value).map(row => `${row.contractParty} = ${row.policyParty}`).join("\n") : "Neutral";

function createPerspectiveHarness() {
  let activeElement;
  class Element {
    constructor(tagName) {
      Object.assign(this, { tagName, children: [], attributes: {}, listeners: new Map(), style: {}, value: "", className: "", _text: "" });
      this.classList = { add: name => { this.className += ` ${name}`; } };
    }
    appendChild(child) { child.remove(); child.parentNode = this; this.children.push(child); return child; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren(...children) { this.children.slice().forEach(child => child.remove()); this._text = ""; this.append(...children); }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; }
    set textContent(text) { this.replaceChildren(); this._text = String(text); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
    setAttribute(name, value) { this.attributes ||= {}; this.attributes[name] = String(value); if (["id", "name", "type", "class"].includes(name)) this[name === "class" ? "className" : name] = String(value); }
    getAttribute(name) { return this.attributes?.[name] ?? null; }
    removeAttribute(name) { if (this.attributes) delete this.attributes[name]; }
    addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) || []), listener]); }
    dispatchEvent(event) { for (const callback of this.listeners.get(event.type) || []) callback(event); if (event.bubbles && this.parentNode) this.parentNode.dispatchEvent(event); }
    click() { this.dispatchEvent({ type: "click" }); }
    focus() { activeElement = this; }
    get nextElementSibling() { return this.parentNode?.children[this.parentNode.children.indexOf(this) + 1] || null; }
    get previousElementSibling() { return this.parentNode?.children[this.parentNode.children.indexOf(this) - 1] || null; }
    find(predicate) { if (predicate(this)) return this; for (const child of this.children) { const found = child.find(predicate); if (found) return found; } return null; }
    querySelectorAll(selector) {
      const matches = node => selector.startsWith(".") ? (node.className || "").split(/\s+/).includes(selector.slice(1))
        : selector.startsWith("[name=") ? node.name === selector.slice(6, -1).replaceAll('"', "")
        : node.tagName === selector;
      const result = [];
      const visit = node => { for (const child of node.children) { if (matches(child)) result.push(child); visit(child); } };
      visit(this); return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }
  const markup = fs.readFileSync(path.resolve(__dirname, "../../src/taskpane/taskpane.html"), "utf8");
  const findSource = node => node.attribs?.id === "review-perspective-container" ? node : (node.children || []).map(findSource).find(Boolean);
  const convert = node => {
    const element = new Element(node.name || "#text");
    for (const [name, value] of Object.entries(node.attribs || {})) element.setAttribute(name, value);
    element._text = node.data || "";
    (node.children || []).forEach(child => element.appendChild(convert(child)));
    return element;
  };
  const root = convert(findSource(parseDocument(markup)));
  const byId = id => root.find(node => node.id === id);
  const rows = () => byId("perspective-mappings")?.querySelectorAll(".perspective-mapping-row") || [];
  const setPerspective = (value, notify = true) => {
    const data = value.trim() ? JSON.parse(value) : [{ contractParty: "", policyParty: "" }];
    const holder = byId("perspective-mappings");
    if (!holder) throw new Error("Structured perspective form is missing");
    holder.replaceChildren();
    for (const mapping of data) {
      byId("add-mapping").click();
      const row = rows().at(-1);
      row.querySelector('[name="contractParty"]').value = mapping.contractParty;
      row.querySelector('[name="policyParty"]').value = mapping.policyParty;
    }
    if (notify) holder.dispatchEvent({ type: "input", bubbles: true });
  };
  const enhanceElement = Target => {
    for (const name of ["setAttribute", "getAttribute", "removeAttribute", "querySelector", "find", "focus"]) {
      if (!Target.prototype[name]) Target.prototype[name] = Element.prototype[name];
    }
    // Existing feature harnesses have their own checkbox query implementation.
    const originalQuery = Target.prototype.querySelectorAll;
    Target.prototype.querySelectorAll = function(selector) {
      return selector === ".perspective-mapping-row" || selector.startsWith("[name=") || ["input", "button"].includes(selector)
        ? Element.prototype.querySelectorAll.call(this, selector)
        : originalQuery?.call(this, selector) || [];
    };
    for (const name of ["nextElementSibling", "previousElementSibling"]) {
      Object.defineProperty(Target.prototype, name, Object.getOwnPropertyDescriptor(Element.prototype, name));
    }
    Target.prototype.value = "";
  };
  return { root, byId, rows, setPerspective, Element, enhanceElement,
    document: { getElementById: byId, createElement: tag => new Element(tag), get activeElement() { return activeElement; } },
  };
}
module.exports = { createPerspectiveHarness, PARTY_A, PARTY_B, MULTIPLE, HOSTILE, displayPerspective };
