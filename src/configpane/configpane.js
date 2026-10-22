import { mountModelSettings } from "../shared/model-settings";
import { mountPromptSettings } from "../shared/prompt-settings";

let deleteConfirmationOpen = false;

function clearConfigNotice() {
    const notice = document.querySelector(".config-notice");
    if (notice) notice.remove();
}

function showConfigNotice(message) {
    const previousFocus = document.activeElement;
    const panel = document.getElementById("config-panel-policies");
    clearConfigNotice();

    // Office hosts do not support the browser's native alert dialog.
    const notice = document.createElement("div");
    notice.className = "config-notice";
    notice.setAttribute("role", "alert");
    notice.tabIndex = -1;
    notice.hidden = false;

    const text = document.createElement("p");
    text.textContent = message;
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "change-button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => {
        notice.remove();
        if (previousFocus && document.body.contains(previousFocus) && !previousFocus.disabled) {
            previousFocus.focus();
        } else {
            panel.focus();
        }
    });

    notice.append(text, dismiss);
    panel.insertBefore(notice, document.getElementById("policy-container"));
    notice.focus();
}

function confirmDeletion(title, message) {
    if (deleteConfirmationOpen) return Promise.resolve(false);
    deleteConfirmationOpen = true;

    return new Promise(resolve => {
        const previousFocus = document.activeElement;
        const appBody = document.getElementById("app-body");
        const wasInert = Boolean(appBody.inert);
        const overlay = document.createElement("div");
        overlay.className = "config-confirm-overlay";

        const dialog = document.createElement("div");
        dialog.className = "config-confirm-dialog";
        dialog.setAttribute("role", "alertdialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "config-delete-title");
        dialog.setAttribute("aria-describedby", "config-delete-message");

        const heading = document.createElement("h3");
        heading.id = "config-delete-title";
        heading.className = "config-confirm-title";
        heading.textContent = title;
        const description = document.createElement("p");
        description.id = "config-delete-message";
        description.textContent = message;

        const actions = document.createElement("div");
        actions.className = "policy-editor-actions config-confirm-actions";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "change-button";
        cancel.textContent = "Cancel";
        const confirm = document.createElement("button");
        confirm.type = "button";
        confirm.className = "delete-button";
        confirm.textContent = "Delete";

        let closed = false;
        const close = accepted => {
            if (closed) return;
            closed = true;
            overlay.remove();
            appBody.inert = wasInert;
            deleteConfirmationOpen = false;
            if (previousFocus && document.body.contains(previousFocus)) previousFocus.focus();
            resolve(accepted);
        };
        cancel.addEventListener("click", () => close(false));
        confirm.addEventListener("click", () => close(true));
        overlay.addEventListener("keydown", event => {
            if (event.key === "Escape") {
                event.preventDefault();
                close(false);
            } else if (event.key === "Tab") {
                event.preventDefault();
                (document.activeElement === cancel ? confirm : cancel).focus();
            }
        });

        actions.append(cancel, confirm);
        dialog.append(heading, description, actions);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        appBody.inert = true;
        cancel.focus();
    });
}

Office.onReady((info) => {
  if (info.host === Office.HostType.Word) {
    document.getElementById("sideload-msg").style.display = "none";
    document.getElementById("app-body").style.display = "flex";
    const sections = ["policies", "models", "prompts"];
    let policiesStarted = false;
    const selectSection = (selected) => {
      sections.forEach((section) => {
        const active = section === selected;
        const tab = document.getElementById(`config-tab-${section}`);
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        document.getElementById(`config-panel-${section}`).hidden = !active;
      });
      if (selected === "models") {
        mountModelSettings(document.getElementById("model-settings-container"));
      } else if (selected === "prompts") {
        mountPromptSettings(document.getElementById("prompt-settings-container"));
      } else if (!policiesStarted) {
        policiesStarted = true;
        displayJSONOutputWithTags();
      }
    };
    sections.forEach((section, index) => {
      const tab = document.getElementById(`config-tab-${section}`);
      tab.addEventListener("click", () => selectSection(section));
      tab.addEventListener("keydown", (event) => {
        let next;
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          const step = event.key === "ArrowRight" ? 1 : -1;
          next = sections[(index + step + sections.length) % sections.length];
        } else if (event.key === "Home") {
          next = sections[0];
        } else if (event.key === "End") {
          next = sections[sections.length - 1];
        } else {
          return;
        }
        event.preventDefault();
        selectSection(next);
        document.getElementById(`config-tab-${next}`).focus();
      });
    });
    selectSection("policies");
  }
});

async function displayJSONOutputWithTags() {
    const container = document.getElementById("policy-container");
    if (!container) {
        console.error("Result container not found");
        return;
    }

    const previousFilter = container.querySelector("#policy-set-filter");
    const previouslySelectedSet = previousFilter ? previousFilter.value : "";
    let deletionPending = false;
    clearConfigNotice();
    container.innerHTML = "Loading company policies...";

    async function loadPolicies() {
        const response = await fetch("/local-api/policy/policies");
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "Failed to load policies");
        }
        return result.policies || [];
    }

    async function savePolicies(policies) {
        const response = await fetch("/local-api/policy/policies", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ policies: policies })
        });
        const result = await response.json();

        if (!response.ok || result.success !== true) {
            throw new Error(result.error || "Failed to save policies");
        }
        return result;
    }

    async function loadPolicySets() {
        const response = await fetch("/local-api/policy/policy-sets");
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "Failed to load policy sets");
        }
        return result.policySets || [];
    }

    async function savePolicySets(policySets) {
        const response = await fetch("/local-api/policy/policy-sets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ policySets: policySets })
        });
        const result = await response.json();
        if (!response.ok || result.success !== true) {
            throw new Error(result.error || "Failed to save policy sets");
        }
        return result;
    }
    function notifyPolicySetsChanged(change) {
        const message = {
            type: "policy-sets-updated",
            ...change,
            timestamp: Date.now()
        };

        if (typeof BroadcastChannel !== "undefined") {
            const channel = new BroadcastChannel("ally-policy-sets");
            channel.postMessage(message);
            channel.close();
        } else {
            localStorage.setItem(
                "ally-policy-sets-updated",
                JSON.stringify(message)
            );
        }
    }

    async function deleteWithConfirmation(button, endpoint, payload, title, message, change) {
        if (deletionPending) return;
        clearConfigNotice();
        deletionPending = true;
        const wasInert = Boolean(container.inert);
        try {
            button.focus();
            if (!await confirmDeletion(title, message)) return;

            button.disabled = true;
            button.textContent = "Deleting...";
            container.inert = true;
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok || result.success !== true) {
                throw new Error(result.error || "Deletion failed");
            }

            if (change) {
                try {
                    notifyPolicySetsChanged(change);
                } catch (error) {
                    console.error("[Policy Sets] Could not notify the review pane:", error);
                }
            }
            await displayJSONOutputWithTags();
        } catch (error) {
            console.error("[Company Policy] Delete failed:", error);
            showConfigNotice("Could not delete: " + error.message);
        } finally {
            container.inert = wasInert;
            button.disabled = false;
            button.textContent = "Delete";
            deletionPending = false;
        }
    }

    function makeField(form, labelText, value, multiline, required) {
        const wrapper = document.createElement("div");
        wrapper.style.margin = "8px 0";

        const label = document.createElement("label");
        label.textContent = labelText;
        label.style.display = "block";
        label.style.fontWeight = "600";
        label.style.marginBottom = "4px";

        const input = multiline
            ? document.createElement("textarea")
            : document.createElement("input");

        if (!multiline) input.type = "text";
        input.value = value || "";
        input.required = Boolean(required);
        input.style.boxSizing = "border-box";
        input.style.width = "100%";
        input.style.padding = "8px";

        if (multiline) {
            input.rows = 4;
            input.style.resize = "vertical";
        }

        wrapper.appendChild(label);
        wrapper.appendChild(input);
        form.appendChild(wrapper);

        return input;
    }

    function makeSeverityField(form, value) {
        const wrapper = document.createElement("div");
        wrapper.style.margin = "8px 0";

        const label = document.createElement("label");
        label.textContent = "Severity";
        label.style.display = "block";
        label.style.fontWeight = "600";

        const select = document.createElement("select");
        select.style.padding = "8px";

        [
            { value: "1", label: "1 - Critical" },
            { value: "2", label: "2 - Warning" },
            { value: "3", label: "3 - Informational" }
        ].forEach(optionData => {
            const option = document.createElement("option");
            option.value = optionData.value;
            option.textContent = optionData.label;
            select.appendChild(option);
        });

        select.value = String(value || 2);
        wrapper.appendChild(label);
        wrapper.appendChild(select);
        form.appendChild(wrapper);

        return select;
    }

    function buildEditor(target, policies, policySets, currentPolicy, currentIndex, isNew) {
        if (target.querySelector(".policy-editor")) return;

        const form = document.createElement("form");
        form.className = "policy-editor";
        form.style.border = "1px solid #d0d0d0";
        form.style.padding = "12px";
        form.style.marginTop = "12px";
        form.style.background = "#fff";

        const titleInput = makeField(
            form, "Policy title", currentPolicy.title, false, true
        );
        const instructionInput = makeField(
            form, "Policy instruction", currentPolicy.instruction, true, true
        );
        const tagsInput = makeField(
            form, "Tags (comma-separated)",
            Array.isArray(currentPolicy.tags) ? currentPolicy.tags.join(", ") : "",
            false, false
        );
        const groupsInput = makeField(
            form, "Permission groups (comma-separated; blank means all)",
            Array.isArray(currentPolicy.groups) ? currentPolicy.groups.join(", ") : "",
            false, false
        );
        const policySetWrapper = document.createElement("div");
        policySetWrapper.style.margin = "8px 0";

        const policySetLabel = document.createElement("label");
        policySetLabel.textContent = "Policy Set";
        policySetLabel.style.display = "block";
        policySetLabel.style.fontWeight = "600";

        const policySetInput = document.createElement("select");
        policySetInput.style.boxSizing = "border-box";
        policySetInput.style.width = "100%";
        policySetInput.style.padding = "8px";

        const availableSets = policySets;

        availableSets.forEach(name => {
            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            policySetInput.appendChild(option);
        });

        policySetInput.value = currentPolicy.policySet || "General Policies";

        if (!availableSets.includes(policySetInput.value)) {
            policySetInput.value = availableSets[0] || "";
        }

        policySetWrapper.appendChild(policySetLabel);
        policySetWrapper.appendChild(policySetInput);
        form.appendChild(policySetWrapper);

        const severityInput = makeSeverityField(form, currentPolicy.severity);

        const buttons = document.createElement("div");
        buttons.className = "policy-editor-actions";

        const saveButton = document.createElement("button");
        saveButton.type = "submit";
        saveButton.textContent = "Save policy";
        saveButton.className = "save-button";

        const cancelButton = document.createElement("button");
        cancelButton.type = "button";
        cancelButton.textContent = "Cancel";
        cancelButton.className = "change-button";
        cancelButton.addEventListener("click", () => form.remove());

        buttons.appendChild(saveButton);
        buttons.appendChild(cancelButton);
        form.appendChild(buttons);

        form.addEventListener("submit", async event => {
            event.preventDefault();
            clearConfigNotice();
            saveButton.disabled = true;
            saveButton.textContent = "Saving...";

            const updatedPolicy = {
                ...currentPolicy,
                id: currentPolicy.id || 0,
                title: titleInput.value.trim(),
                instruction: instructionInput.value.trim(),
                tags: tagsInput.value.split(",").map(x => x.trim()).filter(Boolean),
                groups: groupsInput.value.split(",").map(x => x.trim()).filter(Boolean),
                severity: Number(severityInput.value),
                policySet: policySetInput.value
            };

            const updatedPolicies = policies.slice();
            if (isNew) {
                updatedPolicies.push(updatedPolicy);
            } else {
                updatedPolicies[currentIndex] = updatedPolicy;
            }

            try {
                await savePolicies(updatedPolicies);
                await displayJSONOutputWithTags();
            } catch (error) {
                console.error("[Company Policy] Save failed:", error);
                showConfigNotice("Could not save policy: " + error.message);
                saveButton.disabled = false;
                saveButton.textContent = "Save policy";
            }
        });

        target.appendChild(form);
        titleInput.focus();
    }

    try {
        const policies = await loadPolicies();
        const policySets = await loadPolicySets();
        container.innerHTML = "";

        const setManager = document.createElement("section");
        setManager.className = "policy-set-manager";
        setManager.setAttribute("aria-labelledby", "policy-sets-heading");
        container.appendChild(setManager);

        const setHeading = document.createElement("h3");
        setHeading.id = "policy-sets-heading";
        setHeading.className = "policy-set-heading";
        setHeading.textContent = "Policy Sets";
        setManager.appendChild(setHeading);

        const setList = document.createElement("ul");
        setList.className = "policy-set-list";

        policySets.forEach(name => {
            const item = document.createElement("li");
            item.className = "policy-set-row";

            const nameLabel = document.createElement("span");
            nameLabel.textContent = name;
            item.appendChild(nameLabel);

            const renameButton = document.createElement("button");
            renameButton.type = "button";
            renameButton.textContent = "Rename";
            renameButton.className = "change-button";

            renameButton.addEventListener("click", async () => {
                clearConfigNotice();
                const newName = await new Promise(resolve => {
                    const editor = document.createElement("div");
                    editor.className = "policy-set-rename-editor";

                    const input = document.createElement("input");
                    input.type = "text";
                    input.value = name;
                    input.className = "policy-set-rename-input";
                    input.setAttribute("aria-label", "Policy set name");

                    const buttons = document.createElement("div");
                    buttons.className = "policy-editor-actions";

                    const confirmButton = document.createElement("button");
                    confirmButton.type = "button";
                    confirmButton.textContent = "Save";
                    confirmButton.className = "save-button";

                    const cancelButton = document.createElement("button");
                    cancelButton.type = "button";
                    cancelButton.textContent = "Cancel";
                    cancelButton.className = "change-button";

                    const cleanup = value => {
                        editor.remove();
                        resolve(value);
                    };

                    confirmButton.addEventListener("click", () => {
                        cleanup(input.value);
                    });

                    cancelButton.addEventListener("click", () => {
                        cleanup(null);
                    });

                    input.addEventListener("keydown", event => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            cleanup(input.value);
                        }
                        if (event.key === "Escape") {
                            cleanup(null);
                        }
                    });

                    buttons.append(confirmButton, cancelButton);
                    editor.append(input, buttons);
                    item.appendChild(editor);
                    input.focus();
                    input.select();
                });

                if (newName === null) return;

                const trimmedName = newName.trim();

                if (!trimmedName) {
                    showConfigNotice("Policy set name cannot be empty.");
                    return;
                }

                if (trimmedName === name) return;

                if (policySets.some(
                    existing => existing.toLowerCase() === trimmedName.toLowerCase()
                )) {
                    showConfigNotice("A policy set with this name already exists.");
                    return;
                }

                renameButton.disabled = true;
                renameButton.textContent = "Renaming...";

                try {
                    // Register the destination before moving rules into it.
                    await savePolicySets([...policySets, trimmedName]);

                    const policiesToSave = policies.map(policy => {
                        const currentSet = policy.policySet || "General Policies";

                        return currentSet === name
                            ? { ...policy, policySet: trimmedName }
                            : policy;
                    });

                    await savePolicies(policiesToSave);

                    // 再更新政策集名称列表
                    const renamedSets = policySets.map(existing =>
                        existing === name ? trimmedName : existing
                    );

                    await savePolicySets(renamedSets);

                    notifyPolicySetsChanged({
                        action: "rename",
                        oldName: name,
                        newName: trimmedName
                    });

                    await displayJSONOutputWithTags();
                } catch (error) {
                    console.error("[Policy Sets] Rename failed:", error);
                    showConfigNotice(
                        "Could not rename policy set: " + error.message +
                        "\nPlease check the policy configuration before retrying."
                    );
                    renameButton.disabled = false;
                    renameButton.textContent = "Rename";
                }
            });

            const deleteSetButton = document.createElement("button");
            deleteSetButton.type = "button";
            deleteSetButton.textContent = "Delete";
            deleteSetButton.className = "delete-button";
            deleteSetButton.addEventListener("click", async () => {
                if (deletionPending) return;
                const hasPolicies = policies.some(policy =>
                    (String(policy.policySet || "").trim() || "General Policies") === name
                );
                if (hasPolicies) {
                    showConfigNotice(`Move or delete the policies in "${name}" before deleting this policy set.`);
                    return;
                }
                await deleteWithConfirmation(
                    deleteSetButton, "/local-api/policy/policy-sets/delete", { name },
                    "Delete policy set?", `Delete the empty policy set "${name}"? This cannot be undone.`,
                    { action: "remove", oldName: name }
                );
            });

            const setActions = document.createElement("span");
            setActions.className = "policy-set-actions";
            setActions.append(renameButton, deleteSetButton);
            item.appendChild(setActions);
            setList.appendChild(item);
        });

        setManager.appendChild(setList);

        const addSetForm = document.createElement("form");
        addSetForm.style.display = "flex";
        addSetForm.style.gap = "8px";
        addSetForm.style.margin = "12px 0 0";

        const setNameInput = document.createElement("input");
        setNameInput.type = "text";
        setNameInput.placeholder = "New policy set name";
        setNameInput.setAttribute("aria-label", "New policy set name");
        setNameInput.required = true;
        setNameInput.style.flex = "1";
        setNameInput.style.minWidth = "0";
        setNameInput.style.padding = "8px";

        const addSetButton = document.createElement("button");
        addSetButton.type = "submit";
        addSetButton.textContent = "Add Policy Set";
        addSetButton.className = "change-button policy-add-button";

        addSetForm.appendChild(setNameInput);
        addSetForm.appendChild(addSetButton);
        setManager.appendChild(addSetForm);

        addSetForm.addEventListener("submit", async event => {
            event.preventDefault();
            clearConfigNotice();

            const name = setNameInput.value.trim();
            if (!name) return;

            if (policySets.some(
                item => item.toLowerCase() === name.toLowerCase()
            )) {
                showConfigNotice("A policy set with this name already exists.");
                return;
            }

            addSetButton.disabled = true;
            addSetButton.textContent = "Adding...";

            try {
                await savePolicySets([...policySets, name]);
                notifyPolicySetsChanged({
                    action: "add",
                    newName: name
                });
                await displayJSONOutputWithTags();
            } catch (error) {
                console.error("[Policy Sets] Save failed:", error);
                showConfigNotice("Could not add policy set: " + error.message);
                addSetButton.disabled = false;
                addSetButton.textContent = "Add Policy Set";
            }
        });

        const policyBrowser = document.createElement("section");
        policyBrowser.className = "policy-browser";
        policyBrowser.setAttribute("aria-label", "Browse and manage policies");
        container.appendChild(policyBrowser);

        const filterControls = document.createElement("div");
        filterControls.className = "policy-browser-controls";
        policyBrowser.appendChild(filterControls);

        const filterLabel = document.createElement("label");
        filterLabel.textContent = "Show policies in:";
        filterLabel.htmlFor = "policy-set-filter";
        filterLabel.className = "policy-browser-label";
        filterControls.appendChild(filterLabel);

        const policySetFilter = document.createElement("select");
        policySetFilter.id = "policy-set-filter";
        policySetFilter.className = "policy-browser-select";

        const filterSets = policySets;

        filterSets.forEach(name => {
            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            policySetFilter.appendChild(option);
        });

        policySetFilter.value = filterSets.includes(previouslySelectedSet)
            ? previouslySelectedSet
            : (filterSets.includes("General Policies") ? "General Policies" : filterSets[0] || "");
        policySetFilter.disabled = filterSets.length === 0;
        if (filterSets.length === 0) {
            const emptyOption = document.createElement("option");
            emptyOption.value = "";
            emptyOption.textContent = "No policy sets";
            policySetFilter.appendChild(emptyOption);
        }

        const addButton = document.createElement("button");
        addButton.type = "button";
        addButton.textContent = "Add Policy";
        addButton.className = "change-button policy-add-button";
        addButton.disabled = filterSets.length === 0;
        filterControls.appendChild(policySetFilter);
        filterControls.appendChild(addButton);

        const importButton = document.createElement("button");
        importButton.id = "policy-import-open";
        importButton.type = "button";
        importButton.className = "change-button policy-add-button";
        importButton.textContent = "Import Excel";
        importButton.disabled = filterSets.length === 0;
        const exportButton = document.createElement("button");
        exportButton.id = "policy-export";
        exportButton.type = "button";
        exportButton.className = "change-button policy-add-button";
        exportButton.textContent = "Download Excel";
        exportButton.disabled = filterSets.length === 0;
        const exchangeTools = document.createElement("section");
        exchangeTools.className = "policy-exchange-tools";
        exchangeTools.setAttribute("aria-label", "Excel import and migration for the selected Policy Set");
        const exchangeHeading = document.createElement("h3");
        exchangeHeading.textContent = "Excel import & migration";
        exchangeTools.appendChild(exchangeHeading);
        [[importButton, "Add multiple policies to the set selected above."],
         [exportButton, "Save this set as Excel to share or move it."]].forEach(([button, description]) => {
            const item = document.createElement("div");
            item.className = "policy-exchange-item";
            const caption = document.createElement("p");
            caption.textContent = description;
            item.append(button, caption);
            if (button === importButton) {
                const templateLink = document.createElement("a");
                templateLink.id = "policy-template-download";
                templateLink.href = "/local-api/policy/policies/import-template";
                templateLink.download = "Ally-Legal-Policy-Template.xlsx";
                templateLink.textContent = "Download Template";
                item.appendChild(templateLink);
            }
            exchangeTools.appendChild(item);
        });
        policyBrowser.appendChild(exchangeTools);

        exportButton.addEventListener("click", async () => {
            if (exportButton.disabled || !policySetFilter.value) return;
            const selectedSet = policySetFilter.value;
            exportButton.disabled = true;
            try {
                const response = await fetch("/local-api/policy/policies/export?policySet=" + encodeURIComponent(selectedSet));
                if (!response.ok) {
                    const result = await response.json();
                    throw new Error(result.error || "Could not download policies.");
                }
                const url = URL.createObjectURL(await response.blob());
                const link = document.createElement("a");
                link.href = url;
                link.download = selectedSet.replace(/[\\/:*?"<>|\x00-\x1f]/g, "_") + "-policies.xlsx";
                document.body.appendChild(link);
                link.click();
                link.remove();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (error) {
                showConfigNotice("Could not download policies: " + error.message);
            } finally {
                exportButton.disabled = false;
            }
        });

        function closeImport() {
            const panel = document.getElementById("policy-import-panel");
            if (panel) panel.remove();
        }

        importButton.addEventListener("click", () => {
            if (importButton.disabled) return;
            if (document.getElementById("policy-import-panel")) {
                closeImport();
                return;
            }
            const selectedSet = policySetFilter.value;
            const panel = document.createElement("section");
            panel.id = "policy-import-panel";
            panel.className = "policy-import-panel";
            const heading = document.createElement("h3");
            heading.textContent = `Import policies into “${selectedSet}”`;
            const help = document.createElement("p");
            help.textContent = "Fill in one policy per row. Preview before adding policies to this set; existing policies are kept.";
            const label = document.createElement("p");
            label.id = "policy-import-file-label";
            label.className = "policy-file-label";
            label.textContent = "Excel file (.xlsx, up to 3 MB / 500 policies)";
            const file = document.createElement("input");
            file.id = "policy-import-file";
            file.type = "file";
            file.accept = ".xlsx";
            file.hidden = true;
            const filePicker = document.createElement("div");
            filePicker.className = "policy-file-picker";
            filePicker.setAttribute("role", "group");
            filePicker.setAttribute("aria-labelledby", label.id);
            const chooseFile = document.createElement("button");
            chooseFile.id = "policy-import-choose-file";
            chooseFile.type = "button";
            chooseFile.className = "change-button";
            chooseFile.textContent = "Choose File";
            chooseFile.addEventListener("click", () => file.click());
            const fileName = document.createElement("span");
            fileName.id = "policy-import-filename";
            fileName.textContent = "No file selected";
            fileName.setAttribute("aria-live", "polite");
            filePicker.append(chooseFile, fileName);
            const status = document.createElement("p");
            status.id = "policy-import-status";
            status.setAttribute("role", "status");
            const previewList = document.createElement("div");
            previewList.className = "policy-import-preview-list";
            const actions = document.createElement("div");
            actions.className = "policy-editor-actions";
            const previewButton = document.createElement("button");
            previewButton.id = "policy-import-preview";
            previewButton.type = "button";
            previewButton.className = "change-button";
            previewButton.textContent = "Preview";
            previewButton.disabled = true;
            const confirmButton = document.createElement("button");
            confirmButton.id = "policy-import-confirm";
            confirmButton.type = "button";
            confirmButton.className = "save-button";
            confirmButton.textContent = "Confirm import";
            confirmButton.disabled = true;
            const cancelButton = document.createElement("button");
            cancelButton.type = "button";
            cancelButton.className = "change-button";
            cancelButton.textContent = "Cancel";
            cancelButton.addEventListener("click", () => { closeImport(); importButton.focus(); });
            actions.append(previewButton, confirmButton, cancelButton);
            panel.append(heading, help, label, filePicker, file, status, previewList, actions);
            policyBrowser.insertBefore(panel, list);
            chooseFile.focus();

            let upload = null;
            let previewToken = "";
            let requestVersion = 0;
            let busy = false;
            const isCurrent = version => version === requestVersion && document.body.contains(panel)
                && policySetFilter.value === selectedSet;

            file.addEventListener("change", async () => {
                const version = ++requestVersion;
                upload = null;
                previewToken = "";
                previewList.textContent = "";
                previewButton.disabled = true;
                confirmButton.disabled = true;
                const chosen = file.files && file.files[0];
                fileName.textContent = chosen ? chosen.name : "No file selected";
                if (!chosen) { status.textContent = ""; return; }
                if (!chosen.name.toLowerCase().endsWith(".xlsx") || chosen.size > 3 * 1024 * 1024) {
                    status.textContent = "Select an .xlsx file no larger than 3 MB. Save .xls files as .xlsx first.";
                    return;
                }
                try {
                    const encoded = await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(String(reader.result).split(",")[1]);
                        reader.onerror = () => reject(new Error("Could not read the file. Select it again."));
                        reader.readAsDataURL(chosen);
                    });
                    if (!isCurrent(version)) return;
                    upload = { filename: chosen.name, contentBase64: encoded, policySet: selectedSet };
                    status.textContent = chosen.name + " is ready to preview.";
                    previewButton.disabled = false;
                } catch (error) {
                    if (isCurrent(version)) status.textContent = error.message;
                }
            });

            previewButton.addEventListener("click", async () => {
                if (busy || !upload) return;
                busy = true;
                const version = ++requestVersion;
                previewToken = "";
                previewButton.disabled = true;
                confirmButton.disabled = true;
                previewList.textContent = "";
                status.textContent = "Reading policies...";
                try {
                    const response = await fetch("/local-api/policy/policies/import/preview", {
                        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(upload)
                    });
                    const result = await response.json();
                    if (!isCurrent(version)) return;
                    if (!response.ok || result.success !== true) throw new Error(result.error || "Could not preview this file.");
                    result.rows.forEach(row => {
                        const card = document.createElement("article");
                        card.className = "policy-import-row";
                        const title = document.createElement("h4");
                        title.textContent = `Row ${row.row}: ${row.title}`;
                        const text = document.createElement("p");
                        text.textContent = row.instruction;
                        const detail = document.createElement("p");
                        const states = { ready: "New policy", duplicate: "Already exists — skipped", conflict: "Same name with different content — resolve before importing" };
                        detail.textContent = `${{ 1: "Critical", 2: "Warning", 3: "Informational" }[row.severity]} · ${states[row.status]}`;
                        card.append(title, text, detail);
                        previewList.appendChild(card);
                    });
                    status.textContent = `${result.added} new; ${result.skipped} duplicates skipped; ${result.conflicts} conflicts.`;
                    if (result.conflicts) status.textContent += " Edit the Excel file to resolve conflicts, then upload again.";
                    previewToken = result.previewToken;
                    confirmButton.disabled = result.conflicts > 0 || result.added === 0;
                } catch (error) {
                    if (isCurrent(version)) status.textContent = error.message;
                } finally {
                    busy = false;
                    if (isCurrent(version)) previewButton.disabled = !upload;
                }
            });

            confirmButton.addEventListener("click", async () => {
                if (busy || !upload || !previewToken || confirmButton.disabled) return;
                busy = true;
                confirmButton.disabled = true;
                const wasInert = Boolean(container.inert);
                container.inert = true;
                status.textContent = "Importing policies...";
                try {
                    const response = await fetch("/local-api/policy/policies/import", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ ...upload, previewToken })
                    });
                    const result = await response.json();
                    if (!response.ok || result.success !== true) throw new Error(result.error || "Could not import policies.");
                    await displayJSONOutputWithTags();
                    showConfigNotice(`Added ${result.added} policies to “${selectedSet}”; skipped ${result.skipped} duplicates. Run Summary or Review again to use them.`);
                } catch (error) {
                    previewToken = "";
                    status.textContent = error.message + " Preview again before importing.";
                } finally {
                    container.inert = wasInert;
                    busy = false;
                }
            });
        });

        const list = document.createElement("div");
        list.id = "company-policy-list";
        policyBrowser.appendChild(list);

        function renderPolicies() {
            list.innerHTML = "";

            if (filterSets.length === 0) {
                const empty = document.createElement("p");
                empty.className = "policy-browser-empty";
                empty.textContent = "No policy sets yet. Add one above to create policies.";
                list.appendChild(empty);
                return;
            }

            const visiblePolicies = policies
                .map((item, index) => ({ item, index }))
                .filter(entry =>
                    (entry.item.policySet || "General Policies") ===
                    policySetFilter.value
                );

            if (visiblePolicies.length === 0) {
                const empty = document.createElement("p");
                empty.className = "policy-browser-empty";
                empty.textContent = "No policies in this policy set yet.";
                list.appendChild(empty);
            }

            visiblePolicies.forEach(({ item, index }) => {
                const card = document.createElement("div");
                card.className = "output-item";

                const title = document.createElement("h4");
                title.textContent = item.title || "Untitled policy";
                card.appendChild(title);

                const instruction = document.createElement("p");
                instruction.className = "output-instruction";
                instruction.textContent = item.instruction || "";
                card.appendChild(instruction);

                const metadata = document.createElement("div");
                metadata.className = "policy-metadata";
                card.appendChild(metadata);

                const tags = document.createElement("p");
                tags.textContent = "Tags: " +
                    (Array.isArray(item.tags) ? item.tags.join(", ") : "");
                metadata.appendChild(tags);

                const severity = document.createElement("p");
                const severityLabels = {
                    1: "Critical",
                    2: "Warning",
                    3: "Informational"
                };
                severity.textContent = "Severity: " +
                    (severityLabels[Number(item.severity)] || "Warning");
                metadata.appendChild(severity);

                const groups = document.createElement("p");
                groups.textContent = "Groups: " +
                    (Array.isArray(item.groups) && item.groups.length
                        ? item.groups.join(", ")
                        : "All");
                metadata.appendChild(groups);

                const editButton = document.createElement("button");
                editButton.type = "button";
                editButton.textContent = "Change";
                editButton.className = "change-button";
                editButton.addEventListener("click", () => {
                    buildEditor(
                        card, policies, policySets, item, index, false
                    );
                });
                const deleteButton = document.createElement("button");
                deleteButton.type = "button";
                deleteButton.textContent = "Delete";
                deleteButton.className = "delete-button";
                deleteButton.addEventListener("click", () => deleteWithConfirmation(
                    deleteButton, "/local-api/policy/policies/delete", { policy: item },
                    "Delete policy?", `Delete "${item.title || "Untitled policy"}"? This cannot be undone.`
                ));
                const policyActions = document.createElement("div");
                policyActions.className = "policy-editor-actions";
                policyActions.append(editButton, deleteButton);
                card.appendChild(policyActions);

                list.appendChild(card);
            });
        }

        policySetFilter.addEventListener("change", () => {
            closeImport();
            const editor = container.querySelector("#new-policy-editor");
            if (editor) editor.remove();
            renderPolicies();
        });

        addButton.addEventListener("click", () => {
            if (filterSets.length === 0) return;
            const existing = container.querySelector("#new-policy-editor");
            if (existing) {
                existing.remove();
                return;
            }

            const editor = document.createElement("div");
            editor.id = "new-policy-editor";
            list.parentNode.insertBefore(editor, list);

            buildEditor(editor, policies, policySets, {
                id: 0,
                title: "",
                instruction: "",
                tags: [],
                severity: 2,
                groups: [],
                policySet: policySetFilter.value
            }, -1, true);
        });

        renderPolicies();
    } catch (error) {
        console.error("[Company Policy] Load failed:", error);
        container.innerHTML = "";
        const message = document.createElement("p");
        message.textContent =
            "Could not load policies. Check that the Ally Legal Flex local service on port 8084 is running. " +
            error.message;
        container.appendChild(message);
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "config-button";
        retry.textContent = "Retry loading policies";
        retry.addEventListener("click", displayJSONOutputWithTags);
        container.appendChild(retry);
    }
}
