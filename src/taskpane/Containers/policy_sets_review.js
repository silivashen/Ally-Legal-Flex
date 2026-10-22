// Review policy-set selector.
// Keeps policy sets separate from permission groups ("groups").

let policySetLoadVersion = 0;
let pendingPolicySetRenames = [];
let publishedPolicySelection = "[]";

function readSelectedPolicySets() {
    const options = document.getElementById("policy-set-options");
    return options ? Array.from(options.querySelectorAll(
        'input[type="checkbox"][data-policy-set]:checked'
    )).map(input => input.dataset.policySet) : [];
}

window.getSelectedPolicySets = readSelectedPolicySets;

function notifyPolicySetSelectionChanged() {
    const policySets = readSelectedPolicySets();
    const selectionKey = JSON.stringify(policySets.slice().sort());
    if (selectionKey === publishedPolicySelection) return;
    publishedPolicySelection = selectionKey;
    window.dispatchEvent(new CustomEvent("ally-policy-selection-changed", {
        detail: { policySets }
    }));
}

async function initializePolicySetSelector(change = null) {
    const options = document.getElementById("policy-set-options");
    const errorBox = document.getElementById("policy-set-error");

    if (!options) return;

    const loadVersion = ++policySetLoadVersion;
    if (change && change.action === "rename" && change.oldName && change.newName) {
        pendingPolicySetRenames.push(change);
    }

    try {
        const response = await fetch(
            "/local-api/policy/policy-sets",
            { cache: "no-store" }
        );

        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        const data = await response.json();
        if (loadVersion !== policySetLoadVersion) return;
        if (!Array.isArray(data.policySets)) {
            throw new Error("The server returned an invalid policy set list.");
        }
        const policySets = data.policySets;

        // Read after the fetch so changes made while loading are preserved.
        const previouslySelected = new Set(readSelectedPolicySets());
        for (const rename of pendingPolicySetRenames) {
            if (previouslySelected.delete(rename.oldName)) previouslySelected.add(rename.newName);
        }
        pendingPolicySetRenames = [];
        options.replaceChildren();

        if (policySets.length === 0) {
            options.textContent = "No policy sets yet. Add one in Config.";
        }

        policySets.forEach(name => {
            const label = document.createElement("label");
            label.style.display = "block";
            label.style.marginBottom = "6px";
            label.style.cursor = "pointer";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = name;
            checkbox.dataset.policySet = name;

            checkbox.checked = previouslySelected.has(name);
            checkbox.style.marginRight = "8px";
            checkbox.addEventListener("change", notifyPolicySetSelectionChanged);

            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(name));
            options.appendChild(label);
        });

        if (errorBox) {
            errorBox.style.display = "none";
            errorBox.textContent = "";
        }

        notifyPolicySetSelectionChanged();

        console.log("[Policy Sets] Selector loaded:", policySets);
    } catch (error) {
        if (loadVersion !== policySetLoadVersion) return;
        console.error("[Policy Sets] Failed to load:", error);
        options.textContent = "Could not load policy sets.";

        if (errorBox) {
            errorBox.textContent =
                "Please confirm the local service at " +
                "port 8084 is running, then refresh this pane.";
            errorBox.style.display = "block";
        }

        // Fail closed: do not silently review under a guessed policy set.
        notifyPolicySetSelectionChanged();
    }
}

initializePolicySetSelector();

let policySetRefreshTimer = null;

function schedulePolicySetRefresh() {
    if (document.hidden) return;

    clearTimeout(policySetRefreshTimer);
    policySetRefreshTimer = setTimeout(() => {
        initializePolicySetSelector();
    }, 150);
}

window.addEventListener("focus", schedulePolicySetRefresh);
document.addEventListener("visibilitychange", schedulePolicySetRefresh);

function handlePolicySetsUpdated(change) {
    if (!change || change.type !== "policy-sets-updated") return;
    console.log("[Policy Sets] Config update received:", change);
    initializePolicySetSelector(change);
}

if (typeof BroadcastChannel !== "undefined") {
    const policySetsChannel = new BroadcastChannel("ally-policy-sets");
    policySetsChannel.addEventListener("message", event => {
        handlePolicySetsUpdated(event.data);
    });
} else {
    window.addEventListener("storage", event => {
        if (
            event.key !== "ally-policy-sets-updated" ||
            !event.newValue
        ) return;

        try {
            handlePolicySetsUpdated(JSON.parse(event.newValue));
        } catch (error) {
            console.error("[Policy Sets] Invalid update message:", error);
        }
    });
}
