from promptflow.core import tool
from promptflow.connections import CustomConnection
from openai import OpenAI
from embedding_config_loader import get_embedding_config
from model_config_loader import find_local_config
import hashlib
import json
import math


def find_policy_file():
    return find_local_config("policy.json")


def load_policies(policy_file):
    with policy_file.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = data.get("value", [])

    if not isinstance(data, list):
        raise ValueError("policy.json must contain a list of policies.")

    return data


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def group_is_allowed(
    policy,
    groups
):
    # Groups are custom labels only.
    # Do not filter policies by groups.
    return True

def get_policy_embeddings(policies, client, model, cache_path, config_fingerprint=""):
    # Fingerprint the actual rule content so edits invalidate the cache.
    payload = [
        {
            "id": p.get("id"),
            "title": p.get("title", ""),
            "instruction": p.get("instruction", ""),
            "policySet": p.get("policySet", ""),
        }
        for p in policies
    ]
    fingerprint = hashlib.sha256(
        (json.dumps(payload, ensure_ascii=False, sort_keys=True) + config_fingerprint).encode("utf-8")
    ).hexdigest()

    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                embeddings = cached.get("embeddings", {})
                if all(str(i) in embeddings for i in range(len(policies))):
                    return embeddings
        except (OSError, ValueError, TypeError):
            pass

    embeddings = {}
    for start in range(0, len(policies), 32):
        batch = policies[start:start + 32]
        texts = [
            (str(p.get("title", "")) + "\n" + str(p.get("instruction", ""))).strip()
            for p in batch
        ]
        response = client.embeddings.create(model=model, input=texts)
        for item in response.data:
            embeddings[str(start + item.index)] = item.embedding

    cache_path.write_text(
        json.dumps(
            {"fingerprint": fingerprint, "embeddings": embeddings},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return embeddings


@tool
def list_policy_tool(
    query: str,
    embeding: list,
    searchconnection: CustomConnection,
    groups: list,
    policySets: list,
) -> object:
    selected_sets = [
        str(x).strip() for x in (policySets or [])
        if str(x).strip()
    ]
    if not selected_sets:
        print("No Policy Set selected; refusing to run review.")
        return []

    policy_file = find_policy_file()
    policies = load_policies(policy_file)

    # Filter Policy Set BEFORE semantic ranking.
    candidates = [
        p for p in policies
        if str(p.get("policySet", "General Policies")).strip() in selected_sets
        and group_is_allowed(p, groups or [])
    ]

    if not candidates:
        print(
            f"No policies matched policySets={selected_sets}; "
            f"groups={groups or []}"
        )
        return []

    config = get_embedding_config(searchconnection)
    client = OpenAI(
        base_url=config["base_url"],
        api_key=config["api_key"],
    )
    model = config["model"]

    # Cache identity includes endpoint and model.
    cache_path = policy_file.parent / "local_embedding_policy_embeddings.json"
    config_fingerprint = config["base_url"] + "|" + model
    all_embeddings = get_policy_embeddings(
        policies, client, model, cache_path, config_fingerprint
    )

    original_indexes = {id(p): i for i, p in enumerate(policies)}
    ranked = []
    for policy in candidates:
        idx = original_indexes[id(policy)]
        vector = all_embeddings.get(str(idx), [])
        score = cosine_similarity(embeding or [], vector)
        ranked.append((score, policy))

    ranked.sort(key=lambda item: item[0], reverse=True)

    result = [
        {
            "id": p.get("id"),
            "title": p.get("title", ""),
            "instruction": p.get("instruction", ""),
            "policySet": p.get("policySet"),
            "severity": p.get("severity"),
        }
        for score, p in ranked
    ]

    print(
        f"Local policy search: {len(result)} rules; "
        f"selected sets={selected_sets}; "
        f"matched titles={[p['title'] for p in result]}"
    )
    return result
