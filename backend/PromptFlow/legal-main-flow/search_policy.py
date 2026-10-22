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


def group_is_allowed(policy, groups):
    # Policy Sets are independent from permission groups.
    # Keep existing behavior: groups do not filter policies.
    return True


def get_policy_embeddings(
    policies,
    client,
    model,
    cache_path,
    config_fingerprint="",
):
    # Fingerprint the rule content so edits invalidate the cache.
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
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            )
            + config_fingerprint
        ).encode("utf-8")
    ).hexdigest()

    if cache_path.is_file():
        try:
            cached = json.loads(
                cache_path.read_text(encoding="utf-8")
            )

            if cached.get("fingerprint") == fingerprint:
                embeddings = cached.get("embeddings", {})

                if all(
                    str(i) in embeddings
                    for i in range(len(policies))
                ):
                    return embeddings

        except (OSError, ValueError, TypeError):
            pass

    embeddings = {}

    for start in range(0, len(policies), 32):
        batch = policies[start:start + 32]

        texts = [
            (
                str(p.get("title", ""))
                + "\n"
                + str(p.get("instruction", ""))
            ).strip()
            for p in batch
        ]

        response = client.embeddings.create(
            model=model,
            input=texts,
        )

        for item in response.data:
            embeddings[str(start + item.index)] = item.embedding

    cache_path.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "embeddings": embeddings,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return embeddings


def get_severity_label(severity):
    # Accept integer values and numeric strings from policy.json.
    try:
        severity_number = int(severity)
    except (TypeError, ValueError):
        return "Unknown"

    severity_labels = {
        1: "Critical",
        2: "Warning",
        3: "Informational",
    }

    return severity_labels.get(severity_number, "Unknown")


@tool
def list_policy_tool(
    query: str,
    embeding: list,
    searchconnection: CustomConnection,
    groups: list,
    policySets: list,
) -> object:
    selected_sets = list(
        dict.fromkeys(
            str(value).strip()
            for value in (policySets or [])
            if str(value).strip()
        )
    )

    # Fail closed: never guess a Policy Set.
    if not selected_sets:
        print(
            "[Policy Search] No Policy Set selected; "
            "refusing to return policies."
        )
        return []

    policy_file = find_policy_file()
    policies = load_policies(policy_file)

    # Filter by Policy Set before semantic ranking.
    candidates = [
        policy
        for policy in policies
        if str(
            policy.get("policySet", "General Policies")
        ).strip() in selected_sets
        and group_is_allowed(policy, groups or [])
    ]

    if not candidates:
        print(
            f"[Policy Search] No policies matched "
            f"policySets={selected_sets}; "
            f"groups={groups or []}"
        )
        return []

    config = get_embedding_config(searchconnection)

    client = OpenAI(
        base_url=config["base_url"],
        api_key=config["api_key"],
    )

    model = config["model"]

    # Cache identity includes endpoint and embedding model.
    cache_path = (
        policy_file.parent
        / "local_embedding_policy_embeddings.json"
    )

    config_fingerprint = config["base_url"] + "|" + model

    # Generate/cache embeddings for all policies, then rank only
    # candidates belonging to the selected Policy Sets.
    all_embeddings = get_policy_embeddings(
        policies,
        client,
        model,
        cache_path,
        config_fingerprint,
    )

    original_indexes = {
        id(policy): index
        for index, policy in enumerate(policies)
    }

    ranked = []

    for policy in candidates:
        index = original_indexes[id(policy)]
        vector = all_embeddings.get(str(index), [])

        score = cosine_similarity(
            embeding or [],
            vector,
        )

        ranked.append((score, policy))

    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    # Preserve trusted metadata from policy.json.
    # The model must not invent Policy Set names or severity labels.
    result = [
        {
            "id": policy.get("id"),
            "title": policy.get("title", ""),
            "instruction": policy.get("instruction", ""),
            "policySet": policy.get("policySet"),
            "severity": policy.get("severity"),
            "severityLabel": get_severity_label(
                policy.get("severity")
            ),
        }
        for score, policy in ranked
    ]

    print(
        f"[Policy Search] Returned {len(result)} rules; "
        f"selected sets={selected_sets}; "
        f"matched titles={[policy['title'] for policy in result]}"
    )

    return result
