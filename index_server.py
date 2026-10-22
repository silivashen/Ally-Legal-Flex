
from http.server import ThreadingHTTPServer
from local_api_security import LocalAPIHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from threading import RLock
import importlib.util
import json
import os
import tempfile
import base64
import binascii

from policy_excel import MAX_FILE_BYTES, export_policy_workbook, preview_import

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "contract_index.json"
POLICY = ROOT / "policy.json"
POLICY_CACHE = ROOT / "local_bge_m3_policy.json"
POLICY_SETS = ROOT / "policy_sets.json"
POLICY_LOCK = RLock()
POLICY_TEMPLATE = ROOT / "docs/templates/policy-import-template.xlsx"
PROMPT_SETTINGS_FILE = ROOT / "prompt_settings.json"
PROMPT_LOCK = RLock()
FLOW_DIR = ROOT / "backend/PromptFlow/legal-main-flow"

_prompt_spec = importlib.util.spec_from_file_location("ally_prompt_settings", FLOW_DIR / "prompt_settings.py")
if _prompt_spec is None or _prompt_spec.loader is None:
    raise RuntimeError("The prompt settings module could not be loaded.")
prompt_settings = importlib.util.module_from_spec(_prompt_spec)
_prompt_spec.loader.exec_module(prompt_settings)

# Load the same dependency-free indexing implementation used by the local flow.
_index_spec = importlib.util.spec_from_file_location(
    "ally_contract_index", ROOT / "backend/PromptFlow/legal-main-flow/contract_index.py"
)
if _index_spec is None or _index_spec.loader is None:
    raise RuntimeError("The shared contract index module could not be loaded.")
contract_index = importlib.util.module_from_spec(_index_spec)
_index_spec.loader.exec_module(contract_index)


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(path, data):
    fd, tmp = tempfile.mkstemp(
        prefix=path.stem + "_",
        suffix=".tmp",
        dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_policies():
    policies = load_json(POLICY, [])
    if isinstance(policies, dict):
        policies = policies.get("value", [])
    if not isinstance(policies, list):
        raise ValueError("policy.json must contain a JSON array")
    return policies


def policy_set_name(policy):
    return str(policy.get("policySet") or "").strip() or "General Policies"


def get_policy_sets():
    """Read policy sets, initializing them from existing policies if needed."""
    with POLICY_LOCK:
        if POLICY_SETS.exists():
            policy_sets = load_json(POLICY_SETS, [])
            if not isinstance(policy_sets, list):
                raise ValueError("policy_sets.json must contain a JSON array")
            return policy_sets

        policy_sets = []
        for policy in load_policies():
            if isinstance(policy, dict):
                name = policy_set_name(policy)
                if name not in policy_sets:
                    policy_sets.append(name)

        if not policy_sets:
            policy_sets = ["General Policies"]

        save_json_atomic(POLICY_SETS, policy_sets)
        return policy_sets


class Handler(LocalAPIHandler):
    def send_excel(self, content, filename):
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Origin")
        if getattr(self, "_cors_origin", None):
            self.send_header("Access-Control-Allow-Origin", self._cors_origin)
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if not self.validate_request("GET"):
            return
        route = urlparse(self.path).path.rstrip("/")

        try:
            if route == "/prompt-settings":
                with PROMPT_LOCK:
                    prompts = prompt_settings.prompt_view(
                        prompt_settings.default_prompts(FLOW_DIR),
                        prompt_settings.load_overrides(PROMPT_SETTINGS_FILE),
                    )
                return self.send_json(200, {"success": True, "prompts": prompts})

            if route == "/policies/import-template":
                return self.send_excel(POLICY_TEMPLATE.read_bytes(), "Ally-Legal-Policy-Template.xlsx")

            if route == "/policies/export":
                selected = parse_qs(urlparse(self.path).query).get("policySet", [""])[0]
                with POLICY_LOCK:
                    if selected not in get_policy_sets():
                        return self.send_json(400, {"error": "Select an existing Policy Set before downloading."})
                    policies = [p for p in load_policies() if policy_set_name(p) == selected]
                    try:
                        content = export_policy_workbook(POLICY_TEMPLATE.read_bytes(), policies)
                    except (ValueError, TypeError) as error:
                        return self.send_json(400, {"error": str(error)})
                return self.send_excel(content, "Ally-Legal-Policies.xlsx")

            if route == "/policies":
                policies = load_json(POLICY, [])
                if isinstance(policies, dict):
                    policies = policies.get("value", [])
                if not isinstance(policies, list):
                    return self.send_json(500, {
                        "error": "policy.json must contain a JSON array"
                    })
                return self.send_json(200, {"policies": policies})

            if route == "/policy-sets":
                policy_sets = get_policy_sets()
                return self.send_json(200, {"policySets": policy_sets})

            return self.send_json(404, {"error": "Unknown endpoint"})

        except Exception as e:
            return self.send_json(500, {"error": str(e)})

    def do_POST(self):
        if not self.validate_request("POST"):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 20 * 1024 * 1024:
                return self.send_json(400, {"error": "Invalid request size"})

            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                return self.send_json(400, {
                    "error": "Request body must be a JSON object"
                })

            route = urlparse(self.path).path.rstrip("/")

            if route == "/prompt-settings":
                feature = data.get("feature")
                restore = data.get("reset", False)
                try:
                    if not isinstance(feature, str) or feature not in prompt_settings.FEATURES:
                        raise ValueError("Choose Ask, Summary or Review.")
                    if not isinstance(restore, bool):
                        raise ValueError("reset must be true or false.")
                    text = None if restore else prompt_settings.validate_prompt(feature, data.get("text"))
                except ValueError as error:
                    return self.send_json(400, {"error": str(error)})
                with PROMPT_LOCK:
                    overrides = prompt_settings.load_overrides(PROMPT_SETTINGS_FILE)
                    defaults = prompt_settings.default_prompts(FLOW_DIR)
                    current = prompt_settings.prompt_view(defaults, overrides)[feature]
                    if data.get("expectedVersion") != current["version"]:
                        return self.send_json(409, {"error": "This prompt changed in another window. Reload saved prompts, then save your edits again."})
                    if restore or text == defaults[feature]:
                        overrides.pop(feature, None)
                    else:
                        overrides[feature] = text
                    save_json_atomic(PROMPT_SETTINGS_FILE, overrides)
                    result = prompt_settings.prompt_view(defaults, overrides)[feature]
                return self.send_json(200, {"success": True, "prompt": result})

            if route in {"/policies/import/preview", "/policies/import"}:
                filename = data.get("filename")
                encoded = data.get("contentBase64")
                selected = data.get("policySet")
                if not isinstance(filename, str) or not filename.lower().endswith(".xlsx"):
                    return self.send_json(400, {"error": "Select an Excel .xlsx file (not .xls or .xlsm)."})
                if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES + 2) // 3 * 4:
                    return self.send_json(400, {"error": "Upload an .xlsx file no larger than 3 MB."})
                try:
                    content = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    return self.send_json(400, {"error": "The uploaded file could not be read. Select it again."})
                with POLICY_LOCK:
                    policies = load_policies()
                    try:
                        preview = preview_import(content, selected, policies, get_policy_sets())
                    except ValueError as error:
                        return self.send_json(400, {"error": str(error)})
                    if route.endswith("/preview"):
                        return self.send_json(200, {"success": True, **preview})
                    if data.get("previewToken") != preview["previewToken"]:
                        return self.send_json(409, {"error": "Policies or the file changed. Preview again before importing."})
                    if preview["conflicts"]:
                        return self.send_json(409, {"error": "Resolve same-name policy conflicts in the Excel file before importing."})
                    additions = []
                    ids = [p.get("id") for p in policies if isinstance(p.get("id"), int)]
                    used_ids = {str(p.get("id")).strip() for p in policies}
                    next_id = max([0, *ids]) + 1
                    for row in preview["rows"]:
                        if row["status"] != "ready":
                            continue
                        while str(next_id) in used_ids:
                            next_id += 1
                        additions.append({key: value for key, value in row.items() if key not in {"row", "status"}} | {"id": next_id})
                        used_ids.add(str(next_id))
                        next_id += 1
                    if additions:
                        # A stale vector cache must not outlive a successful policy change.
                        if POLICY_CACHE.exists():
                            POLICY_CACHE.unlink()
                        save_json_atomic(POLICY, policies + additions)
                return self.send_json(200, {"success": True, "added": len(additions), "skipped": preview["skipped"]})

            if route == "/policies/delete":
                target = data.get("policy")
                if not isinstance(target, dict):
                    return self.send_json(400, {
                        "error": "policy must be a JSON object"
                    })

                with POLICY_LOCK:
                    policies = load_policies()
                    target_json = json.dumps(target, sort_keys=True)
                    matches = [
                        index for index, policy in enumerate(policies)
                        if json.dumps(policy, sort_keys=True) == target_json
                    ]
                    if len(matches) != 1:
                        return self.send_json(409, {
                            "error": "Policy changed or is not unique. Refresh before deleting."
                        })

                    remaining = policies[:matches[0]] + policies[matches[0] + 1:]
                    cache_removed = False
                    if POLICY_CACHE.exists():
                        POLICY_CACHE.unlink()
                        cache_removed = True
                    # If cache removal fails, leave the policy file untouched.
                    save_json_atomic(POLICY, remaining)

                return self.send_json(200, {
                    "success": True,
                    "count": len(remaining),
                    "cacheInvalidated": cache_removed
                })

            if route == "/policy-sets/delete":
                name = data.get("name")
                if not isinstance(name, str) or not name.strip():
                    return self.send_json(400, {
                        "error": "name must be a non-empty string"
                    })
                name = name.strip()

                with POLICY_LOCK:
                    policy_sets = get_policy_sets()
                    if name not in policy_sets:
                        return self.send_json(409, {
                            "error": "Policy set no longer exists. Refresh before deleting."
                        })
                    if any(
                        isinstance(policy, dict) and policy_set_name(policy) == name
                        for policy in load_policies()
                    ):
                        return self.send_json(409, {
                            "error": "Move or delete all policies in this set before deleting it."
                        })

                    remaining_sets = [item for item in policy_sets if item != name]
                    save_json_atomic(POLICY_SETS, remaining_sets)

                return self.send_json(200, {
                    "success": True,
                    "policySets": remaining_sets
                })

            if route == "/policy-sets":
                submitted = data.get("policySets")
                if not isinstance(submitted, list):
                    return self.send_json(400, {
                        "error": "policySets must be a JSON array"
                    })

                clean_sets = []
                for item in submitted:
                    if not isinstance(item, str) or not item.strip():
                        return self.send_json(400, {
                            "error": "Each policy set must be a non-empty string"
                        })

                    name = item.strip()
                    if name not in clean_sets:
                        clean_sets.append(name)

                with POLICY_LOCK:
                    policies = load_policies()
                    assigned_sets = {
                        policy_set_name(item)
                        for item in policies
                        if isinstance(item, dict)
                    }

                    removed_sets = assigned_sets - set(clean_sets)
                    if removed_sets:
                        return self.send_json(400, {
                            "error": "Reassign policies before removing these sets",
                            "policySetsInUse": sorted(removed_sets)
                        })

                    if not clean_sets and policies:
                        return self.send_json(400, {
                            "error": "Remove all policies before removing all policy sets"
                        })

                    save_json_atomic(POLICY_SETS, clean_sets)
                return self.send_json(200, {
                    "success": True,
                    "policySets": clean_sets
                })

            if route == "/policies":
                submitted = data.get("policies")
                if not isinstance(submitted, list):
                    return self.send_json(400, {
                        "error": "policies must be a JSON array"
                    })

                clean = []
                seen_ids = set()
                next_id = 1

                for item in submitted:
                    if not isinstance(item, dict):
                        return self.send_json(400, {
                            "error": "Each policy must be an object"
                        })

                    title = str(item.get("title", "")).strip()
                    instruction = str(item.get("instruction", "")).strip()

                    if not title or not instruction:
                        return self.send_json(400, {
                            "error": "Each policy needs a title and instruction"
                        })

                    try:
                        policy_id = int(item.get("id", 0))
                    except (TypeError, ValueError):
                        policy_id = 0

                    if policy_id <= 0 or policy_id in seen_ids:
                        while next_id in seen_ids:
                            next_id += 1
                        policy_id = next_id

                    seen_ids.add(policy_id)
                    next_id = max(next_id, policy_id + 1)

                    tags = item.get("tags", [])
                    groups = item.get("groups", [])

                    if isinstance(tags, str):
                        tags = [x.strip() for x in tags.split(",") if x.strip()]
                    if not isinstance(tags, list):
                        tags = []

                    if isinstance(groups, str):
                        groups = [x.strip() for x in groups.split(",") if x.strip()]
                    if not isinstance(groups, list):
                        groups = []

                    try:
                        severity = int(item.get("severity", 2))
                    except (TypeError, ValueError):
                        severity = 2

                    record = dict(item)
                    record.update({
                        "id": policy_id,
                        "title": title,
                        "instruction": instruction,
                        "tags": tags,
                        "severity": severity,
                        "groups": groups
                    })
                    clean.append(record)

                with POLICY_LOCK:
                    current_sets = set(get_policy_sets())
                    missing_sets = {
                        policy_set_name(policy) for policy in clean
                    } - current_sets
                    if missing_sets:
                        return self.send_json(409, {
                            "error": "Policy sets changed. Refresh before saving policies.",
                            "missingPolicySets": sorted(missing_sets)
                        })

                    save_json_atomic(POLICY, clean)

                    cache_removed = False
                    if POLICY_CACHE.exists():
                        POLICY_CACHE.unlink()
                        cache_removed = True

                return self.send_json(200, {
                    "success": True,
                    "count": len(clean),
                    "cacheInvalidated": cache_removed
                })

            if route == "/index":
                text = data.get("document_text", "")
                doc_id = data.get("filename", "")
                if not isinstance(text, str) or not text.strip() or not isinstance(doc_id, str) or not doc_id.strip():
                    return self.send_json(400, {
                        "error": "Document ID or text is empty"
                    })
                try:
                    result = contract_index.index_document(
                        doc_id, text, data.get("document_paragraphs"),
                        INDEX.parent / ".ally-contract-index",
                    )
                except ValueError as error:
                    return self.send_json(400, {"error": str(error)})
                return self.send_json(200, result)

            if route == "/check":
                doc_id = data.get("filename", "")
                text = data.get("document_text", "")
                if not isinstance(doc_id, str) or not isinstance(text, str):
                    return self.send_json(400, {"error": "Document ID and text must be strings"})
                try:
                    result = contract_index.check_contract_index(
                        doc_id, text, data.get("document_paragraphs"),
                        INDEX.parent / ".ally-contract-index", INDEX,
                    )
                except ValueError as error:
                    return self.send_json(400, {"error": str(error)})
                return self.send_json(200, result)

            return self.send_json(404, {"error": "Unknown endpoint"})

        except Exception as e:
            return self.send_json(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    print("Ally local service listening at http://127.0.0.1:8084")
    print("Contract index:", INDEX)
    print("Policy file:", POLICY)
    print("Policy vector cache:", POLICY_CACHE)
    print("Policy sets file:", POLICY_SETS)
    ThreadingHTTPServer(("127.0.0.1", 8084), Handler).serve_forever()
