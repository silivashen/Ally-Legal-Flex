const API = "/local-api/model";
const mountedContainers = new WeakMap();

async function request(path, method = "GET", payload) {
  const options = { method, headers: {} };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(API + path, options);
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.message || "HTTP " + response.status);
  }
  return data;
}

function createModelPanel(container, options) {
  const doc = container.ownerDocument;
  const section = doc.createElement("section");
  section.id = options.id;
  section.className = "ally-model-settings";

  function element(tag, text, parent = section) {
    const node = doc.createElement(tag);
    if (text) node.textContent = text;
    parent.appendChild(node);
    return node;
  }

  const heading = element("h3", options.title);
  heading.id = options.id + "-title";
  section.setAttribute("aria-labelledby", heading.id);
  element("p", options.description).className = "ally-model-description";

  function input(id, label, type, placeholder) {
    const labelNode = element("label", label);
    labelNode.htmlFor = id;
    const field = element("input");
    field.id = id;
    field.type = type;
    field.placeholder = placeholder;
    field.className = "ally-model-input";
    if (type === "password") field.autocomplete = "new-password";
    return field;
  }

  const url = input(options.prefix + "-url", "API Base URL", "url", options.urlPlaceholder);
  const model = input(options.modelId, options.modelLabel, "text", "Enter the model ID required by your provider");
  const key = input(options.prefix + "-key", "API Key", "password", "Leave blank to keep the saved key for the same API URL");
  const keyStatus = element("p", "Loading local configuration...");
  keyStatus.id = options.prefix + "-key-status";
  keyStatus.className = "ally-model-key-status";

  const actions = element("div");
  actions.className = "ally-model-actions";
  const testButton = element("button", "Test Connection", actions);
  testButton.id = options.prefix + "-test";
  testButton.type = "button";
  const saveButton = element("button", options.saveLabel, actions);
  saveButton.id = options.saveId;
  saveButton.type = "button";
  const status = element("p");
  status.id = options.prefix + "-status";
  status.className = "ally-model-status";
  status.setAttribute("role", "status");
  const controls = [url, model, key, testButton, saveButton];

  function setBusy(busy) {
    controls.forEach((control) => { control.disabled = busy; });
    section.setAttribute("aria-busy", String(busy));
  }

  function formData() {
    return { base_url: url.value.trim(), model: model.value.trim(), api_key: key.value.trim() };
  }

  async function loadConfig() {
    try {
      const cfg = await request(options.configPath);
      url.value = cfg.base_url || "";
      model.value = cfg.model || "";
      keyStatus.textContent = cfg.has_api_key
        ? "API key saved locally. Leave blank to keep it for the same API URL. Re-enter a key when changing the URL."
        : "No API key saved locally.";
      status.textContent = "Connected to the local configuration service.";
      return true;
    } catch (err) {
      status.textContent = "Unable to load configuration: " + (err.message || err);
      keyStatus.textContent = "Check that the local configuration service is running.";
      return false;
    }
  }

  testButton.addEventListener("click", async () => {
    setBusy(true);
    status.textContent = "Testing connection...";
    try {
      const result = await request(options.testPath, "POST", formData());
      status.textContent = result.message || "Connection successful.";
    } catch (err) {
      status.textContent = "Connection test failed: " + (err.message || err);
    } finally {
      setBusy(false);
    }
  });

  saveButton.addEventListener("click", async () => {
    setBusy(true);
    status.textContent = "Saving local configuration...";
    try {
      const result = await request(options.savePath, "POST", formData());
      key.value = "";
      const loaded = await loadConfig();
      if (loaded) status.textContent = result.message || "Configuration saved locally.";
      else status.textContent = "Configuration saved. " + status.textContent;
    } catch (err) {
      status.textContent = "Save failed: " + (err.message || err);
    } finally {
      setBusy(false);
    }
  });

  container.appendChild(section);
  setBusy(true);
  return loadConfig().finally(() => setBusy(false));
}

// Mount once: changing Config tabs only hides the panel, preserving unsaved input.
export function mountModelSettings(container) {
  if (mountedContainers.has(container)) return mountedContainers.get(container);
  const ready = Promise.all([
    createModelPanel(container, {
      id: "ally-model-settings",
      prefix: "ally-model",
      title: "Chat Model",
      urlPlaceholder: "e.g. https://api.deepseek.com",
      description: "Configure an OpenAI-compatible model for Summary, Ask, and Review. API keys are saved on this machine and are not stored in browser local storage.",
      modelId: "ally-model-name",
      modelLabel: "Model Name",
      configPath: "/api/config",
      testPath: "/api/test",
      savePath: "/api/apply",
      saveId: "ally-model-apply",
      saveLabel: "Apply Model",
    }),
    createModelPanel(container, {
      id: "ally-embedding-settings",
      prefix: "ally-embedding",
      title: "Embedding Model",
      urlPlaceholder: "Enter your embedding provider's API base URL",
      description: "Used for document and policy retrieval. Configure this separately from the chat model.",
      modelId: "ally-embedding-model",
      modelLabel: "Embedding Model",
      configPath: "/api/embedding-config",
      testPath: "/api/embedding-test",
      savePath: "/api/embedding-config",
      saveId: "ally-embedding-save",
      saveLabel: "Save Configuration",
    }),
  ]);
  mountedContainers.set(container, ready);
  return ready;
}
