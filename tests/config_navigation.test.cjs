const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parseDocument } = require('htmlparser2');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/configpane/configpane.js'), 'utf8').replace(/^import .*;\s*$/gm, '');
const modelSource = fs.readFileSync(path.join(root, 'src/shared/model-settings.js'), 'utf8').replace('export function mountModelSettings', 'function mountModelSettings');
const promptSource = fs.readFileSync(path.join(root, 'src/shared/prompt-settings.js'), 'utf8').replace('export function mountPromptSettings', 'function mountPromptSettings');
const html = fs.readFileSync(path.join(root, 'src/configpane/configpane.html'), 'utf8');

class Element {
  constructor(tagName, doc) {
    this.tagName = tagName;
    this.ownerDocument = doc;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.value = '';
    this._text = '';
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }
  insertBefore(child, before) { child.parentNode = this; this.children.splice(this.children.indexOf(before), 0, child); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  set innerHTML(value) {
    this.textContent = '';
    const convert = node => {
      const e = new Element(node.name || '#text', this.ownerDocument);
      Object.assign(e, node.attribs || {});
      e.className = node.attribs?.class || '';
      e._text = node.data || '';
      for (const child of node.children || []) e.appendChild(convert(child));
      return e;
    };
    for (const node of parseDocument(value).children) this.appendChild(convert(node));
  }
  find(predicate) {
    if (predicate(this)) return this;
    for (const child of this.children) { const found = child.find(predicate); if (found) return found; }
    return null;
  }
  contains(element) { return Boolean(this.find(node => node === element)); }
  matches(selector) {
    if (selector.includes(',')) return selector.split(',').some(part => this.matches(part.trim()));
    const enabled = selector.replace(/:not\((?:\[disabled\]|:disabled)\)/g, '');
    if (enabled !== selector && this.disabled) return false;
    selector = enabled;
    const attributes = Array.from(selector.matchAll(/\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]/g));
    if (attributes.some(([, key, value]) => value === undefined
      ? !(key in this.attributes || this[key]) : String(this.attributes[key] ?? this[key]) !== value)) return false;
    selector = selector.replace(/\[[^\]]+\]/g, '');
    if (!selector) return true;
    return selector.startsWith('#') ? this.id === selector.slice(1)
      : selector.startsWith('.') ? (this.className || '').split(' ').includes(selector.slice(1)) : this.tagName === selector;
  }
  querySelector(selector) {
    return this.find(node => node.matches(selector));
  }
  querySelectorAll(selector) {
    const matches = [];
    const visit = node => { if (node.matches(selector)) matches.push(node); node.children.forEach(visit); };
    this.children.forEach(visit);
    return matches;
  }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  removeEventListener(type, listener) { this.listeners[type] = (this.listeners[type] || []).filter(item => item !== listener); }
  async dispatch(type, extra = {}) {
    const event = { preventDefault() {}, stopPropagation() {}, target: this, ...extra };
    for (const listener of this.listeners[type] || []) await listener(event);
    if (this.parentNode) await this.parentNode.dispatch(type, event);
    else if (this !== this.ownerDocument) await this.ownerDocument.dispatch(type, event);
  }
  click() { if (!this.disabled) return this.dispatch('click'); return Promise.resolve(); }
  focus() { this.ownerDocument.activeElement = this; }
  select() {}
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness({ waitPolicies, failPolicies = false, policies, policySets, failDelete = false, waitDelete, broadcast = false, failSavePolicies = false, failImport = false, waitImportPreview, waitImport, failExport = false, failPrompts = false, failPromptSave = false, waitPrompts } = {}) {
  const doc = new Element('document', null);
  doc.ownerDocument = doc;
  doc.createElement = tag => new Element(tag, doc);
  const tree = doc.createElement('document');
  tree.innerHTML = html;
  doc.getElementById = id => tree.find(node => node.id === id);
  doc.body = tree.querySelector('body');
  doc.activeElement = doc.body;
  doc.querySelector = selector => tree.querySelector(selector);
  doc.querySelectorAll = selector => tree.querySelectorAll(selector);
  const get = doc.getElementById;
  const calls = [];
  const messages = [];
  const downloads = [];
  const downloadURLs = [];
  let ready;
  const state = {
    failPolicies, failDelete, failSavePolicies, failImport, failPrompts, failPromptSave,
    prompts: Object.fromEntries(['ask', 'summary', 'review'].map(key => [key, {
      text: key + ' default prompt {language}', default: key + ' default prompt {language}', customized: false, version: key + '-v0',
    }])),
    policies: policies ?? [{ id: 1, title: 'Cap', instruction: 'Set liability cap', policySet: 'General Policies', severity: 1 }],
    policySets: policySets ?? ['General Policies', 'Supply'],
  };
  const BroadcastChannel = broadcast ? class {
    constructor(name) { this.name = name; }
    postMessage(data) { messages.push({ channel: this.name, data }); }
    close() {}
  } : undefined;
  const context = vm.createContext({
    document: doc,
    console: { error() {} },
    alert() { throw new Error('Function window.alert is not supported.'); },
    confirm() { throw new Error('Function window.confirm is not supported.'); },
    prompt() { throw new Error('Function window.prompt is not supported.'); },
    localStorage: { setItem(key, value) { messages.push({ key, data: JSON.parse(value) }); } },
    BroadcastChannel,
    URL: {
      createObjectURL(blob) { downloadURLs.push({ created: blob }); return 'blob:synthetic-download'; },
      revokeObjectURL(url) { downloadURLs.push({ revoked: url }); },
    },
    setTimeout(callback) { callback(); },
    FileReader: class {
      readAsDataURL(file) {
        this.result = 'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,' + file.base64;
        queueMicrotask(() => this.onload());
      }
    },
    Office: { HostType: { Word: 'Word' }, onReady(callback) { ready = callback; } },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      let data;
      let status = 200;
      if (options.method === 'POST') {
        if (url === '/local-api/policy/prompt-settings') {
          if (state.failPromptSave) {
            status = 409; data = { error: 'This prompt changed in another window.' };
          } else {
            const body = JSON.parse(options.body), old = state.prompts[body.feature];
            assert.equal(body.expectedVersion, old.version);
            const text = body.reset ? old.default : body.text;
            const prompt = { ...old, text, customized: text !== old.default, version: old.version + '-saved' };
            state.prompts[body.feature] = prompt;
            data = { success: true, prompt: { ...prompt } };
          }
        }
        else if (url === '/local-api/policy/policies/import/preview') {
          if (waitImportPreview) await waitImportPreview;
          data = { success: true, added: 1, skipped: 0, conflicts: 0, previewToken: 'preview-token',
            rows: [{ row: 2, title: '<img src=x onerror=alert(1)>', instruction: 'Imported requirement', severity: 2, tags: [], groups: [], status: 'ready' }] };
        } else if (url === '/local-api/policy/policies/import') {
          if (waitImport) await waitImport;
          if (state.failImport) {
            status = 409;
            data = { success: false, error: 'Policies changed. Preview again.' };
          } else {
            const body = JSON.parse(options.body);
            assert.equal(body.previewToken, 'preview-token');
            state.policies.push({ id: 99, title: 'Imported', instruction: 'Imported requirement', policySet: body.policySet, severity: 2 });
            data = { success: true, added: 1, skipped: 0 };
          }
        } else if (url.endsWith('/delete')) {
          if (waitDelete) await waitDelete;
          if (state.failDelete) {
            status = 409;
            data = { success: false, error: 'Policy data changed. Refresh and try again.' };
          } else {
            const body = JSON.parse(options.body);
            if (url.endsWith('/policies/delete')) {
              const index = state.policies.findIndex(policy => JSON.stringify(policy) === JSON.stringify(body.policy));
              assert.notEqual(index, -1, 'delete must identify the original complete policy');
              state.policies.splice(index, 1);
            } else if (url.endsWith('/policy-sets/delete')) {
              assert.ok(state.policySets.includes(body.name), 'delete must identify an existing set');
              assert.equal(state.policies.some(policy => (policy.policySet || 'General Policies') === body.name), false,
                'nonempty sets must never be sent to the delete endpoint');
              state.policySets = state.policySets.filter(name => name !== body.name);
            } else throw new Error('Unexpected delete URL: ' + url);
          }
        } else if (url === '/local-api/policy/policies') {
          const body = JSON.parse(options.body);
          if (state.failSavePolicies || body.policies.some(policy => !state.policySets.includes(policy.policySet || 'General Policies'))) {
            status = 409;
            data = { success: false, error: 'Policies must refer to registered policy sets.' };
          } else state.policies = body.policies;
        } else if (url === '/local-api/policy/policy-sets') {
          const body = JSON.parse(options.body);
          if (state.policies.some(policy => !body.policySets.includes(policy.policySet || 'General Policies'))) {
            status = 409;
            data = { success: false, error: 'A nonempty policy set cannot be removed.' };
          } else state.policySets = body.policySets;
        }
        data ||= { success: true, ok: true };
      }
      else if (url === '/local-api/policy/prompt-settings') {
        if (waitPrompts) await waitPrompts;
        status = state.failPrompts ? 500 : 200;
        data = state.failPrompts ? { error: 'Could not read local prompt settings.' }
          : { success: true, prompts: JSON.parse(JSON.stringify(state.prompts)) };
      }
      else if (url.startsWith('/local-api/policy/policies/export?')) {
        status = failExport ? 400 : 200;
        data = { error: 'Selected set no longer exists.' };
        return { ok: !failExport, status, json: async () => data, blob: async () => 'synthetic-workbook' };
      }
      else if (url.endsWith('/policies')) {
        if (waitPolicies) await waitPolicies;
        if (state.failPolicies) throw new Error('Offline');
        data = { policies: state.policies };
      } else if (url.endsWith('/policy-sets')) data = { policySets: state.policySets };
      else if (url.startsWith('/local-api/model/')) data = { ok: true, base_url: 'https://model.example/v1', model: 'configured-model', has_api_key: true };
      else throw new Error('Unexpected URL: ' + url);
      return { ok: status < 400, status, json: async () => data };
    },
  });
  doc.addEventListener('click', event => {
    if (event.target.tagName === 'a' && event.target.download) {
      downloads.push({ name: event.target.download, href: event.target.href });
    }
  });
  context.window = context;
  vm.runInContext(modelSource + '\n' + promptSource + '\n' + source, context);
  ready({ host: 'Word' });
  return { get, calls, state, doc, messages, downloads, downloadURLs, tab: name => get('config-tab-' + name).click() };
}
function assertModelsSelected(h) {
  assert.equal(h.get('config-panel-models').hidden, false);
  assert.equal(h.get('config-panel-policies').hidden, true);
  assert.equal(h.get('config-tab-models').attributes['aria-selected'], 'true');
}

test('prompt bookmarks preserve separate drafts across features and config sections', async () => {
  const h = harness(); await flush();
  assert.equal(h.calls.some(call => call.url.endsWith('/prompt-settings')), false);
  await h.tab('prompts'); await flush();
  assert.equal(h.get('config-panel-prompts').hidden, false);
  assert.equal(h.get('prompt-text').value, 'ask default prompt {language}');
  assert.equal(h.get('prompt-state').textContent, 'Built-in');
  assert.equal(h.get('prompt-reset').disabled, true);
  const promptPanel = h.get('prompt-settings-container').querySelector('.prompt-settings');
  const commonHelp = promptPanel.querySelector('.prompt-common-help');
  assert.ok(promptPanel.children.indexOf(commonHelp) > promptPanel.children.indexOf(h.get('prompt-editor-panel')));
  assert.match(commonHelp.textContent, /Keep the default JSON field names unchanged/);
  const editor = h.get('prompt-text');
  editor.value = 'Ask draft <img src=x onerror=alert(1)>';
  await editor.dispatch('input');
  assert.match(h.get('prompt-state').textContent, /Unsaved changes/);
  assert.equal(h.get('prompt-reset').disabled, false);
  await h.get('prompt-feature-summary').click();
  editor.value = 'Summary draft'; await editor.dispatch('input');
  await h.tab('models'); await flush();
  await h.tab('prompts');
  assert.equal(editor.value, 'Summary draft');
  await h.get('prompt-feature-ask').click();
  assert.equal(editor.value, 'Ask draft <img src=x onerror=alert(1)>');
  assert.equal(h.get('prompt-settings-container').querySelector('img'), null);
  assert.equal(h.calls.filter(call => call.url.endsWith('/prompt-settings')).length, 1);
});

test('saving or restoring a prompt changes only the selected function', async () => {
  const h = harness(); await flush(); await h.tab('prompts'); await flush();
  h.get('prompt-text').value = 'Custom Ask'; await h.get('prompt-text').dispatch('input');
  await h.get('prompt-save').click();
  assert.equal(h.state.prompts.ask.text, 'Custom Ask');
  assert.equal(h.state.prompts.summary.customized, false);
  assert.equal(h.get('prompt-state').textContent, 'Customized');
  assert.equal(h.get('prompt-save').disabled, true);
  assert.equal(h.get('prompt-reset').disabled, false);
  await h.get('prompt-reset').click();
  assert.equal(h.get('prompt-text').value, h.state.prompts.ask.default);
  assert.equal(h.get('prompt-state').textContent, 'Built-in');
  assert.equal(h.get('prompt-reset').disabled, true);
});

test('prompt errors keep drafts and reload refreshes versions without discarding edits', async () => {
  const h = harness({ failPromptSave: true }); await flush(); await h.tab('prompts'); await flush();
  h.get('prompt-text').value = 'Keep my draft'; await h.get('prompt-text').dispatch('input');
  await h.get('prompt-save').click();
  assert.equal(h.get('prompt-text').value, 'Keep my draft');
  assert.match(h.get('prompt-status').textContent, /edits are still here/);
  assert.equal(h.get('prompt-reload').hidden, false);
  h.state.prompts.ask.version = 'updated-elsewhere';
  await h.get('prompt-reload').click();
  assert.equal(h.get('prompt-text').value, 'Keep my draft');
  h.state.failPromptSave = false;
  await h.get('prompt-save').click();
  assert.equal(h.state.prompts.ask.text, 'Keep my draft');
});

test('prompt load failure can be retried without blocking other settings', async () => {
  const h = harness({ failPrompts: true }); await flush(); await h.tab('prompts'); await flush();
  assert.equal(h.get('prompt-save').disabled, true);
  assert.equal(h.get('prompt-text').disabled, true);
  assert.match(h.get('prompt-status').textContent, /Could not read/);
  await h.tab('models'); assertModelsSelected(h);
  await h.tab('prompts'); h.state.failPrompts = false;
  await h.get('prompt-reload').click();
  assert.equal(h.get('prompt-text').disabled, false);
  await h.get('prompt-feature-ask').dispatch('keydown', { key: 'End' });
  assert.equal(h.get('prompt-feature-review').attributes['aria-selected'], 'true');
  await h.get('config-tab-prompts').dispatch('keydown', { key: 'ArrowRight' });
  assert.equal(h.get('config-panel-policies').hidden, false);
  await h.get('config-tab-policies').dispatch('keydown', { key: 'ArrowLeft' });
  assert.equal(h.get('config-panel-prompts').hidden, false);
});

async function importPreview(h) {
  await h.get('policy-import-open').click();
  const file = h.get('policy-import-file');
  file.files = [{ name: 'policies.xlsx', size: 1024, base64: 'c3ludGhldGlj' }];
  await file.dispatch('change');
  await h.get('policy-import-preview').click();
  await flush();
}

test('Excel import belongs to the selected set and preview never saves or renders uploaded HTML', async () => {
  const h = harness(); await flush();
  h.get('policy-set-filter').value = 'Supply';
  await h.get('policy-set-filter').dispatch('change');
  await importPreview(h);
  assert.match(h.get('policy-import-panel').textContent, /Supply/);
  const parent = h.get('policy-import-panel').parentNode;
  assert.ok(parent.children.indexOf(h.get('policy-import-panel')) < parent.children.indexOf(h.get('company-policy-list')));
  assert.equal(h.state.policies.length, 1);
  assert.equal(h.get('policy-import-confirm').disabled, false);
  assert.equal(h.get('policy-import-panel').querySelector('img'), null);
  assert.match(h.get('policy-import-panel').textContent, /<img src=x/);
  assert.equal(Boolean(h.get('policy-import-panel').querySelector('a')), false);
  assert.equal(h.get('policy-import-open').textContent, 'Import Excel');
  assert.equal(h.get('policy-export').textContent, 'Download Excel');
  assert.match(h.doc.querySelector('.policy-exchange-tools').textContent, /share or move/);
  assert.equal(h.get('policy-template-download').href, '/local-api/policy/policies/import-template');
  assert.equal(h.get('policy-template-download').textContent, 'Download Template');
  await h.get('policy-import-confirm').click();
  await flush();
  assert.equal(h.state.policies[0].title, 'Cap');
  assert.equal(h.state.policies[1].policySet, 'Supply');
  assert.equal(h.get('policy-set-filter').value, 'Supply');
  assert.equal(h.get('policy-import-panel'), null);
});

test('changing the target set discards its import preview without writing', async () => {
  const h = harness(); await flush();
  await importPreview(h);
  h.get('policy-set-filter').value = 'Supply';
  await h.get('policy-set-filter').dispatch('change');
  assert.equal(h.get('policy-import-panel'), null);
  assert.equal(h.state.policies.length, 1);
});

test('Excel file selection uses English controls and updates the visible filename', async () => {
  const h = harness(); await flush();
  await h.get('policy-import-open').click();
  const input = h.get('policy-import-file');
  const choose = h.get('policy-import-choose-file');
  assert.equal(input.hidden, true);
  assert.equal(choose.textContent, 'Choose File');
  assert.equal(h.get('policy-import-filename').textContent, 'No file selected');
  assert.ok(h.doc.activeElement === choose);
  let clicks = 0;
  input.addEventListener('click', () => { clicks += 1; });
  await choose.click();
  assert.equal(clicks, 1);
  input.files = [{ name: 'rules.xlsx', size: 1024, base64: 'c3ludGhldGlj' }];
  await input.dispatch('change');
  assert.equal(h.get('policy-import-filename').textContent, 'rules.xlsx');
  assert.equal(h.get('policy-import-preview').disabled, false);
  input.files = [];
  await input.dispatch('change');
  assert.equal(h.get('policy-import-filename').textContent, 'No file selected');
  assert.equal(h.get('policy-import-preview').disabled, true);
});

test('Excel download uses the selected set, names the file and releases its URL', async () => {
  const h = harness({ policySets: ['采购 / Supply'] }); await flush();
  await h.get('policy-export').click();
  assert.ok(h.calls.some(call => call.url === '/local-api/policy/policies/export?policySet=' + encodeURIComponent('采购 / Supply')));
  assert.equal(h.downloads[0].name, '采购 _ Supply-policies.xlsx');
  assert.equal(h.downloadURLs[1].revoked, 'blob:synthetic-download');
  assert.equal(h.get('policy-export').disabled, false);
  assert.equal(h.state.policies.length, 1);
});

test('failed Excel download shows an error without producing a file', async () => {
  const h = harness({ failExport: true }); await flush();
  await h.get('policy-export').click();
  assert.equal(h.downloads.length, 0);
  assert.match(h.doc.querySelector('.config-notice').textContent, /Selected set no longer exists/);
  assert.equal(h.get('policy-export').disabled, false);
});

test('a failed import preserves existing policies and requires a fresh preview', async () => {
  const h = harness({ failImport: true }); await flush();
  await importPreview(h);
  await h.get('policy-import-confirm').click();
  assert.equal(h.state.policies.length, 1);
  assert.equal(h.get('policy-import-confirm').disabled, true);
  assert.match(h.get('policy-import-status').textContent, /Preview again/);
});

test('invalid Excel selection cannot upload and no set means import is disabled', async () => {
  const h = harness(); await flush();
  await h.get('policy-import-open').click();
  const file = h.get('policy-import-file');
  for (const item of [{ name: 'rules.xls', size: 100 }, { name: 'rules.xlsx', size: 4 * 1024 * 1024 }]) {
    file.files = [item];
    await file.dispatch('change');
    assert.equal(h.get('policy-import-preview').disabled, true);
  }
  assert.equal(h.calls.some(call => call.url.includes('/import/')), false);
  const empty = harness({ policies: [], policySets: [] }); await flush();
  assert.equal(empty.get('policy-import-open').disabled, true);
  assert.equal(empty.get('policy-export').disabled, true);
});

test('a late preview cannot appear in another set and double confirmation sends one import', async () => {
  let finishPreview;
  const waitImportPreview = new Promise(resolve => { finishPreview = resolve; });
  const h = harness({ waitImportPreview }); await flush();
  await h.get('policy-import-open').click();
  const file = h.get('policy-import-file');
  file.files = [{ name: 'rules.xlsx', size: 1024, base64: 'c3ludGhldGlj' }];
  await file.dispatch('change');
  const pending = h.get('policy-import-preview').click();
  h.get('policy-set-filter').value = 'Supply';
  await h.get('policy-set-filter').dispatch('change');
  finishPreview(); await pending;
  assert.equal(h.get('policy-import-panel'), null);
  let finishImport;
  const second = harness({ waitImport: new Promise(resolve => { finishImport = resolve; }) }); await flush();
  await importPreview(second);
  const confirm = second.get('policy-import-confirm');
  const first = confirm.click();
  const repeated = confirm.click();
  await flush();
  assert.equal(second.calls.filter(call => call.url === '/local-api/policy/policies/import').length, 1);
  finishImport(); await Promise.all([first, repeated]);
});

test('navigation survives policy loading; switching tabs preserves drafts and does not reload either panel', async () => {
  const h = harness();
  await flush();
  const filter = h.get('policy-set-filter');
  filter.value = 'Supply';
  await filter.dispatch('change');
  await h.get('policy-container').find(node => node.tagName === 'button' && node.textContent === 'Add Policy').click();
  const editor = h.get('new-policy-editor');
  const title = editor.querySelector('input');
  title.value = 'Unsaved policy';
  await h.tab('models');
  await flush();
  h.get('ally-model-name').value = 'unsaved-model';
  const requests = h.calls.length;
  await h.tab('policies');
  assert.equal(h.get('policy-set-filter'), filter);
  assert.equal(filter.value, 'Supply');
  assert.equal(h.get('new-policy-editor'), editor);
  assert.equal(title.value, 'Unsaved policy');
  await h.tab('models');
  assert.equal(h.get('ally-model-name').value, 'unsaved-model');
  assert.equal(h.calls.length, requests);
  assertModelsSelected(h);
});

for (const failPolicies of [false, true]) {
  test(`late policy ${failPolicies ? 'failure' : 'success'} does not change the selected model panel`, async () => {
    let resolve;
    const waitPolicies = new Promise(done => { resolve = done; });
    const h = harness({ waitPolicies, failPolicies });
    await h.tab('models');
    resolve();
    await flush();
    assertModelsSelected(h);
    assert.ok(h.get('config-tab-policies'));
    if (failPolicies) {
      h.state.failPolicies = false;
      const retry = h.get('policy-container').querySelector('button');
      assert.equal(retry.textContent, 'Retry loading policies');
      await retry.click();
      assertModelsSelected(h);
    }
    assert.ok(h.get('policy-set-filter'));
  });
}

test('saving a policy reloads only its content and preserves model drafts and navigation', async () => {
  const h = harness();
  await flush();
  await h.tab('models');
  await flush();
  h.get('ally-model-name').value = 'unsaved-model';
  await h.tab('policies');
  const change = h.get('company-policy-list').find(node => node.tagName === 'button' && node.textContent === 'Change');
  await change.click();
  await h.get('company-policy-list').querySelector('form').dispatch('submit');
  assert.equal(h.calls.filter(call => call.options.method === 'POST').length, 1);
  await h.tab('models');
  assertModelsSelected(h);
  assert.equal(h.get('ally-model-name').value, 'unsaved-model');
  assert.equal(h.calls.filter(call => call.url.startsWith('/local-api/model/')).length, 2);
});

test('tabs support keyboard selection and focus', async () => {
  const h = harness();
  await h.get('config-tab-policies').dispatch('keydown', { key: 'ArrowRight' });
  assertModelsSelected(h);
  assert.equal(h.doc.activeElement, h.get('config-tab-models'));
  await h.get('config-tab-models').dispatch('keydown', { key: 'Home' });
  assert.equal(h.get('config-panel-policies').hidden, false);
  assert.equal(h.get('config-tab-policies').tabIndex, 0);
  assert.equal(h.get('config-tab-models').tabIndex, -1);
});

function buttonIn(element, text) {
  const button = element?.find(node => node.tagName === 'button' && node.textContent === text);
  assert.ok(button, `Expected ${text} button`);
  return button;
}

function setRow(h, name) {
  const row = h.get('policy-container').find(node => node.tagName === 'li'
    && node.children.some(child => child.tagName === 'span' && child.textContent === name));
  assert.ok(row, `Expected ${name} policy set`);
  return row;
}

function deleteCalls(h) { return h.calls.filter(call => call.url.endsWith('/delete')); }

function noticeIn(h, expectedMessage) {
  const notice = h.doc.querySelector('.config-notice');
  assert.ok(notice, 'errors must appear inside the Office add-in page');
  assert.equal(notice.getAttribute('role'), 'alert');
  assert.notEqual(notice.hidden, true, 'the error explanation must be visible');
  assert.match(notice.textContent, expectedMessage);
  buttonIn(notice, 'Dismiss');
  return notice;
}

async function dismissNotice(h, notice) {
  await buttonIn(notice, 'Dismiss').click();
  const remaining = h.doc.querySelector('.config-notice');
  assert.ok(!remaining || remaining.hidden === true, 'Dismiss must hide or remove the error explanation');
}

test('renaming a nonempty set registers the new name before moving policies and removing the old name', async () => {
  const original = { id: 1, title: 'Legacy cap', instruction: 'Keep the cap', severity: 1 };
  const untouched = { id: 2, title: 'Supply cap', instruction: 'Keep supply cap', policySet: 'Supply', severity: 2 };
  const h = harness({ policies: [original, untouched] }); await flush();
  await h.tab('models'); await flush();
  h.get('ally-model-name').value = 'unsaved-model';
  await h.tab('policies');
  const row = setRow(h, 'General Policies');
  const pending = buttonIn(row, 'Rename').click();
  await flush();
  const editor = row.querySelector('.policy-set-rename-editor');
  editor.querySelector('input').value = 'Renamed general';
  await buttonIn(editor, 'Save').click();
  await pending;
  const posts = h.calls.filter(call => call.options.method === 'POST');
  assert.deepEqual(posts.map(call => call.url), [
    '/local-api/policy/policy-sets', '/local-api/policy/policies', '/local-api/policy/policy-sets',
  ]);
  const registered = JSON.parse(posts[0].options.body).policySets;
  assert.ok(registered.includes('General Policies'));
  assert.ok(registered.includes('Renamed general'));
  assert.ok(registered.includes('Supply'));
  assert.deepEqual(JSON.parse(posts[1].options.body).policies,
    [{ ...original, policySet: 'Renamed general' }, untouched]);
  assert.deepEqual(JSON.parse(posts[2].options.body).policySets, ['Renamed general', 'Supply']);
  assert.deepEqual(h.state.policySets, ['Renamed general', 'Supply']);
  assert.deepEqual(h.state.policies, [{ ...original, policySet: 'Renamed general' }, untouched]);
  assert.ok(!h.doc.querySelector('.config-notice') || h.doc.querySelector('.config-notice').hidden === true);
  assert.equal(h.messages.length, 1);
  assert.equal(h.messages[0].data.type, 'policy-sets-updated');
  assert.equal(h.messages[0].data.action, 'rename');
  assert.equal(h.messages[0].data.oldName, 'General Policies');
  assert.equal(h.messages[0].data.newName, 'Renamed general');
  setRow(h, 'Renamed general');
  await h.tab('models');
  assert.equal(h.get('ally-model-name').value, 'unsaved-model');
});

test('failed policy transfer during rename preserves the original set and its policies', async () => {
  const original = { id: 1, title: 'Cap', instruction: 'Keep cap', policySet: 'General Policies', severity: 1 };
  const h = harness({ policies: [original], failSavePolicies: true }); await flush();
  const row = setRow(h, 'General Policies');
  const trigger = buttonIn(row, 'Rename');
  const pending = trigger.click();
  await flush();
  const editor = row.querySelector('.policy-set-rename-editor');
  editor.querySelector('input').value = 'Renamed general';
  await buttonIn(editor, 'Save').click();
  await pending;
  const posts = h.calls.filter(call => call.options.method === 'POST');
  assert.deepEqual(posts.map(call => call.url), ['/local-api/policy/policy-sets', '/local-api/policy/policies']);
  assert.ok(h.state.policySets.includes('General Policies'));
  assert.ok(h.state.policySets.includes('Supply'));
  assert.deepEqual(h.state.policies, [original]);
  assert.equal(h.messages.length, 0, 'failed transfer must not publish a completed rename');
  noticeIn(h, /rename|registered|check/i);
  assert.equal(Boolean(trigger.disabled), false);
  assert.equal(setRow(h, 'General Policies'), row);
});

async function openDelete(h, trigger) {
  const existingRequests = deleteCalls(h).length;
  trigger.focus();
  const pending = trigger.click();
  await flush();
  const overlay = h.doc.querySelector('.config-confirm-overlay');
  assert.ok(overlay, 'deleting must show a confirmation overlay');
  const dialog = overlay.querySelector('[role="alertdialog"]');
  assert.ok(dialog, 'confirmation must be an accessible alert dialog');
  assert.ok(dialog.querySelector('.config-confirm-title')?.textContent);
  assert.equal(deleteCalls(h).length, existingRequests, 'opening confirmation must not delete anything');
  return { pending, overlay, dialog, cancel: buttonIn(dialog, 'Cancel'), confirm: buttonIn(dialog, 'Delete') };
}

test('policy deletion requires confirmation; Cancel leaves the policy intact and restores focus', async () => {
  const h = harness(); await flush();
  const card = h.get('company-policy-list').querySelector('.output-item');
  buttonIn(card, 'Change');
  const trigger = buttonIn(card, 'Delete');
  const dialog = await openDelete(h, trigger);
  await dialog.cancel.click();
  await dialog.pending;
  assert.equal(deleteCalls(h).length, 0);
  assert.equal(h.get('company-policy-list').querySelector('.output-item'), card);
  assert.equal(h.doc.querySelector('.config-confirm-overlay'), null);
  assert.equal(h.doc.activeElement, trigger);
});

test('confirmation keeps keyboard focus inside and Escape cancels without deleting', async () => {
  const h = harness(); await flush();
  const trigger = buttonIn(h.get('company-policy-list'), 'Delete');
  const dialog = await openDelete(h, trigger);
  assert.equal(h.doc.activeElement, dialog.cancel, 'initial focus should be on the non-destructive action');
  await dialog.cancel.dispatch('keydown', { key: 'Tab', shiftKey: true });
  assert.equal(h.doc.activeElement, dialog.confirm);
  await dialog.confirm.dispatch('keydown', { key: 'Tab', shiftKey: false });
  assert.equal(h.doc.activeElement, dialog.cancel);
  await dialog.cancel.dispatch('keydown', { key: 'Escape' });
  await dialog.pending;
  assert.equal(deleteCalls(h).length, 0);
  assert.equal(h.doc.querySelector('.config-confirm-overlay'), null);
  assert.equal(h.doc.activeElement, trigger);
});

test('confirmed policy deletion sends its complete original snapshot and preserves filter and model draft', async () => {
  const original = { id: 8, title: 'Supply cap', instruction: 'Cap supply liability', policySet: 'Supply',
    severity: 2, tags: ['cap'], groups: ['Legal'], customField: { keep: true } };
  const h = harness({ policies: [original] }); await flush();
  await h.tab('models'); await flush();
  h.get('ally-model-name').value = 'unsaved-model';
  await h.tab('policies');
  h.get('policy-set-filter').value = 'Supply';
  await h.get('policy-set-filter').dispatch('change');
  const dialog = await openDelete(h, buttonIn(h.get('company-policy-list'), 'Delete'));
  await dialog.confirm.click(); await dialog.pending; await flush();
  assert.equal(deleteCalls(h).length, 1);
  assert.equal(deleteCalls(h)[0].url, '/local-api/policy/policies/delete');
  assert.deepEqual(JSON.parse(deleteCalls(h)[0].options.body), { policy: original });
  assert.equal(h.get('policy-set-filter').value, 'Supply');
  assert.match(h.get('company-policy-list').textContent, /No policies/i);
  assert.deepEqual(h.state.policySets, ['General Policies', 'Supply']);
  await h.tab('models');
  assert.equal(h.get('ally-model-name').value, 'unsaved-model');
});

test('a failed policy deletion keeps the current card and allows retry', async () => {
  const h = harness({ failDelete: true }); await flush();
  const card = h.get('company-policy-list').querySelector('.output-item');
  const trigger = buttonIn(card, 'Delete');
  const dialog = await openDelete(h, trigger);
  await dialog.confirm.click(); await dialog.pending; await flush();
  assert.equal(deleteCalls(h).length, 1);
  assert.equal(h.get('company-policy-list').querySelector('.output-item'), card);
  const notice = noticeIn(h, /changed|refresh|delete/i);
  assert.equal(Boolean(trigger.disabled), false);
  assert.equal(h.state.policies.length, 1);
  await dismissNotice(h, notice);
  assert.equal(deleteCalls(h).length, 1, 'dismissing an error must not retry the operation');
  h.state.failDelete = false;
  const retry = await openDelete(h, trigger);
  await retry.confirm.click(); await retry.pending; await flush();
  assert.equal(deleteCalls(h).length, 2);
  assert.equal(h.state.policies.length, 0);
  assert.match(h.get('company-policy-list').textContent, /No policies/i);
});

test('repeated confirmation cannot issue duplicate policy deletion requests', async () => {
  let finish;
  const waitDelete = new Promise(resolve => { finish = resolve; });
  const h = harness({ waitDelete }); await flush();
  const dialog = await openDelete(h, buttonIn(h.get('company-policy-list'), 'Delete'));
  const first = dialog.confirm.click();
  const second = dialog.confirm.click();
  await flush();
  assert.equal(deleteCalls(h).length, 1);
  finish();
  await Promise.all([first, second, dialog.pending]);
  assert.equal(h.state.policies.length, 0);
});

for (const policySet of ['General Policies', undefined]) {
  test(`nonempty set deletion is blocked before a request (${policySet ?? 'implicit General Policies'})`, async () => {
    const h = harness({ policies: [{ id: 4, title: 'Existing rule', instruction: 'Keep it', ...(policySet ? { policySet } : {}) }] });
    await flush();
    const row = setRow(h, 'General Policies');
    buttonIn(row, 'Rename');
    await buttonIn(row, 'Delete').click();
    assert.equal(deleteCalls(h).length, 0);
    assert.equal(h.doc.querySelector('.config-confirm-overlay'), null);
    const notice = noticeIn(h, /Move or delete.*General Policies.*before deleting/i);
    assert.equal(h.state.policySets.length, 2);
    assert.equal(h.state.policies.length, 1);
    await dismissNotice(h, notice);
    assert.equal(deleteCalls(h).length, 0);
    await buttonIn(row, 'Delete').click();
    noticeIn(h, /Move or delete.*General Policies.*before deleting/i);
    assert.equal(deleteCalls(h).length, 0, 'repeated attempts must continue to protect a nonempty set');
  });
}

for (const broadcast of [false, true]) {
  test(`empty set deletion confirms and publishes a removal via ${broadcast ? 'BroadcastChannel' : 'storage'}`, async () => {
    const h = harness({ broadcast }); await flush();
    const row = setRow(h, 'Supply');
    buttonIn(row, 'Rename');
    const dialog = await openDelete(h, buttonIn(row, 'Delete'));
    await dialog.confirm.click(); await dialog.pending; await flush();
    assert.equal(deleteCalls(h).length, 1);
    assert.equal(deleteCalls(h)[0].url, '/local-api/policy/policy-sets/delete');
    assert.deepEqual(JSON.parse(deleteCalls(h)[0].options.body), { name: 'Supply' });
    assert.deepEqual(h.state.policySets, ['General Policies']);
    assert.equal(h.get('policy-set-filter').value, 'General Policies');
    assert.equal(h.messages.length, 1);
    assert.equal(h.messages[0].data.type, 'policy-sets-updated');
    assert.equal(h.messages[0].data.action, 'remove');
    assert.equal(h.messages[0].data.oldName, 'Supply');
    assert.equal(broadcast ? h.messages[0].channel : h.messages[0].key,
      broadcast ? 'ally-policy-sets' : 'ally-policy-sets-updated');
  });
}

test('set deletion conflict shows an in-page explanation, preserves the set, and allows a confirmed retry', async () => {
  const h = harness({ failDelete: true }); await flush();
  const row = setRow(h, 'Supply');
  const trigger = buttonIn(row, 'Delete');
  const dialog = await openDelete(h, trigger);
  await dialog.confirm.click(); await dialog.pending; await flush();
  assert.equal(deleteCalls(h).length, 1);
  assert.equal(setRow(h, 'Supply'), row);
  assert.equal(Boolean(trigger.disabled), false);
  assert.equal(h.messages.length, 0);
  const notice = noticeIn(h, /changed|refresh|delete/i);
  await dismissNotice(h, notice);
  assert.equal(deleteCalls(h).length, 1, 'dismissing an error must not retry the operation');
  h.state.failDelete = false;
  const retry = await openDelete(h, trigger);
  await retry.confirm.click(); await retry.pending; await flush();
  assert.equal(deleteCalls(h).length, 2);
  assert.deepEqual(h.state.policySets, ['General Policies']);
  assert.equal(h.messages.length, 1);
  assert.equal(h.messages[0].data.action, 'remove');
});

test('deleting a different empty set preserves the currently displayed policy set', async () => {
  const h = harness({ policies: [{ id: 1, title: 'Supply rule', instruction: 'Keep this rule', policySet: 'Supply' }],
    policySets: ['General Policies', 'Supply', 'Empty'] });
  await flush();
  h.get('policy-set-filter').value = 'Supply';
  await h.get('policy-set-filter').dispatch('change');
  const dialog = await openDelete(h, buttonIn(setRow(h, 'Empty'), 'Delete'));
  await dialog.confirm.click(); await dialog.pending; await flush();
  assert.equal(h.get('policy-set-filter').value, 'Supply');
  assert.match(h.get('company-policy-list').textContent, /Supply rule/);
  assert.equal(h.state.policies.length, 1);
});

test('deleting the last empty set leaves no invented General Policies option and disables adding policies', async () => {
  const h = harness({ policies: [], policySets: ['Only set'] }); await flush();
  const dialog = await openDelete(h, buttonIn(setRow(h, 'Only set'), 'Delete'));
  await dialog.confirm.click(); await dialog.pending; await flush();
  assert.deepEqual(h.state.policySets, []);
  assert.equal(h.get('policy-set-filter').children.some(option => option.value === 'General Policies'), false);
  assert.equal(h.get('policy-set-filter').value, '');
  assert.equal(h.get('policy-set-filter').disabled, true);
  const add = buttonIn(h.get('policy-container'), 'Add Policy');
  assert.equal(add.disabled, true);
  await add.click();
  assert.equal(h.get('new-policy-editor'), null);
  assert.match(h.get('company-policy-list').textContent, /create|add.*policy set/i);
  buttonIn(h.get('policy-container'), 'Add Policy Set');
});
