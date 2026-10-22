import { readWordDocument, documentRequestFields } from "../../shared/word-document.js";
import { resolveLocalEndpoint } from "../../shared/local-endpoint.js";
import { getReviewPerspective, onReviewPerspectiveChange, appendReviewPerspective, validateReviewPerspective, validateReviewPerspectiveInputs } from "../../shared/review-perspective.js";

// ============================================================
// Ally Review / Redline
// ============================================================

let storedSelectedText = "";
let selectedOoxml = "";
let reviewRequestVersion = 0;
let reviewPerspective = null;

function invalidateReview() {
    reviewRequestVersion += 1;
    reviewPerspective = null;
    const container = document.getElementById("policy-results");
    if (container) {
        container.innerHTML = "";
        const message = document.createElement("p");
        message.textContent = "Review perspective changed. Run Review again to use the current perspective.";
        container.appendChild(message);
    }
    const button = document.getElementById("fetchPolicyData");
    if (button) button.style.display = "";
}

onReviewPerspectiveChange(() => {
    if (reviewPerspective === null || reviewPerspective === getReviewPerspective()) return;
    invalidateReview();
});


// ============================================================
// Main review function
// ============================================================

export async function summary() {
    const container = document.getElementById("policy-results");

    if (!container) {
        console.error("Redline error: policy-container not found.");
        return;
    }

    if (!validateReviewPerspectiveInputs()) return;
    const startButton = document.getElementById("fetchPolicyData");

    const endpoint = resolveLocalEndpoint(localStorage.getItem("pfendpoint"));
    const language = localStorage.getItem("language") || "Chinese";
    const perspective = getReviewPerspective();
    const requestVersion = ++reviewRequestVersion;
    reviewPerspective = perspective;
    const isCurrentRequest = () => requestVersion === reviewRequestVersion &&
        perspective === getReviewPerspective();

    console.log("Redline endpoint:", endpoint);
    console.log("Redline language:", language);

    // Hide the startup Review button while the review runs.
    if (startButton) startButton.style.display = "none";

    container.innerHTML = "";

    const spinner = document.createElement("div");
    spinner.id = "policy-spinner";
    spinner.classList.add("spinner");
    spinner.style.display = "block";
    container.appendChild(spinner);

    try {
        // Read the selection and its current contract in the same Word context.
        const documentSnapshot = await readWordDocument({ captureSelection: true });
        const fullText = documentSnapshot.selectionText.trim();

        if (!isCurrentRequest()) return;
        console.log("Selected text length:", fullText.length);

        if (!fullText) {
            if (startButton) startButton.style.display = "";
            displayNoTextSelectedMessage();
            return;
        }

        if (!endpoint) {
            throw new Error("Backend endpoint is missing.");
        }

        // Preserve the complete original text.
        storedSelectedText = fullText;

        // Save original formatting information.
        saveSelectedText();

        await processSelectedText(fullText, endpoint, language, documentSnapshot, perspective, isCurrentRequest);

    } catch (error) {
        if (!isCurrentRequest()) return;
        console.error("Redline review failed:", error);

        // Restore the startup button so the user can retry.
        if (startButton) startButton.style.display = "";

        container.innerHTML = "";

        const errorMessage = document.createElement("div");
        errorMessage.classList.add("warning");
        errorMessage.textContent =
            "Review failed: " +
            (error?.message || String(error));

        container.appendChild(errorMessage);

    } finally {
        // Only remove the spinner owned by this request.
        spinner.remove();
    }
}


// ============================================================
// Message when no text is selected
// ============================================================

function displayNoTextSelectedMessage() {
    const container = document.getElementById("policy-results");

    if (!container) return;

    container.innerHTML = "";

    const title = document.createElement("h2");
    title.classList.add("policy-title");
    title.textContent = "Review & Mark-up";

    const warning = document.createElement("div");
    warning.classList.add("warning");
    warning.textContent =
        "Please select some text in the Word document and try again.";

    container.appendChild(title);
    container.appendChild(warning);
    container.appendChild(document.createElement("p"));
    container.appendChild(document.createElement("hr"));


}


// ============================================================
// Call backend to review selected text
// ============================================================

async function processSelectedText(text, endpoint, language, documentSnapshot, perspective, isCurrentRequest) {
    let groups = [];

    try {
        const savedGroups = localStorage.getItem("groups");
        groups = savedGroups ? JSON.parse(savedGroups) : [];

        if (!Array.isArray(groups)) {
            groups = [];
        }
    } catch (error) {
        console.warn("Could not read user groups:", error);
    }

    if (typeof window.getSelectedPolicySets !== "function") {
        throw new Error("Policy Set selector is not loaded. Please refresh the pane.");
    }

    const selectedPolicySets = window.getSelectedPolicySets();

    if (!Array.isArray(selectedPolicySets)) {
        throw new Error("Policy Set selection is invalid. Please refresh the pane.");
    }
    if (selectedPolicySets.length === 0) {
        throw new Error("Please select at least one Policy Set in General Settings before running Review.");
    }

    const response = await fetch(endpoint, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            query_type: 2,
            question: text,
            group: groups,
            language: language,
            policySets: selectedPolicySets,
            ...documentRequestFields(documentSnapshot),
            reviewPerspective: perspective
        })
    });

    const responseText = await response.text();
    if (!isCurrentRequest()) return;
    let data;

    try {
        data = responseText ? JSON.parse(responseText) : {};
    } catch (error) {
        throw new Error(
            `Backend returned invalid JSON (HTTP ${response.status}): ` +
            responseText.substring(0, 500)
        );
    }

    console.log("Redline HTTP status:", response.status);

    if (!response.ok) {
        throw new Error(
            `Backend HTTP ${response.status}: ${JSON.stringify(data)}`
        );
    }

    const answer = data?.answer ?? data;

    if (!answer || typeof answer !== "object") {
        throw new Error(
            "Unexpected backend response: " + JSON.stringify(data)
        );
    }

    if (answer.error) {
        throw new Error(typeof answer.error === "string" ? answer.error : "The review could not be completed.");
    }
    validateReviewPerspective(answer, perspective);

    if (answer.warning) {
        displayWarningMessage(perspective);
        return;
    }

    if (!Array.isArray(answer.PolicyItems)) {
        throw new Error(
            "Backend response does not contain a PolicyItems array."
        );
    }

    displayPolicyItems(answer.PolicyItems, perspective);
}


// ============================================================
// Display warning when no policy matches
// ============================================================

function displayWarningMessage(perspective = "") {
    const container = document.getElementById("policy-results");

    if (!container) return;

    container.innerHTML = "";
    appendReviewPerspective(container, perspective);

    const title = document.createElement("h2");
    title.classList.add("policy-title");
    title.textContent = "Review & Mark-up";
    container.appendChild(title);

    const warning = document.createElement("div");
    warning.classList.add("warning");
    warning.textContent =
        "I couldn't find any matching company policy items for the selected text.";
    container.appendChild(warning);

    const warning2 = document.createElement("div");
    warning2.classList.add("warning");
    warning2.textContent =
        "Please check the text or try another clause.";
    container.appendChild(warning2);

    const table = document.createElement("table");
    table.classList.add("causes-table");

    const causes = [
        "Cause 1: No matching policy found.",
        "Cause 2: Text may be too vague.",
        "Cause 3: System error."
    ];

    causes.forEach((cause) => {
        const row = document.createElement("tr");
        const cell = document.createElement("td");

        cell.textContent = cause;
        row.appendChild(cell);
        table.appendChild(row);
    });

    container.appendChild(table);
    container.appendChild(document.createElement("hr"));

    const reviewButton = document.createElement("button");
    reviewButton.classList.add("search-button");
    reviewButton.textContent = "Review Next";
    reviewButton.addEventListener("click", summary);

    container.appendChild(reviewButton);
}


// ============================================================
// Display all policy review items
// ============================================================

function displayPolicyItems(policyItems, perspective = "") {
    const container = document.getElementById("policy-results");

    if (!container) return;

    container.innerHTML = "";
    appendReviewPerspective(container, perspective);

    if (!Array.isArray(policyItems) || policyItems.length === 0) {
        const message = document.createElement("div");
        message.classList.add("warning");
        message.textContent =
            "No review results were returned. Please try again.";

        container.appendChild(message);
    } else {
        policyItems.forEach((item, index) => {
            const policyDiv = createPolicyDiv(item, index);
            container.appendChild(policyDiv);
        });
    }

    const reviewButton = document.createElement("button");
    reviewButton.classList.add("search-button");
    reviewButton.textContent = "Review Next";
    reviewButton.addEventListener("click", summary);

    container.appendChild(reviewButton);
}


// ============================================================
// Create an individual policy review card
// ============================================================

function isGeneralReview(item) {
    return item.review_basis === "general" ||
        (Array.isArray(item.policy_ids) && item.policy_ids.length === 0);
}

function createPolicyDiv(item, index) {
    const policyDiv = document.createElement("div");
    policyDiv.classList.add("policy-container");

    const headerDiv = document.createElement("div");
    headerDiv.classList.add("policy-header");
    headerDiv.style.cursor = "pointer";

    const complianceIcon = document.createElement("div");
    complianceIcon.classList.add("compliance-icon");
    complianceIcon.classList.add(
        item.iscompliant === "yes"
            ? "compliant"
            : "non-compliant"
    );
    complianceIcon.title = isGeneralReview(item)
        ? (item.iscompliant === "yes" ? "No obvious issue identified" : "Potential contractual risk")
        : (item.iscompliant === "yes" ? "No company policy issue identified" : "Company policy issue");

    const title = document.createElement("span");
    title.classList.add("policy-title");
    title.textContent = item.title || `Review ${index + 1}`;

    const toggleMarker = document.createElement("span");
    toggleMarker.classList.add("toggle-marker");
    toggleMarker.textContent = "▼";

    headerDiv.appendChild(complianceIcon);
    headerDiv.appendChild(title);
    headerDiv.appendChild(toggleMarker);

    policyDiv.appendChild(headerDiv);

    const contentDiv = document.createElement("div");
    contentDiv.classList.add("policy-content");
    contentDiv.id = `policy-content-${index}`;
    contentDiv.style.display = "none";

    headerDiv.addEventListener("click", () => {
        const isHidden = contentDiv.style.display === "none";

        contentDiv.style.display = isHidden ? "block" : "none";
        toggleMarker.textContent = isHidden ? "▲" : "▼";
    });

    addPolicyDetails(contentDiv, item, index);
    policyDiv.appendChild(contentDiv);

    return policyDiv;
}


// ============================================================
// Add policy details
// ============================================================

function addPolicyDetails(contentDiv, item, index) {
    const general = isGeneralReview(item);
    const details = [
        {
            label: "Summary",
            value: item.summary
        },
        {
            label: general ? "Review Basis" : "Relevant Company Policy Item",
            value: general ? "General risk analysis. No matching company policy." : item.relevant_policy_item
        }
    ];

    if (item.iscompliant !== "yes") {
        details.push({
            label: "Suggested Correction",
            value: item.suggested_correction
        });

        details.push({
            label: general ? "Suggested Wording" : "Suggestion based on company knowledge base",
            value: ""
        });
    }

    if (Array.isArray(item.key_phrases) && item.key_phrases.length > 0) {
        details.push({
            label: "Key Phrases",
            value: item.key_phrases.join(", ")
        });
    }

    details.forEach((detail) => {
        const detailDiv = document.createElement("div");
        detailDiv.classList.add("policy-field");

        const detailTitle = document.createElement("div");
        detailTitle.classList.add("field-title");
        detailTitle.textContent = `${detail.label}:`;

        const detailValue = document.createElement("div");
        detailValue.textContent = String(detail.value ?? "");
        detailValue.style.whiteSpace = "pre-line";

        detailDiv.appendChild(detailTitle);
        detailDiv.appendChild(detailValue);
        contentDiv.appendChild(detailDiv);
    });

    if (item.iscompliant !== "yes") {
        addCarousel(contentDiv, item.corrected_text);
    }
}


// ============================================================
// Correction carousel
// ============================================================

function addCarousel(contentDiv, variations) {
    const items = Array.isArray(variations)
        ? variations.map((value) => String(value ?? ""))
        : typeof variations === "string"
            ? [variations]
            : [];

    if (items.length === 0) {
        const message = document.createElement("div");
        message.classList.add("warning");
        message.textContent =
            "No correction text was returned for this policy item.";

        contentDiv.appendChild(message);
        return;
    }

    let currentIndex = 0;

    const carouselDiv = document.createElement("div");
    carouselDiv.classList.add("carousel-container");

    const correctedTextDiv = document.createElement("div");
    correctedTextDiv.classList.add("carousel-text");

    const variationNumber = document.createElement("div");
    variationNumber.classList.add("variation-number");

    function renderCurrentVariation() {
        correctedTextDiv.textContent = items[currentIndex];

        variationNumber.textContent =
            `${currentIndex + 1}/${items.length}`;
    }

    const leftButton = document.createElement("button");
    leftButton.classList.add("carousel-button", "carousel-left");
    leftButton.textContent = "◀";
    leftButton.type = "button";

    leftButton.addEventListener("click", () => {
        if (currentIndex > 0) {
            currentIndex--;
            renderCurrentVariation();
        }
    });

    const rightButton = document.createElement("button");
    rightButton.classList.add("carousel-button", "carousel-right");
    rightButton.textContent = "▶";
    rightButton.type = "button";

    rightButton.addEventListener("click", () => {
        if (currentIndex < items.length - 1) {
            currentIndex++;
            renderCurrentVariation();
        }
    });

    carouselDiv.appendChild(leftButton);
    carouselDiv.appendChild(correctedTextDiv);
    carouselDiv.appendChild(rightButton);
    carouselDiv.appendChild(variationNumber);

    contentDiv.appendChild(carouselDiv);

    renderCurrentVariation();

    // Important: obtain the current value when clicked,
    // not the value from the initial carousel position.
    addCarouselButtons(contentDiv, () => items[currentIndex]);
}


// ============================================================
// Mark-up and Go To buttons
// ============================================================

function addCarouselButtons(contentDiv, getCurrentCorrection) {
    const perspective = reviewPerspective;
    const requestVersion = reviewRequestVersion;
    const fixButton = document.createElement("button");
    fixButton.textContent = "Mark-up";
    fixButton.classList.add("search-button");
    fixButton.type = "button";

    fixButton.addEventListener("click", async () => {
        if (requestVersion !== reviewRequestVersion || perspective !== getReviewPerspective()) {
            invalidateReview();
            return;
        }
        const correction = getCurrentCorrection();

        if (!correction || !correction.trim()) {
            console.warn("Mark-up: no correction text selected.");
            return;
        }

        await fixText(correction);
    });

    contentDiv.appendChild(fixButton);
    contentDiv.appendChild(document.createElement("p"));

    const gotoButton = document.createElement("button");
    gotoButton.textContent = "Go To";
    gotoButton.classList.add("search-button");
    gotoButton.type = "button";

    gotoButton.addEventListener("click", async () => {
        const correction = getCurrentCorrection();
        await gotoText(correction);
    });

    contentDiv.appendChild(gotoButton);
}


// ============================================================
// Replace the current Word selection with corrected text
// ============================================================

async function fixText(correctedText) {
    if (!correctedText || !correctedText.trim()) {
        console.warn("Mark-up: corrected text is empty.");
        return;
    }

    try {
        await Word.run(async (context) => {
            const selection = context.document.getSelection();

            selection.load("text");
            await context.sync();

            if (!selection.text) {
                throw new Error(
                    "No text is selected in Word. Please select the clause again."
                );
            }

            selection.insertText(
                correctedText,
                Word.InsertLocation.replace
            );

            await context.sync();

            console.log(
                "Mark-up completed. Replacement length:",
                correctedText.length
            );
        });
    } catch (error) {
        console.error("Mark-up failed:", error);
    }
}


// ============================================================
// Go To: find the full correction or original clause
// ============================================================

async function gotoText(correctedText = "") {
    const candidates = [
        correctedText,
        storedSelectedText
    ]
        .map((value) => String(value || "").trim())
        .filter((value, index, array) =>
            value.length > 0 && array.indexOf(value) === index
        );

    if (candidates.length === 0) {
        console.warn("Go To: no text available to search.");
        return;
    }

    try {
        await Word.run(async (context) => {
            const body = context.document.body;
            const options = {
                matchCase: false,
                ignorePunct: true
            };

            // First try to select the entire exact text.
            for (const candidate of candidates) {
                try {
                    const results = body.search(candidate, options);
                    results.load("text");
                    await context.sync();

                    if (results.items.length > 0) {
                        results.items[0].select();
                        await context.sync();

                        console.log(
                            "Go To selected full text:",
                            results.items[0].text.length,
                            "characters"
                        );
                        return;
                    }
                } catch (error) {
                    console.warn(
                        "Full-text search failed; trying text anchors.",
                        error
                    );
                }
            }

            // If an exact long or multi-paragraph search fails,
            // locate the opening and ending text and expand the range.
            for (const candidate of candidates) {
                if (candidate.length < 50) continue;

                const anchorLength = Math.min(
                    40,
                    Math.floor(candidate.length / 3)
                );

                const prefix = candidate.substring(0, anchorLength).trim();
                const suffix = candidate
                    .substring(candidate.length - anchorLength)
                    .trim();

                if (!prefix || !suffix || prefix === suffix) continue;

                try {
                    const prefixResults = body.search(prefix, options);
                    const suffixResults = body.search(suffix, options);

                    prefixResults.load("text");
                    suffixResults.load("text");

                    await context.sync();

                    if (
                        prefixResults.items.length > 0 &&
                        suffixResults.items.length > 0
                    ) {
                        const startRange = prefixResults.items[0];
                        const endRange =
                            suffixResults.items[suffixResults.items.length - 1];

                        const expandedRange = startRange.expandTo(endRange);

                        expandedRange.select();
                        await context.sync();

                        console.log(
                            "Go To selected expanded text range."
                        );
                        return;
                    }
                } catch (error) {
                    console.warn(
                        "Go To range expansion failed.",
                        error
                    );
                }
            }

            console.warn(
                "Go To could not find the complete corrected or original text."
            );
        });
    } catch (error) {
        console.error("Go To failed:", error);
    }
}


// ============================================================
// Toggle policy details
// ============================================================

function toggleContent(index) {
    const contentDiv =
        document.getElementById(`policy-content-${index}`);

    if (!contentDiv) return;

    contentDiv.style.display =
        contentDiv.style.display === "none"
            ? "block"
            : "none";
}


// ============================================================
// Insert corrected OOXML, retained for existing integrations
// ============================================================

function insertCorrectedText(correctedOoxml) {
    Office.context.document.setSelectedDataAsync(
        correctedOoxml,
        {
            coercionType: Office.CoercionType.Ooxml
        },
        (result) => {
            if (result.status === Office.AsyncResultStatus.Succeeded) {
                console.log("Corrected OOXML inserted successfully.");
                selectedOoxml = correctedOoxml;
            } else {
                console.error(
                    "OOXML insertion failed:",
                    result.error.message
                );
            }
        }
    );
}


// ============================================================
// Save the selected text's OOXML formatting
// ============================================================

function saveSelectedText() {
    Office.context.document.getSelectedDataAsync(
        Office.CoercionType.Ooxml,
        (result) => {
            if (result.status === Office.AsyncResultStatus.Succeeded) {
                selectedOoxml = result.value;
                console.log("Selected OOXML saved.");
            } else {
                console.error(
                    "Saving selected OOXML failed:",
                    result.error.message
                );
            }
        }
    );
}
