import { readWordDocument, documentRequestFields } from "../../shared/word-document.js";
import { resolveLocalEndpoint } from "../../shared/local-endpoint.js";
import { getReviewPerspective, onReviewPerspectiveChange, appendReviewPerspective, validateReviewPerspective, validateReviewPerspectiveInputs } from "../../shared/review-perspective.js";

// ============================================================
// Ally - Summarize the CURRENT Word document
// ============================================================

let summaryRequestVersion = 0;
let summaryController = null;
let summaryPolicySets = null;
let summaryPerspective = null;

function samePolicySets(first, second) {
    const valid = value => Array.isArray(value) &&
        value.every(name => typeof name === "string" && name.trim().length > 0);
    return valid(first) && valid(second) &&
        JSON.stringify(first.slice().sort()) === JSON.stringify(second.slice().sort());
}

function currentPolicySets() {
    return typeof window.getSelectedPolicySets === "function"
        ? window.getSelectedPolicySets()
        : [];
}

function cancelSummaryRequest() {
    summaryRequestVersion += 1;
    if (summaryController) summaryController.abort();
    summaryController = null;
    const indexSpinner = document.getElementById("index-doc-spinner");
    if (indexSpinner) indexSpinner.style.display = "none";
}

window.addEventListener("ally-policy-selection-changed", () => {
    if (!summaryPolicySets || samePolicySets(summaryPolicySets, currentPolicySets())) return;
    invalidateSummary("Policy Set selection changed. Run Summary again to use the current selection.");
});

onReviewPerspectiveChange(() => {
    if (summaryPerspective === null || summaryPerspective === getReviewPerspective()) return;
    invalidateSummary("Review perspective changed. Run Summary again to use the current perspective.");
});

function invalidateSummary(messageText) {
    cancelSummaryRequest();
    summaryPolicySets = null;
    summaryPerspective = null;
    localStorage.removeItem("FullSummaryData");
    const container = document.getElementById("summary-container");
    if (!container) return;
    container.innerHTML = "";
    const title = document.createElement("h2");
    title.textContent = "Summary";
    const message = document.createElement("p");
    message.textContent = messageText;
    const button = document.createElement("button");
    button.classList.add("search-button");
    button.textContent = "Run Summary Again";
    button.addEventListener("click", document_summary);
    container.appendChild(title);
    container.appendChild(message);
    container.appendChild(button);
}

// Main entry point
export async function document_summary() {
    const container = document.getElementById("summary-container");
    const endpoint = resolveLocalEndpoint(localStorage.getItem("pfendpoint"));
    const language = localStorage.getItem("language") || "Chinese";

    if (!container) {
        console.error("Summary error: summary-container not found.");
        return;
    }

    cancelSummaryRequest();
    const requestVersion = summaryRequestVersion;
    summaryPolicySets = null;
    summaryPerspective = null;

    if (!endpoint) {
        showSummaryError(container, "Backend endpoint is missing.");
        return;
    }

    // Validate Policy Set selection BEFORE showing any spinner.
    if (typeof window.getSelectedPolicySets !== "function") {
        showSummaryError(
            container,
            "Policy Set selector is not loaded. Please refresh the pane."
        );
        return;
    }

    const selection = window.getSelectedPolicySets();

    if (!samePolicySets(selection, selection) || selection.length === 0) {
        showSummaryError(
            container,
            "Please select at least one Policy Set before Summary."
        );
        return;
    }
    if (!validateReviewPerspectiveInputs()) return;
    const selectedPolicySets = selection.slice();
    summaryPolicySets = selectedPolicySets;
    const reviewPerspective = getReviewPerspective();
    summaryPerspective = reviewPerspective;
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    summaryController = controller;
    const isCurrentRequest = () => requestVersion === summaryRequestVersion &&
        samePolicySets(selectedPolicySets, currentPolicySets()) &&
        reviewPerspective === getReviewPerspective();

    // Show loading state
    container.innerHTML = "";

    const spinner = document.createElement("div");
    spinner.id = "summary-spinner";
    spinner.classList.add("spinner");
    spinner.style.display = "block";
    container.appendChild(spinner);

    const indexSpinner = document.getElementById("index-doc-spinner");

    if (indexSpinner) {
        indexSpinner.style.display = "flex";
    }

    try {
        // ----------------------------------------------------
        // 1. Read the CURRENT Word document
        // ----------------------------------------------------
        const documentSnapshot = await readWordDocument();
        const documentText = documentSnapshot.text.trim();

        if (!isCurrentRequest()) return;

        console.log(
            "Current Word document character count:",
            documentText.length
        );

        if (!documentText) {
            throw new Error(
                "The current Word document contains no readable text."
            );
        }

        // ----------------------------------------------------
        // 2. Clear the previous document's summary cache
        // ----------------------------------------------------
        localStorage.removeItem("FullSummaryData");

        // Read the current user's groups
        let groups = [];

        try {
            const savedGroups = localStorage.getItem("groups");
            groups = savedGroups ? JSON.parse(savedGroups) : [];

            if (!Array.isArray(groups)) {
                groups = [];
            }
        } catch (error) {
            console.warn("Unable to read groups:", error);
            groups = [];
        }

        // ----------------------------------------------------
        // 3. Send the current document text to the backend
        // ----------------------------------------------------
        const payload = {
            query_type: 1,
            question: documentText,
            ...documentRequestFields(documentSnapshot),
            language: language,
            group: groups,
            policySets: selectedPolicySets,
            reviewPerspective
        };

        console.log("Sending current document to summary backend.");

        const response = await fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload),
            ...(controller ? { signal: controller.signal } : {})
        });

        const responseText = await response.text();
        if (!isCurrentRequest()) return;

        let data;

        try {
            data = responseText ? JSON.parse(responseText) : {};
        } catch (error) {
            throw new Error(
                `Backend returned invalid JSON. HTTP ${response.status}: ` +
                responseText.substring(0, 500)
            );
        }

        console.log("Summary HTTP status:", response.status);
        console.log("Summary backend response:", data);

        if (!response.ok) {
            throw new Error(
                `Backend HTTP ${response.status}: ` +
                JSON.stringify(data)
            );
        }

        // Support a response wrapped in { answer: ... }
        let result = data.answer ?? data;

        // Some flows return JSON as a string
        if (typeof result === "string") {
            try {
                result = JSON.parse(result);
            } catch (error) {
                throw new Error(
                    "The backend returned text instead of structured " +
                    "summary data: " + result.substring(0, 300)
                );
            }
        }

        if (result && result.error) {
            throw new Error(result.error);
        }

        // This metadata is stamped by the backend after policy filtering.
        if (!result || !samePolicySets(result.PolicySets, selectedPolicySets)) {
            throw new Error(
                "The backend did not confirm the selected Policy Sets. " +
                "Restart the updated backend and run Summary again."
            );
        }

        if (!result || !Array.isArray(result.Items)) {
            throw new Error(
                "Unexpected summary response. Expected an object " +
                "containing an Items array. Received: " +
                JSON.stringify(result).substring(0, 500)
            );
        }

        // Do not cache the response across different Word documents.
        validateReviewPerspective(result, reviewPerspective);
        displaySummaryData(result, reviewPerspective);

    } catch (error) {
        if (!isCurrentRequest()) return;
        console.error("Document summary failed:", error);

        showSummaryError(
            container,
            error && error.message
                ? error.message
                : String(error)
        );

    } finally {
        // Each request owns its spinner; a late request must not clean up a newer one.
        spinner.remove();
        if (requestVersion === summaryRequestVersion) {
            summaryController = null;
            const currentIndexSpinner = document.getElementById("index-doc-spinner");
            if (currentIndexSpinner) currentIndexSpinner.style.display = "none";
        }
    }
}


// ============================================================
// Display an error and provide a retry button
// ============================================================

function showSummaryError(container, message) {
    container.innerHTML = "";

    const title = document.createElement("h2");
    title.textContent = "Summary";
    container.appendChild(title);

    const errorMessage = document.createElement("div");
    errorMessage.classList.add("warning");
    errorMessage.textContent = "Summary failed: " + message;
    container.appendChild(errorMessage);

    const retryButton = document.createElement("button");
    retryButton.classList.add("search-button");
    retryButton.textContent = "Try Again";
    retryButton.addEventListener("click", document_summary);

    container.appendChild(retryButton);
}


// ============================================================
// Display the document summary
// Expected format:
// {
//   "Summary": "...",
//   "KeyPoints": ["..."],
//   "Items": [
//     {
//       "title": "...",
//       "summary": "...",
//       "notes": "...",
//       "keyItems": ["..."],
//       "original_text": "..."
//     }
//   ]
// }
// ============================================================

function displaySummaryData(policyData, reviewPerspective = "") {
    const container = document.getElementById("summary-container");

    if (!container) {
        console.error("Cannot display summary: container not found.");
        return;
    }

    if (!policyData || !Array.isArray(policyData.Items)) {
        showSummaryError(
            container,
            "The summary response does not contain an Items array."
        );
        return;
    }

    container.innerHTML = "";
    appendReviewPerspective(container, reviewPerspective);

    const policySetsLabel = document.createElement("p");
    policySetsLabel.id = "doc-summary-policy-sets";
    policySetsLabel.textContent = "Policy Sets: " + policyData.PolicySets.join(", ");
    container.appendChild(policySetsLabel);

    // --------------------------------------------------------
    // Document Summary section
    // --------------------------------------------------------
    const summaryDiv = document.createElement("div");
    summaryDiv.classList.add("document-summary");

    const summaryTitle = document.createElement("h3");
    summaryTitle.textContent = "▼ Document Summary";
    summaryTitle.id = "doc-summary-result-title";
    summaryTitle.style.cursor = "pointer";

    const summaryText = document.createElement("p");
    summaryText.id = "doc-summary-summary-text";
    summaryText.textContent =
        policyData.Summary || "No overall summary was returned.";

    summaryTitle.addEventListener("click", () => {
        const isVisible = summaryText.style.display !== "none";

        summaryText.style.display = isVisible ? "none" : "block";
        summaryTitle.textContent = isVisible
            ? "► Document Summary"
            : "▼ Document Summary";
    });

    summaryDiv.appendChild(summaryTitle);
    summaryDiv.appendChild(summaryText);
    container.appendChild(summaryDiv);

    // --------------------------------------------------------
    // Key Points section
    // --------------------------------------------------------
    if (
        Array.isArray(policyData.KeyPoints) &&
        policyData.KeyPoints.length > 0
    ) {
        const keyPointsSection = document.createElement("div");
        keyPointsSection.classList.add("doc-summary-field");

        const keyPointsTitle = document.createElement("h4");
        keyPointsTitle.textContent = "Key Points";
        keyPointsSection.appendChild(keyPointsTitle);

        const keyPointsList = document.createElement("ul");

        policyData.KeyPoints.forEach((point) => {
            const listItem = document.createElement("li");
            listItem.textContent = String(point);
            keyPointsList.appendChild(listItem);
        });

        keyPointsSection.appendChild(keyPointsList);
        container.appendChild(keyPointsSection);
    }

    // --------------------------------------------------------
    // Individual clause summaries
    // --------------------------------------------------------
    const sectionsTitle = document.createElement("h4");
    sectionsTitle.textContent = "Sections Summary List";
    sectionsTitle.id = "doc-summary-paragraphs-title";
    container.appendChild(sectionsTitle);

    policyData.Items.forEach((item, index) => {
        const sectionDiv = document.createElement("div");
        sectionDiv.classList.add("doc-summary-container");
        sectionDiv.id = `doc-summary-item-${index}`;

        // Clickable clause heading
        const headerDiv = document.createElement("div");
        headerDiv.classList.add("doc-summary-header");
        headerDiv.style.cursor = "pointer";

        const title = document.createElement("span");
        title.classList.add("doc-summary-title");
        title.textContent = item.title || `Section ${index + 1}`;

        const toggleMarker = document.createElement("span");
        toggleMarker.classList.add("toggle-marker");
        toggleMarker.textContent = "▼";

        headerDiv.appendChild(title);
        headerDiv.appendChild(toggleMarker);
        sectionDiv.appendChild(headerDiv);

        // Expandable content
        const contentDiv = document.createElement("div");
        contentDiv.classList.add("doc-summary-content");
        contentDiv.id = `doc-summary-content-${index}`;
        contentDiv.style.display = "none";

        headerDiv.addEventListener("click", () => {
            const isVisible = contentDiv.style.display !== "none";

            contentDiv.style.display = isVisible ? "none" : "block";
            toggleMarker.textContent = isVisible ? "▼" : "▲";
        });

        // Summary
        addSummaryField(
            contentDiv,
            "Summary",
            item.summary || "No summary available."
        );

        // Notes
        addSummaryField(
            contentDiv,
            "Notes",
            item.notes || "No notes available."
        );

        // Original contract wording
        if (item.original_text) {
            addSummaryField(
                contentDiv,
                "Original Text",
                item.original_text
            );
        }

        // Key Items
        if (Array.isArray(item.keyItems) && item.keyItems.length > 0) {
            const keyItemsField = document.createElement("div");
            keyItemsField.classList.add("doc-summary-field");

            const keyItemsTitle = document.createElement("div");
            keyItemsTitle.classList.add("field-title");
            keyItemsTitle.textContent = "Key Items:";

            const tagsDiv = document.createElement("div");
            tagsDiv.classList.add("key-items");

            item.keyItems.forEach((keyItem) => {
                const tag = document.createElement("span");
                tag.classList.add("key-item");
                tag.textContent = String(keyItem);
                tagsDiv.appendChild(tag);
            });

            keyItemsField.appendChild(keyItemsTitle);
            keyItemsField.appendChild(tagsDiv);
            contentDiv.appendChild(keyItemsField);
        }

        // Find the clause in the current Word document
        const goToButton = document.createElement("button");
        goToButton.classList.add("search-button");
        goToButton.textContent = "Go to";

        goToButton.addEventListener("click", () => {
            findInDocument(item.original_text || item.title);
        });

        contentDiv.appendChild(goToButton);
        sectionDiv.appendChild(contentDiv);
        container.appendChild(sectionDiv);
    });

    // --------------------------------------------------------
    // Run Again button
    // --------------------------------------------------------
    const retryButton = document.createElement("button");
    retryButton.classList.add("search-button");
    retryButton.textContent = "Run Summary Again";
    retryButton.addEventListener("click", document_summary);
    container.appendChild(retryButton);
}


// ============================================================
// Add a labelled field
// ============================================================

function addSummaryField(container, label, value) {
    const field = document.createElement("div");
    field.classList.add("doc-summary-field");

    const title = document.createElement("div");
    title.classList.add("field-title");
    title.textContent = label + ":";

    const content = document.createElement("div");
    const text = String(value ?? "");
    const policyLabel = "Relevant Company Policy:";
    const policyLabelMatch = label === "Notes"
        ? /(^|\n)Relevant Company Policy:(?=\n|$)/.exec(text)
        : null;

    if (policyLabelMatch) {
        const labelStart = policyLabelMatch.index + policyLabelMatch[1].length;
        content.textContent = text.slice(0, labelStart);
        const policyTitle = document.createElement("strong");
        policyTitle.textContent = policyLabel;
        content.appendChild(policyTitle);
        content.appendChild(document.createTextNode(text.slice(labelStart + policyLabel.length)));
    } else {
        content.textContent = text;
    }
    content.style.whiteSpace = "pre-line";

    field.appendChild(title);
    field.appendChild(content);
    container.appendChild(field);
}


// ============================================================
// Find and select text in the current Word document
// ============================================================


async function findInDocument(text) {
    if (!text || typeof text !== "string") {
        console.warn("[Go to] No searchable text.");
        return;
    }

    const normalize = (value) =>
        String(value || "").replace(/\s+/g, " ").trim();

    const source = normalize(text);

    if (!source) return;

    const candidates = [];
    const addCandidate = (value) => {
        const candidate = normalize(value);

        if (
            candidate.length >= 12 &&
            !candidates.includes(candidate)
        ) {
            candidates.push(candidate);
        }
    };

    // 1. Try the complete text first.
    addCandidate(source);

    // 2. Split merged clauses using common Chinese and English
    // clause boundaries, paragraph breaks, and numbering.
    const parts = String(text)
        .split(/\r?\n+|(?=(?:第[一二三四五六七八九十百\d]+条))|(?=(?:\d+(?:\.\d+)*[、.．)]\s*))/)
        .map(normalize)
        .filter(part => part.length >= 12);

    parts.forEach(addCandidate);

    // 3. Try shorter excerpts from the beginning, middle and end.
    for (const length of [200, 120, 80, 50, 30]) {
        if (source.length > length) {
            addCandidate(source.slice(0, length));

            const middle = Math.max(
                0,
                Math.floor((source.length - length) / 2)
            );
            addCandidate(source.slice(middle, middle + length));

            addCandidate(source.slice(-length));
        }
    }

    console.log("[Go to] Search candidates:", candidates.length);

    try {
        await Word.run(async (context) => {
            for (const candidate of candidates) {
                const results = context.document.body.search(candidate, {
                    ignorePunct: true,
                    matchCase: false,
                    matchWholeWord: false
                });

                results.load("text");
                await context.sync();

                console.log(
                    "[Go to] Candidate length:",
                    candidate.length,
                    "matches:",
                    results.items.length
                );

                if (results.items.length > 0) {
                    results.items[0].select();
                    await context.sync();

                    console.log("[Go to] Match selected.");
                    return;
                }
            }

            console.warn(
                "[Go to] No match found. The source text may combine " +
                "multiple clauses or differ from the Word document."
            );
        });
    } catch (error) {
        console.error("[Go to] Search failed:", error);
    }
}
