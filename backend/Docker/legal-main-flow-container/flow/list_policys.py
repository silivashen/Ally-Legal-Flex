"""Load selected policies from the frontend's local configuration."""
import json
from promptflow.core import tool
from promptflow.connections import CustomConnection
from model_config_loader import find_local_config


@tool
def list_policy_tool(input: str, searchconnection: CustomConnection, policySets: list) -> list:
    if not isinstance(policySets, list) or not policySets:
        raise ValueError("Please select at least one Policy Set.")
    if any(not isinstance(name, str) or not name.strip() for name in policySets):
        raise ValueError("Invalid Policy Set selection.")
    selected = {name.strip() for name in policySets}
    policies = json.loads(find_local_config("policy.json").read_text(encoding="utf-8-sig"))
    if isinstance(policies, dict):
        policies = policies.get("value", [])
    if not isinstance(policies, list):
        raise ValueError("policy.json must contain a list of policies.")
    result = [policy for policy in policies if isinstance(policy, dict)
              and policy.get("policySet") in selected]
    missing = selected - {policy["policySet"] for policy in result}
    if missing:
        raise ValueError("No policies found for: " + ", ".join(sorted(missing)))
    return result
