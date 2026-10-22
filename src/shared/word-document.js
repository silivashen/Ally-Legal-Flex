// Read document text and original list labels for automatic indexing.
// Raw paragraph text and automatic list labels stay separate; neither is renumbered.

function requireWordParagraphSupport() {
    if (typeof Office === "undefined" ||
        !Office.context?.requirements?.isSetSupported("WordApi", "1.3")) {
        throw new Error("This feature needs Word API 1.3 or later to read the original clause numbers. Please update Word.");
    }
}

async function snapshotHash(text, paragraphs) {
    if (!globalThis.crypto?.subtle) throw new Error("Document fingerprinting is unavailable. Please reload the add-in.");
    const data = new TextEncoder().encode(JSON.stringify({ text, paragraphs }));
    const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
    return "sha256-" + Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
}

async function readSnapshotInContext(context) {
    const body = context.document.body;
    const collection = body.paragraphs;
    body.load("text");
    collection.load("items/text,items/isListItem");
    await context.sync();
    const listItems = collection.items.filter(paragraph => paragraph.isListItem);
    listItems.forEach(paragraph => paragraph.listItem.load("listString"));
    if (listItems.length) await context.sync();
    const text = String(body.text || "");
    if (!text.trim()) throw new Error("The current Word document contains no readable text.");
    const paragraphs = collection.items.map((paragraph, index) => ({
        index,
        text: String(paragraph.text || ""),
        list_label: paragraph.isListItem ? String(paragraph.listItem.listString || "") : ""
    }));
    return { snapshot: { text, paragraphs, documentId: await snapshotHash(text, paragraphs) }, collection };
}

export async function readWordDocument({ captureSelection = false } = {}) {
    requireWordParagraphSupport();
    return Word.run(async context => {
        const selection = captureSelection ? context.document.getSelection() : null;
        if (selection) selection.load("text");
        const { snapshot } = await readSnapshotInContext(context);
        if (selection) snapshot.selectionText = String(selection.text || "");
        return snapshot;
    });
}

export function documentRequestFields(snapshot) {
    return { filename: snapshot.documentId, document_text: snapshot.text, document_paragraphs: snapshot.paragraphs };
}
