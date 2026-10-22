"""Local, content-addressed contract chunks and verified original-clause citations.

This module has no model or PromptFlow dependency. Text offsets are Python Unicode
character offsets in the exact submitted document, never Word range offsets.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


SCHEMA_VERSION = 1
CHUNK_VERSION = "original-paragraph-1500-v2"
MAX_CHARS = 1500
CHUNK_FIELDS = ("source_id", "paragraph", "start", "end", "paragraph_start",
                "paragraph_end", "clause_number")
NUMBER_PATTERNS = [
    re.compile(r"^(第[〇零一二三四五六七八九十百千万两\d]+[条款章])"),
    re.compile(r"^((?:Article|Section|Clause)\s+(?:\d+(?:\.\d+)*|[IVXLCDM]+)(?:\([a-z0-9]+\))*)(?=$|[\s:：–—-]|\.(?!\d))", re.I),
    re.compile(r"^(\d+(?:\.\d+)+(?:[.．、)）])?)(?![\d.%％‰])(?=$|[\s：:]|[\u4e00-\u9fff])"),
    re.compile(r"^(\d+[.．、)）])(?=$|[^\d])"),
    re.compile(r"^([（(](?:\d+|[a-zA-Z]|[ivxlcdmIVXLCDM]+|[一二三四五六七八九十百]+)[)）])"),
    re.compile(r"^([一二三四五六七八九十百]+、)"),
    re.compile(r"^((?:[ivxlcdmIVXLCDM]+|[A-Za-z])[.)])(?=$|\s)"),
]

CLAUSE_NUMERALS = r"[〇零一二三四五六七八九十百千万两\d]+"
CLAUSE_QUESTION = re.compile(r"第\s*(" + CLAUSE_NUMERALS + r")\s*条")


def _integer_clause_number(value):
    if value.isdecimal():
        return int(value)
    digits = dict(zip("〇零一二三四五六七八九两", (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 2)))
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = section = digit = 0
    for character in value:
        if character in digits:
            digit = digits[character]
        elif character in units:
            unit = units[character]
            if unit == 10000:
                total += (section + digit or 1) * unit
                section = 0
            else:
                section += (digit or 1) * unit
            digit = 0
        else:
            return None
    return total + section + digit


def requested_clause_chunks(record, query):
    """Match explicit clause references to original labels, never paragraph order."""
    requested = {_integer_clause_number(match.group(1)): match.group(0)
                 for match in CLAUSE_QUESTION.finditer(query)}
    requested.pop(None, None)
    if not requested:
        return []
    labeled = []
    for chunk in record["chunks"]:
        label = chunk["clause_number"]
        explicit = (re.fullmatch(r"第(" + CLAUSE_NUMERALS + r")条", label)
                    or re.fullmatch(r"(?:Article|Section|Clause)\s+(\d+)", label, re.I))
        enumeration = re.fullmatch(r"(" + CLAUSE_NUMERALS + r")[、.．]?", label)
        style = "explicit" if explicit else ""
        match = explicit or enumeration
        if enumeration and not explicit:
            style = "arabic" if enumeration.group(1).isdecimal() else "chinese"
        number = _integer_clause_number(match.group(1)) if match else None
        labeled.append((chunk, style, number))
    has_explicit = any(style == "explicit" for _, style, _ in labeled)
    results = []
    active = None
    for chunk, style, number in labeled:
        if active:
            active_style, active_number, _reference = active
            sibling = style == active_style and number != active_number
            higher = style == "explicit" and active_style != "explicit"
            chapter = re.fullmatch(r"第" + CLAUSE_NUMERALS + r"章", chunk["clause_number"])
            decimal = re.match(r"^(\d+)\.\d", chunk["clause_number"])
            different_parent = active_style == "arabic" and decimal and int(decimal.group(1)) != active_number
            if sibling or higher or chapter or different_parent:
                active = None
        if number is not None and number in requested and (style == "explicit" or not has_explicit):
            active = (style, number, requested[number])
        if active:
            results.append(dict(chunk, requested_as=active[2]))
    return results


def default_cache_directory():
    directory = Path(__file__).resolve().parent
    for parent in directory.parents:
        if (parent / "package.json").is_file() and (parent / "src").is_dir():
            directory = parent
            break
    return directory / ".ally-contract-index"


def _cache_directory(cache_dir):
    return Path(cache_dir) if cache_dir is not None else default_cache_directory()


def _is_gap(text):
    # Word can put a cell marker between table paragraphs; do not change source offsets.
    return not text.replace("\u0007", "").strip()


def _number(text, list_label=""):
    # Recognize numbered automatic lists conservatively; arbitrary bullets are not numbers.
    if list_label:
        if re.fullmatch(r"\d+|[一二三四五六七八九十百]+", list_label):
            return list_label
        for pattern in NUMBER_PATTERNS:
            match = pattern.match(list_label)
            if match and match.group(1) == list_label:
                return list_label
    date = re.match(r"^\d{4}\.(\d{1,2})\.(\d{1,2})(?=$|[^\d.])", text)
    if date and 1 <= int(date.group(1)) <= 12 and 1 <= int(date.group(2)) <= 31:
        return ""
    for pattern in NUMBER_PATTERNS:
        match = pattern.match(text)
        if match:
            # Only bare decimal labels are ambiguous amounts; explicit heading markers win.
            label = match.group(1)
            suffix = text[match.end():].lstrip()
            if re.fullmatch(r"\d+(?:\.\d+)+", label) and re.match(
                r"^(?:[万亿]?(?:元|美元|欧元)|人民币|[%％‰]|倍|公斤|千克|吨|厘米|毫米|米|毫升|升|"
                r"(?:USD|EUR|CNY|RMB|kg|cm|mm|ml|g|m|l|hundred|thousand|million|billion|trillion)\b)", suffix, re.I,
            ):
                continue
            return label
    return ""


def _text_segments(text, offset=0, index=None, list_label=""):
    segments = []
    for match in re.finditer(r"[^\r\n]+", text):
        raw = match.group()
        value = raw.strip()
        if not value:
            continue
        start = offset + match.start() + len(raw) - len(raw.lstrip())
        segments.append({"index": index, "start": start, "end": start + len(value),
                         "text": value, "list_label": list_label if not segments else ""})
    return segments


def normalize_paragraphs(document_text, document_paragraphs=None):
    if not isinstance(document_text, str) or not document_text.strip():
        raise ValueError("The current Word document contains no readable text.")
    if document_paragraphs is None or document_paragraphs == []:
        return _text_segments(document_text)
    if not isinstance(document_paragraphs, list):
        raise ValueError("document_paragraphs must be a list of Word paragraphs.")
    segments = []
    cursor = 0
    previous_index = -1
    for paragraph in document_paragraphs:
        if not isinstance(paragraph, dict):
            raise ValueError("Word paragraph metadata is invalid.")
        index = paragraph.get("index")
        raw_text = paragraph.get("text")
        label = paragraph.get("list_label", "")
        if (isinstance(index, bool) or not isinstance(index, int) or index <= previous_index
                or not isinstance(raw_text, str) or not isinstance(label, str)
                or len(label) > 128 or any(ord(char) < 32 for char in label)):
            raise ValueError("Word paragraph metadata is invalid.")
        previous_index = index
        value = raw_text.strip()
        if not value:
            continue
        start = document_text.find(value, cursor)
        if start < 0 or not _is_gap(document_text[cursor:start]):
            raise ValueError("Word paragraph metadata does not match the current document. Refresh and retry.")
        segments.extend(_text_segments(value, start, index, label.strip()))
        cursor = start + len(value)
    if not _is_gap(document_text[cursor:]) or not segments:
        raise ValueError("Word paragraph metadata does not cover the current document. Refresh and retry.")
    return segments


def _identity(document_text, paragraphs):
    data = {"schema_version": SCHEMA_VERSION, "chunk_version": CHUNK_VERSION,
            "text": document_text, "paragraphs": paragraphs}
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _labeled_paragraphs(paragraphs):
    result = []
    current = ""
    group = -1
    for paragraph in paragraphs:
        label = _number(paragraph["text"], paragraph["list_label"])
        if label or group < 0:
            current = label
            group += 1
        result.append(dict(paragraph, clause_number=current, group=group))
    return result


def _span_metadata(paragraphs, start, end):
    matches = [paragraph for paragraph in paragraphs
               if paragraph["start"] < end and paragraph["end"] > start]
    return {"paragraph_start": matches[0]["index"], "paragraph_end": matches[-1]["index"],
            "clause_number": matches[0]["clause_number"]} if matches else None


def build_chunks(document_text, paragraphs):
    chunks = []
    for paragraph in _labeled_paragraphs(paragraphs):
        for position in range(paragraph["start"], paragraph["end"], MAX_CHARS):
            raw = document_text[position:min(position + MAX_CHARS, paragraph["end"])]
            value = raw.strip()
            if not value:
                continue
            start = position + len(raw) - len(raw.lstrip())
            end = start + len(value)
            metadata = _span_metadata([paragraph], start, end)
            if metadata is None:
                continue
            chunks.append({"source_id": len(chunks), "paragraph": value,
                           "start": start, "end": end, **metadata})
    return chunks


def _read_record(path, identity, document_text, paragraphs):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("identity") != identity
                or record.get("schema_version") != SCHEMA_VERSION
                or record.get("chunk_version") != CHUNK_VERSION
                or record.get("text") != document_text or record.get("paragraphs") != paragraphs):
            return None
        chunks = record.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            return None
        labeled = _labeled_paragraphs(paragraphs)
        cursor = 0
        for source_id, chunk in enumerate(chunks):
            if not isinstance(chunk, dict) or set(chunk) != set(CHUNK_FIELDS):
                return None
            start, end = chunk.get("start"), chunk.get("end")
            if (type(start) is not int or type(end) is not int
                    or not cursor <= start < end <= len(document_text)
                    or end - start > MAX_CHARS or not _is_gap(document_text[cursor:start])
                    or type(chunk.get("source_id")) is not int or chunk["source_id"] != source_id
                    or chunk.get("paragraph") != document_text[start:end]):
                return None
            expected = _span_metadata(labeled, start, end)
            covered = [p for p in labeled if p["start"] < end and p["end"] > start]
            if (expected is None or any(chunk.get(key) != value for key, value in expected.items())
                    or len(covered) != 1):
                return None
            cursor = end
        return record if _is_gap(document_text[cursor:]) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="contract-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def ensure_contract_index(document_text, document_paragraphs=None, cache_dir=None):
    """Reuse only a verified index of this exact text and numbering snapshot."""
    paragraphs = normalize_paragraphs(document_text, document_paragraphs)
    identity = _identity(document_text, paragraphs)
    path = _cache_directory(cache_dir) / (identity + ".json")
    record = _read_record(path, identity, document_text, paragraphs)
    if record is not None:
        return record
    record = {"schema_version": SCHEMA_VERSION, "chunk_version": CHUNK_VERSION,
              "identity": identity, "text": document_text, "paragraphs": paragraphs,
              "chunks": build_chunks(document_text, paragraphs)}
    _write_atomic(path, record)
    return record


def index_context(record):
    """Expose only trusted chunks; source_id is never a contract clause number."""
    return [{field: chunk[field] for field in CHUNK_FIELDS} for chunk in record["chunks"]]


def model_index_context(record):
    """Numbering and exact offsets without duplicating the full contract in prompts."""
    fields = ("source_id", "start", "end", "paragraph_start", "paragraph_end", "clause_number")
    return [dict({field: chunk[field] for field in fields}, anchor=chunk["paragraph"][:120])
            for chunk in record["chunks"]]


def citations_for_text(record, source_text):
    """Return all possible exact-source citations, marking non-unique text explicitly."""
    if not isinstance(source_text, str) or not source_text.strip():
        return []
    text = record["text"]
    occurrences = []
    cursor = 0
    while True:
        start = text.find(source_text, cursor)
        if start < 0:
            break
        occurrences.append((start, start + len(source_text)))
        cursor = start + 1
    return [dict(chunk, ambiguous=len(occurrences) > 1) for chunk in index_context(record)
            if any(chunk["start"] < end and chunk["end"] > start for start, end in occurrences)]


def _document_pointer(cache_dir, filename):
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Document ID is required.")
    key = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    return cache_dir / "documents" / (key + ".json")


def index_document(filename, document_text, document_paragraphs=None, cache_dir=None):
    """Compatibility entry point; never overwrite the old full-text index file."""
    directory = _cache_directory(cache_dir)
    pointer = _document_pointer(directory, filename)
    record = ensure_contract_index(document_text, document_paragraphs, directory)
    _write_atomic(pointer, {"identity": record["identity"]})
    return {"Indexed": True, "DocumentId": filename, "Characters": len(document_text),
            "Chunks": len(record["chunks"]), "IndexId": record["identity"]}


def check_contract_index(filename, document_text="", document_paragraphs=None,
                         cache_dir=None, legacy_path=None):
    directory = _cache_directory(cache_dir)
    if document_text:
        paragraphs = normalize_paragraphs(document_text, document_paragraphs)
        identity = _identity(document_text, paragraphs)
        record = _read_record(directory / (identity + ".json"), identity, document_text, paragraphs)
        if record is not None:
            return {"Found": True, "Status": "current", "Chunks": len(record["chunks"])}
    if filename and _document_pointer(directory, filename).is_file():
        return {"Found": False, "Status": "stale" if document_text else "unverified", "Chunks": 0}
    legacy = Path(legacy_path) if legacy_path is not None else directory.parent / "contract_index.json"
    try:
        previous = json.loads(legacy.read_text(encoding="utf-8-sig"))
        if isinstance(previous, dict) and filename and filename in previous:
            return {"Found": False, "Status": "legacy", "Chunks": 0}
    except (OSError, ValueError, TypeError):
        pass
    return {"Found": False, "Status": "missing", "Chunks": 0}
