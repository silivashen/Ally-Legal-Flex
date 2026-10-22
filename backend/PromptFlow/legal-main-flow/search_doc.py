import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Optional

from promptflow.core import tool
from promptflow.connections import CustomConnection
from openai import OpenAI
from embedding_config_loader import get_embedding_config
from model_config_loader import find_local_config
from python_text_embedding import create_embeddings, validate_vector
from contract_index import CHUNK_VERSION, ensure_contract_index, requested_clause_chunks


def split_document(text, max_chars=1500):
    # Keep exact clause whitespace so Word can locate every returned passage.
    paragraphs = [paragraph.strip() for paragraph in re.split(r"[\r\n]+", text)
                  if paragraph.strip()]
    return [paragraph[start:start + max_chars].strip()
            for paragraph in paragraphs for start in range(0, len(paragraph), max_chars)
            if paragraph[start:start + max_chars].strip()]


def get_cache_directory():
    return find_local_config("model_config.json").parent / ".ally-vector-cache"


def cache_identity(document_text, config, dimensions, index_identity=""):
    metadata = {
        "document_sha256": hashlib.sha256(document_text.encode("utf-8")).hexdigest(),
        "base_url": config["base_url"],
        "model": config["model"],
        "dimensions": dimensions,
        "chunk_version": CHUNK_VERSION,
        "index_identity": index_identity,
    }
    return hashlib.sha256(json.dumps(metadata, sort_keys=True).encode("utf-8")).hexdigest()


def load_vectors(path, identity, count, dimensions):
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict) or cached.get("identity") != identity:
            return None
        vectors = cached.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != count:
            return None
        return [validate_vector(vector, dimensions) for vector in vectors]
    except (OSError, ValueError, TypeError):
        return None


def save_vectors(path, identity, vectors):
    """Use an atomic cache per exact contract index and model configuration."""
    temp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix="vectors-", suffix=".tmp", dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"identity": identity, "vectors": vectors}, stream, allow_nan=False)
        os.replace(temp_name, path)
    except OSError:
        # A cache is optional: a read-only mount must not prevent document questions.
        pass
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def cosine_similarity(first, second):
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    return sum((left / first_norm) * (right / second_norm)
               for left, right in zip(first, second))


@tool
def search_doc_tool(query: str, document_text: str, ally: CustomConnection,
                    document_paragraphs: Optional[list] = None, filename: str = "") -> object:
    if not isinstance(document_text, str) or not document_text.strip():
        raise ValueError("未收到当前 Word 文档正文，请打开有正文的合同后重试。")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("请先输入合同问题。")
    record = ensure_contract_index(document_text, document_paragraphs,
                                   get_cache_directory().parent / ".ally-contract-index")
    chunks = record["chunks"]
    if not chunks:
        raise ValueError("当前 Word 文档没有可读取的正文。")

    # Query and clauses share a configuration snapshot even if settings change mid-call.
    config = get_embedding_config(ally)
    client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
    question_vector = create_embeddings(client, config["model"], [query])[0]
    dimensions = len(question_vector)
    identity = cache_identity(document_text, config, dimensions, record["identity"])
    cache_path = get_cache_directory() / (identity + ".json")
    vectors = load_vectors(cache_path, identity, len(chunks), dimensions)
    if vectors is None:
        vectors = []
        for start in range(0, len(chunks), 32):
            vectors.extend(create_embeddings(client, config["model"],
                                             [chunk["paragraph"] for chunk in chunks[start:start + 32]], dimensions))
        save_vectors(cache_path, identity, vectors)

    ranked = sorted(enumerate(chunks),
                    key=lambda item: (-cosine_similarity(question_vector, vectors[item[0]]), item[0]))
    requested = requested_clause_chunks(record, query)
    requested_ids = {chunk["source_id"] for chunk in requested}
    # Preserve semantic retrieval, while retaining every explicitly named clause chunk.
    selected = requested + [chunk for _position, chunk in ranked
                            if chunk["source_id"] not in requested_ids][:max(0, 8 - len(requested))]
    return [{"source_id": chunk["source_id"], "title": chunk["paragraph"][:120],
             "paragraph": chunk["paragraph"], "summary": chunk["paragraph"], "keyphrases": []}
            for chunk in selected]
