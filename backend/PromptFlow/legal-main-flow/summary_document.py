from promptflow.core import tool
from promptflow.connections import CustomConnection
from model_config_loader import get_chat_client_and_model
import json
import re


def parse_json_response(content: str) -> dict:
    """Parse JSON returned by the model, including optional Markdown fences."""
    if not content or not content.strip():
        raise ValueError("Chat model returned empty content.")

    content = content.strip()

    # Remove Markdown code fences if the model adds them.
    content = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        content,
        flags=re.IGNORECASE
    ).strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # Recover a JSON object if the response contains surrounding text.
        start = content.find("{")
        end = content.rfind("}")

        if start == -1 or end <= start:
            raise ValueError(
                "The model response does not contain a valid JSON object."
            )

        result = json.loads(content[start:end + 1])

    if not isinstance(result, dict):
        raise ValueError("The model response must be a JSON object.")

    if not isinstance(result.get("PolicyItems"), list):
        raise ValueError("The JSON response must contain a PolicyItems list.")

    return result


@tool
def python_tool(
    input_text: str,
    policy_list: list,
    ally: CustomConnection,
    language: str
) -> object:

    if not policy_list:
        return {"PolicyItems": []}

    client, chat_model = get_chat_client_and_model(ally)

    prompt = """
You are a legal contract review assistant.

Review the provided contract against ONLY the policy items supplied below.

Requirements:

1. Analyze each supplied policy item against the relevant contract text.
2. Do not invent contract language or policy requirements.
3. The "summary" field must summarize the relevant contract text.
4. The "compare" field must explain the policy requirement and compare it
   with the actual contract language. Identify deviations and risks clearly.
5. "original_text" must reproduce the exact relevant contract text.
   Do not rewrite, correct, or paraphrase it.
6. "original_policy" must reproduce the exact policy instruction provided.
7. "keyItems" must be a JSON array of important details, such as numbers,
   dates, names, amounts, obligations, and deadlines.
8. "iscompliant" must be the string "yes" or "no".
9. Use "no" when the relevant contract text violates the policy.
   Explain the violation in "compare".
10. Do not claim compliance when the relevant text is missing or insufficient
    to determine compliance. Explain the limitation in "compare".
11. Return ONLY one valid JSON object. Do not use Markdown or add commentary.
12. Do not omit a supplied policy item merely because it is difficult to assess.

Required structure:

{
  "PolicyItems": [
    {
      "title": "Policy Title",
      "summary": "Summary of relevant contract text",
      "compare": "Comparison and explanation of any deviation",
      "original_text": "Exact relevant contract text",
      "original_policy": "Exact policy text",
      "keyItems": ["Important item"],
      "iscompliant": "yes"
    }
  ]
}

The policy items to review are:
""" + json.dumps(policy_list, indent=2, ensure_ascii=False)

    prompt += "\nWrite generated text in " + str(language) + ". Preserve exact source quotations."

    openai_response = client.chat.completions.create(
        model=chat_model,
        messages=[
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": (
                    "Review the following contract text against the supplied "
                    "policy items. Return the required JSON object only.\n\n"
                    + str(input_text)
                )
            }
        ]
        # Keep compatibility with endpoints that do not accept response_format.
    )

    try:
        content = openai_response.choices[0].message.content
        response = parse_json_response(content)
        return response

    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("The chat model returned an invalid policy summary.") from exc
