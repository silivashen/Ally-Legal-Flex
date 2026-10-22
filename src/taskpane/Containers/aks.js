import { readWordDocument, documentRequestFields } from "../../shared/word-document.js";
import { resolveLocalEndpoint } from "../../shared/local-endpoint.js";
import { getReviewPerspective, onReviewPerspectiveChange, appendReviewPerspective, validateReviewPerspective, validateReviewPerspectiveInputs } from "../../shared/review-perspective.js";

let askRequestVersion = 0;
let askPerspective = null;
let lastAskQuery = "";

onReviewPerspectiveChange(() => {
    if (askPerspective === null || askPerspective === getReviewPerspective()) return;
    const query = document.getElementById("ask-input")?.value ?? lastAskQuery;
    resetPolicyContainer();
    const input = document.getElementById("ask-input");
    if (input) input.value = query;
    showAskMessage("Review perspective changed. Ask again to use the current perspective.");
});

// ============================================================
// Ally Ask - Answer questions about the CURRENT Word document
// ============================================================

// Ask a question about the document currently open in Word.
export async function ask() {
    const container = document.getElementById("ask-container");
    const input = document.getElementById("ask-input");

    if (!container || !input) {
        console.error("Ask failed: input or container not found.");
        return;
    }

    const query = String(input.value || "").trim();

    if (!query) {
        input.focus();
        showAskMessage("Please enter a question.");
        return;
    }

    const endpoint = resolveLocalEndpoint(localStorage.getItem("pfendpoint"));
    const language = localStorage.getItem("language") || "Chinese";

    if (!endpoint) {
        showAskMessage("Backend endpoint is missing. Check Ally Legal Flex configuration.");
        return;
    }

    if (!validateReviewPerspectiveInputs()) return;
    const reviewPerspective = getReviewPerspective();
    const requestVersion = ++askRequestVersion;
    askPerspective = reviewPerspective;
    lastAskQuery = query;
    const isCurrentRequest = () => requestVersion === askRequestVersion &&
        reviewPerspective === getReviewPerspective();

    // Read the user's group IDs.
    let groups = [];

    try {
        const savedGroups = localStorage.getItem("groups");
        const parsedGroups = savedGroups
            ? JSON.parse(savedGroups)
            : [];

        groups = Array.isArray(parsedGroups) ? parsedGroups : [];
    } catch (error) {
        console.warn("Could not read user groups:", error);
    }

    // Render the question and loading indicator.
    container.innerHTML = "";

    const questionHeader = document.createElement("h3");
    questionHeader.classList.add("question-header");
    questionHeader.textContent = `Question: ${query}`;
    container.appendChild(questionHeader);

    const spinner = createSpinner();
    container.appendChild(spinner);

    try {
        // Step 1: Read the actual Word document currently open.
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

        // Step 2: Send the question and current document to the backend.
        const response = await fetchData(
            endpoint,
            query,
            language,
            groups,
            documentSnapshot,
            reviewPerspective
        );

        const responseText = await response.text();
        if (!isCurrentRequest()) return;

        let data;

        try {
            data = responseText ? JSON.parse(responseText) : {};
        } catch (error) {
            throw new Error(
                `Backend returned invalid JSON (HTTP ${response.status}). Please try again.`
            );
        }

        console.log("Ask HTTP status:", response.status);
        throwIfBackendError(data);

        if (!response.ok) {
            throw new Error(
                `Backend HTTP ${response.status}. Please try again.`
            );
        }

        // Support responses where the answer is an object or JSON string.
        let answerData = data?.answer ?? data;

        if (typeof answerData === "string") {
            try {
                answerData = JSON.parse(answerData);
            } catch (error) {
                throw new Error(
                    "The backend returned an unexpected answer. Please try again."
                );
            }
        }

        throwIfBackendError(answerData);

        // Some backends wrap the actual answer in another "answer" field.
        if (
            answerData &&
            typeof answerData === "object" &&
            answerData.answer &&
            !answerData.Answer
        ) {
            let nestedAnswer = answerData.answer;

            if (typeof nestedAnswer === "string") {
                try {
                    nestedAnswer = JSON.parse(nestedAnswer);
                } catch (error) {
                    // Preserve the string if it is ordinary answer text.
                    nestedAnswer = { Answer: nestedAnswer };
                }
            }

            answerData = nestedAnswer;
        }

        throwIfBackendError(answerData);

        if (
            !answerData ||
            typeof answerData !== "object" ||
            !("Answer" in answerData)
        ) {
            throw new Error(
                "The backend returned an unexpected answer structure. Please try again."
            );
        }

        if (typeof answerData.Answer !== "string" || !answerData.Answer.trim()) {
            throw new Error("The backend did not provide an answer. Please try again.");
        }

        // Step 3: Display the answer.
        validateReviewPerspective(answerData, reviewPerspective);
        displaySearchResults(answerData, query, reviewPerspective);

    } catch (error) {
        if (!isCurrentRequest()) return;
        console.error("Ask failed; see the error in the task pane.");

        displayAskError(
            error?.message || String(error),
            query
        );
    }
}

function throwIfBackendError(data) {
    if (!data || typeof data !== "object" || !data.error) return;

    const message = typeof data.error === "string"
        ? data.error
        : data.error.message;
    throw new Error(message || "The backend could not answer this question. Please try again.");
}


// ============================================================
// Send the current document and question to PromptFlow
// ============================================================

async function fetchData(
    endpoint,
    query,
    language,
    groups,
    documentSnapshot,
    reviewPerspective
) {
    const payload = {
        query_type: 3,
        question: query,
        ...documentRequestFields(documentSnapshot),
        language: language,
        group: groups,
        reviewPerspective
    };

    console.log("Sending Ask request:", {
        documentLength: documentSnapshot.text.length,
        language: language
    });

    return fetch(endpoint, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });
}


// ============================================================
// Loading spinner
// ============================================================

function createSpinner() {
    const spinner = document.createElement("div");
    spinner.id = "ask-spinner";
    spinner.classList.add("spinner");
    spinner.style.display = "block";

    return spinner;
}


// ============================================================
// Display an error and allow the user to retry
// ============================================================

function displayAskError(message, query = "") {
    resetPolicyContainer();

    const container = document.getElementById("ask-container");
    const input = document.getElementById("ask-input");

    if (!container) {
        console.error("Cannot display Ask error: container not found.");
        return;
    }

    if (input) {
        input.value = query;
    }

    const warning = document.createElement("div");
    warning.classList.add("warning");
    warning.textContent = "Ask failed: " + message;

    if (input) {
        container.insertBefore(warning, input);
    } else {
        container.appendChild(warning);
    }
}


// Display a simple message before another request is made.
function showAskMessage(message) {
    const container = document.getElementById("ask-container");

    if (!container) {
        console.error(message);
        return;
    }

    let warning = document.getElementById("ask-validation-error");

    if (!warning) {
        warning = document.createElement("div");
        warning.id = "ask-validation-error";
        warning.classList.add("warning");

        const input = document.getElementById("ask-input");

        if (input) {
            container.insertBefore(warning, input);
        } else {
            container.appendChild(warning);
        }
    }

    warning.textContent = message;
}


// ============================================================
// Display the answer and related passages
// ============================================================

function displaySearchResults(data, query = "", reviewPerspective = "") {
    const container = document.getElementById("ask-container");

    if (!container) {
        console.error("Cannot display Ask results: container not found.");
        return;
    }

    container.innerHTML = "";
    appendReviewPerspective(container, reviewPerspective);

    if (query) {
        const questionHeader = document.createElement("h3");
        questionHeader.classList.add("question-header");
        questionHeader.textContent = `Question: ${query}`;

        container.appendChild(questionHeader);
    }

    if (!data || typeof data !== "object") {
        throw new Error("The backend did not return a valid answer object.");
    }

    const answerHeader = createHeader();
    container.appendChild(answerHeader);

    const answerText =
        data.Answer ??
        data.answer ??
        "The backend did not provide an answer.";

    const answerDiv = createAnswerDiv(answerText);
    container.appendChild(answerDiv);

    const searchResults = Array.isArray(data.SearchResults)
        ? data.SearchResults
        : Array.isArray(data.searchResults)
            ? data.searchResults
            : [];

    if (searchResults.length > 0) {
        const resultsDiv = createResultsDiv(searchResults);
        container.appendChild(resultsDiv);
    }

    const tryAgainButton = createTryAgainButton();
    container.appendChild(tryAgainButton);
}


// ============================================================
// Answer heading
// ============================================================

function createHeader() {
    const header = document.createElement("h2");

    header.textContent = "▼ Answer";
    header.id = "ask-answer-header";

    header.addEventListener("click", showhideAnswer);

    return header;
}


// ============================================================
// Answer text
// ============================================================

function createAnswerDiv(answer) {
    const answerDiv = document.createElement("div");
    answerDiv.classList.add("ask-answer-container");

    const answerContent = document.createElement("p");
    answerContent.textContent = String(answer ?? "");

    answerDiv.appendChild(answerContent);

    return answerDiv;
}


// ============================================================
// Relevant clauses list
// ============================================================

function createResultsDiv(results) {
    const resultsDiv = document.createElement("div");
    resultsDiv.classList.add("ask-results-container");

    const resultsTitle = document.createElement("h3");
    resultsTitle.textContent = "Relevant Clauses:";
    resultsTitle.id = "ask-results-title";
    resultsTitle.classList.add("ask-results-title");

    resultsDiv.appendChild(resultsTitle);

    results.forEach((result) => {
        const resultItem = createResultItem(result);
        resultsDiv.appendChild(resultItem);
    });

    return resultsDiv;
}


// ============================================================
// Individual clause
// ============================================================

function createResultItem(result) {
    const resultItem = document.createElement("div");
    resultItem.classList.add("result-item");

    const title =
        result?.title ||
        result?.paragraph ||
        "Untitled clause";

    resultItem.textContent = title;

    const additionalLine = document.createElement("p");
    additionalLine.classList.add("result-description");
    additionalLine.textContent = result?.summary || "";

    const keyphrases = Array.isArray(result?.keyphrases)
        ? result.keyphrases
        : [];

    const keyItemsTagsDiv = createKeyItemsTagsDiv(keyphrases);

    resultItem.addEventListener("click", () => {
        const searchText = result?.paragraph || title;

        if (searchText) {
            findInDocument(searchText);
        }
    });

    resultItem.appendChild(additionalLine);
    resultItem.appendChild(keyItemsTagsDiv);

    return resultItem;
}


// ============================================================
// Key phrase tags
// ============================================================

function createKeyItemsTagsDiv(keyphrases) {
    const keyItemsTagsDiv = document.createElement("div");
    keyItemsTagsDiv.classList.add("key-items");

    const items = Array.isArray(keyphrases) ? keyphrases : [];

    items.forEach((keyItem) => {
        const tag = document.createElement("span");
        tag.classList.add("key-item");
        tag.textContent = String(keyItem);

        keyItemsTagsDiv.appendChild(tag);
    });

    return keyItemsTagsDiv;
}


// ============================================================
// Search Again button
// ============================================================

function createTryAgainButton() {
    const tryAgainButton = document.createElement("button");

    tryAgainButton.classList.add("search-button");
    tryAgainButton.textContent = "Search Again";

    tryAgainButton.addEventListener("click", resetPolicyContainer);

    return tryAgainButton;
}


// ============================================================
// Restore the initial Ask interface
// ============================================================

function resetPolicyContainer() {
    askRequestVersion += 1;
    askPerspective = null;
    const container = document.getElementById("ask-container");

    if (!container) {
        console.error("Cannot reset Ask: container not found.");
        return;
    }

    container.innerHTML = `
        <h2>Ask</h2>
        <p>Chat with your contract to uncover the general meaning of the various provisions</p>
        <div id="ask-spinner" style="display: none;" class="spinner"></div>
        <input
            type="text"
            class="search-input"
            id="ask-input"
            name="search"
            placeholder="Write your question"
        >
        <button
            type="button"
            class="ms-Button ms-Button--primary search-button"
            id="ask-button"
        >
            <span class="ms-Button-label">Ask on the contract</span>
        </button>
    `;

    const button = document.getElementById("ask-button");

    if (button) {
        button.addEventListener("click", ask);
    }
}


// ============================================================
// Expand or collapse the answer and relevant clauses
// ============================================================

function showhideAnswer() {
    const header = document.getElementById("ask-answer-header");
    const answerDiv = document.querySelector(".ask-answer-container");
    const resultsDiv = document.querySelector(".ask-results-container");

    if (!header || !answerDiv) {
        console.error("Answer elements not found.");
        return;
    }

    const isVisible = answerDiv.style.display !== "none";

    answerDiv.style.display = isVisible ? "none" : "block";

    if (resultsDiv) {
        resultsDiv.style.display = isVisible ? "none" : "block";
    }

    header.textContent = isVisible ? "► Answer" : "▼ Answer";
}


// ============================================================
// Find and select matching text in the current Word document
// ============================================================

function findInDocument(text) {
    if (!text) {
        return;
    }

    Word.run(async (context) => {
        const searchResults = context.document.body.search(text, {
            ignorePunct: true
        });

        searchResults.load("text");
        await context.sync();

        console.log(
            "Found matching passages in Word:",
            searchResults.items.length
        );

        if (searchResults.items.length > 0) {
            searchResults.items[0].select();
            await context.sync();
        } else {
            console.log("Text not found in the current Word document.");
        }
    }).catch((error) => {
        console.error("Find in document failed.");
    });
}
