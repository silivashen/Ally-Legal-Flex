export function mountPromptSettings(container) {
    if (container.dataset.mounted) return;
    container.dataset.mounted = "true";
    container.innerHTML = `
        <section class="prompt-settings" aria-label="Prompt settings">
            <p>Customize how each function analyzes and explains the contract.</p>
            <div class="prompt-feature-tabs" role="tablist" aria-label="Choose a function">
                <button type="button" id="prompt-feature-ask" role="tab" aria-selected="true" aria-controls="prompt-editor-panel">Ask</button>
                <button type="button" id="prompt-feature-summary" role="tab" aria-selected="false" aria-controls="prompt-editor-panel" tabindex="-1">Summary</button>
                <button type="button" id="prompt-feature-review" role="tab" aria-selected="false" aria-controls="prompt-editor-panel" tabindex="-1">Review</button>
            </div>
            <div id="prompt-editor-panel" class="prompt-editor-panel" role="tabpanel" aria-labelledby="prompt-feature-ask">
            <p id="prompt-purpose" class="prompt-hint"></p>
            <div class="prompt-editor-label">
                <label for="prompt-text">Core prompt</label>
                <span id="prompt-state" class="prompt-state"></span>
            </div>
            <textarea id="prompt-text" rows="18" maxlength="20000" spellcheck="false" disabled></textarea>
            <p id="prompt-length" class="prompt-hint"></p>
            <div class="policy-editor-actions">
                <button type="button" id="prompt-save" class="save-button" disabled>Save Prompt</button>
                <button type="button" id="prompt-reset" class="change-button" disabled>Restore Default</button>
            </div>
            <p id="prompt-status" role="status" aria-live="polite">Loading prompts...</p>
            <button type="button" id="prompt-reload" class="change-button" hidden>Reload saved prompts</button>
            </div>
            <aside class="prompt-common-help">
                <p>The add-in automatically includes the current contract, answer language, review perspective, and required output and citation rules. Selected policies are included for Summary and Review only. Keep the default JSON field names unchanged.</p>
            </aside>
        </section>`;

    const get = id => container.querySelector("#" + id);
    const features = ["ask", "summary", "review"];
    let selectedFeature = "ask";
    const editor = get("prompt-text");
    const save = get("prompt-save");
    const reset = get("prompt-reset");
    const status = get("prompt-status");
    const reload = get("prompt-reload");
    const purposes = {
        ask: "Answer questions using the current contract and relevant passages.",
        summary: "Summarize important clauses, general risks and compliance with the selected Policy Sets.",
        review: "Review the selected clause and propose replacement wording when needed."
    };
    let settings = null;
    let busy = false;
    const drafts = {};

    function render() {
        const item = settings && settings[selectedFeature];
        get("prompt-purpose").textContent = purposes[selectedFeature];
        if (editor.value !== drafts[selectedFeature]) editor.value = drafts[selectedFeature] ?? (item ? item.text : "");
        const changed = Boolean(item && editor.value !== item.text);
        get("prompt-state").textContent = changed ? "Unsaved changes" : item && item.customized ? "Customized" : "Built-in";
        get("prompt-length").textContent = `${Array.from(editor.value).length.toLocaleString()} characters · core prompt only`;
        features.forEach(key => {
            const tab = get("prompt-feature-" + key);
            tab.disabled = busy || !settings;
            tab.setAttribute("aria-selected", String(key === selectedFeature));
            tab.tabIndex = key === selectedFeature ? 0 : -1;
        });
        get("prompt-editor-panel").setAttribute("aria-labelledby", "prompt-feature-" + selectedFeature);
        editor.disabled = busy || !item;
        save.disabled = busy || !changed || !editor.value.trim();
        reset.disabled = busy || !item || (!item.customized && editor.value === item.default);
    }

    async function load() {
        if (busy) return;
        busy = true;
        reload.hidden = true;
        status.textContent = "Loading prompts...";
        render();
        try {
            const response = await fetch("/local-api/policy/prompt-settings");
            const result = await response.json();
            if (!response.ok || result.success !== true) throw new Error(result.error || "Could not load prompts.");
            settings = result.prompts;
            Object.keys(settings).forEach(key => {
                if (!(key in drafts)) drafts[key] = settings[key].text;
            });
            status.textContent = "Saved on this computer. Your model connections and policies are managed separately.";
        } catch (error) {
            status.textContent = error.message;
            reload.hidden = false;
        } finally {
            busy = false;
            render();
        }
    }

    async function persist(restore) {
        if (busy || !settings) return;
        const key = selectedFeature;
        busy = true;
        status.textContent = restore ? "Restoring default..." : "Saving prompt...";
        reload.hidden = true;
        render();
        try {
            const response = await fetch("/local-api/policy/prompt-settings", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ feature: key, text: drafts[key], reset: restore, expectedVersion: settings[key].version })
            });
            const result = await response.json();
            if (!response.ok || result.success !== true) throw new Error(result.error || "Could not save this prompt.");
            settings[key] = result.prompt;
            drafts[key] = result.prompt.text;
            status.textContent = restore ? "Default restored. Run the feature again to use it." : "Prompt saved. Run the feature again to use it.";
        } catch (error) {
            status.textContent = error.message + " Your edits are still here.";
            reload.hidden = false;
        } finally {
            busy = false;
            render();
        }
    }

    features.forEach((key, index) => {
        const tab = get("prompt-feature-" + key);
        tab.addEventListener("click", () => { selectedFeature = key; render(); });
        tab.addEventListener("keydown", event => {
            if (busy || !settings) return;
            let next;
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                const step = event.key === "ArrowRight" ? 1 : -1;
                next = features[(index + step + features.length) % features.length];
            } else if (event.key === "Home") next = features[0];
            else if (event.key === "End") next = features[features.length - 1];
            else return;
            event.preventDefault();
            selectedFeature = next;
            render();
            get("prompt-feature-" + next).focus();
        });
    });
    editor.addEventListener("input", () => {
        drafts[selectedFeature] = editor.value;
        status.textContent = "Unsaved changes. Save to apply them to the next request.";
        render();
    });
    save.addEventListener("click", () => persist(false));
    reset.addEventListener("click", () => persist(true));
    reload.addEventListener("click", load);
    load();
}
