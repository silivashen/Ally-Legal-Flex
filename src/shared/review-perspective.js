// A perspective belongs to the open task pane, never global browser storage.
function mappingRows() {
    return Array.from(document.getElementById("perspective-mappings")?.querySelectorAll(".perspective-mapping-row") || []);
}

function rowFields(row) {
    return [row.querySelector('[name="contractParty"]'), row.querySelector('[name="policyParty"]')];
}

export function getReviewPerspective() {
    const mappings = mappingRows().map(row => {
        const [contract, policy] = rowFields(row);
        return { contractParty: contract.value.trim(), policyParty: policy.value.trim() };
    }).filter(row => row.contractParty || row.policyParty);
    return mappings.length ? JSON.stringify(mappings) : "";
}

export function validateReviewPerspectiveInputs(focus = true) {
    const error = document.getElementById("review-perspective-error");
    let missingField = null;
    let message = "";
    mappingRows().forEach((row, index) => {
        const fields = rowFields(row);
        const incomplete = fields.some(input => input.value.trim()) && fields.some(input => !input.value.trim());
        fields.forEach(input => {
            input.setAttribute("aria-invalid", String(incomplete && !input.value.trim()));
            if (incomplete && !input.value.trim() && !missingField) {
                missingField = input;
                message = `Complete both fields in mapping ${index + 1}, or remove that mapping.`;
            }
        });
    });
    if (error) error.textContent = message;
    if (focus && missingField) missingField.focus();
    return !missingField;
}

export function onReviewPerspectiveChange(callback) {
    document.getElementById("perspective-mappings")?.addEventListener("input", callback);
}

function initializeReviewPerspective() {
    const mappings = document.getElementById("perspective-mappings");
    const addButton = document.getElementById("add-mapping");
    if (!mappings || !addButton) return;
    const status = document.getElementById("mapping-status");
    const notify = message => {
        if (status) status.textContent = message;
        if (document.getElementById("review-perspective-error")?.textContent) validateReviewPerspectiveInputs(false);
        mappings.dispatchEvent(new Event("input", { bubbles: true }));
    };
    const relabel = () => mappingRows().forEach((row, index) => {
        row.setAttribute("aria-label", `Mapping ${index + 1}`);
        const [contract, policy] = rowFields(row);
        contract.setAttribute("aria-label", `Contract party, mapping ${index + 1}`);
        policy.setAttribute("aria-label", `Policy party, mapping ${index + 1}`);
        const remove = row.querySelector("button");
        remove.setAttribute("aria-label", `Remove mapping ${index + 1}`);
        remove.title = `Remove mapping ${index + 1}`;
    });
    const addRow = (focus = false) => {
        const row = document.createElement("div");
        row.className = "perspective-mapping-row";
        row.setAttribute("role", "group");
        for (const [name, placeholder] of [["contractParty", "e.g. Party A"], ["policyParty", "e.g. Seller"]]) {
            const input = document.createElement("input");
            input.type = "text";
            input.name = name;
            input.placeholder = placeholder;
            input.autocomplete = "off";
            input.spellcheck = false;
            input.setAttribute("aria-describedby", "review-perspective-error");
            row.appendChild(input);
            if (name === "contractParty") {
                const equals = document.createElement("span");
                equals.className = "mapping-equals";
                equals.textContent = "=";
                equals.setAttribute("aria-hidden", "true");
                row.appendChild(equals);
            }
        }
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-mapping-button";
        remove.textContent = "×";
        remove.addEventListener("click", () => {
            const focusRow = row.nextElementSibling || row.previousElementSibling;
            row.remove();
            if (!mappings.children.length) addRow(true);
            else focusRow.querySelector("input").focus();
            relabel();
            notify("Mapping removed.");
        });
        row.appendChild(remove);
        mappings.appendChild(row);
        relabel();
        if (focus) row.querySelector("input").focus();
    };
    addButton.addEventListener("click", () => { addRow(true); notify("Mapping added."); });
    mappings.addEventListener("input", () => {
        if (document.getElementById("review-perspective-error")?.textContent) validateReviewPerspectiveInputs(false);
    });
    addRow();
}

function displayPerspective(perspective) {
    if (!perspective) return "Neutral";
    try {
        const mappings = JSON.parse(perspective);
        if (Array.isArray(mappings)) return mappings.map(row => `${row.contractParty} = ${row.policyParty}`).join("\n");
    } catch (_) { /* Older result labels may contain plain text. */ }
    return perspective;
}

export function appendReviewPerspective(container, perspective) {
    const label = document.createElement("p");
    label.classList.add("review-perspective-label");
    label.style.whiteSpace = "pre-wrap";
    label.style.overflowWrap = "anywhere";
    label.textContent = "Review Perspective: " + displayPerspective(perspective);
    container.appendChild(label);
}

initializeReviewPerspective();

export function validateReviewPerspective(result, expected) {
    // Older backends remain usable for neutral requests only.
    if (expected === "" && result?.reviewPerspective === undefined) return;
    if (result?.reviewPerspective !== expected) {
        throw new Error(
            "The backend did not confirm this review perspective. " +
            "Restart the updated backend and try again."
        );
    }
}
