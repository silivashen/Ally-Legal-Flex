"""Local core prompts; contract data and output requirements stay in each flow."""
import ast
import hashlib
import json

FEATURES = {
    'ask': ('ask_result_format.py', 'ORIGINAL_ASK_PROMPT'),
    'summary': ('summary_full_doc.py', 'ORIGINAL_CLAUSE_PROMPT'),
    'review': ('documen_summary.py', 'ORIGINAL_REVIEW_PROMPT'),
}
MAX_PROMPT_CHARS = 20000
SCHEMAS = {
    'ask': {'Answer': 'Answer to the question', 'AnswerSource': 'Exact contract excerpt or empty',
            'MarkedText': 'Short exact substring or empty', 'SearchResults': []},
    'summary': {'Summary': 'Contract overview', 'KeyPoints': ['Important point'], 'Items': [
        {'title': 'Clause title', 'summary': 'Clause summary', 'notes': 'Risk analysis',
         'original_text': 'Exact contract excerpt', 'policy_ids': [], 'keyItems': ['Key fact']}]},
    'review': {'PolicyItems': [{'title': 'Clause title', 'summary': 'Clause summary',
        'keyItems': ['Key fact'], 'iscompliant': 'yes', 'suggested_correction': '',
        'policy_ids': [], 'corrected_text': []}]},
}


def validate_prompt(feature, text):
    if feature not in FEATURES:
        raise ValueError('Choose Ask, Summary or Review.')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROMPT_CHARS:
        raise ValueError('Enter a prompt between 1 and 20,000 characters.')
    if any(ord(char) < 32 and char not in '\n\r\t' for char in text):
        raise ValueError('The prompt contains unsupported control characters.')
    text.encode('utf-8')
    return text


def load_overrides(path):
    if not path.exists():
        return {}
    if path.stat().st_size > 256 * 1024:
        raise ValueError('Prompt settings file is too large.')
    settings = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(settings, dict):
        raise ValueError('Prompt settings must be a JSON object.')
    for feature, text in settings.items():
        validate_prompt(feature, text)
    return settings


def default_prompts(flow_dir):
    """Read constants without importing PromptFlow, OpenAI or executing flow code."""
    defaults = {}
    for feature, (filename, variable) in FEATURES.items():
        tree = ast.parse((flow_dir / filename).read_text(encoding='utf-8'))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == variable
                                  for target in node.targets))
        defaults[feature] = ast.literal_eval(assignment.value)
    return defaults


def prompt_view(defaults, overrides):
    result = {}
    for feature, default in defaults.items():
        text = overrides.get(feature, default)
        version = hashlib.sha256(json.dumps([text, default], ensure_ascii=False).encode()).hexdigest()
        result[feature] = {'text': text, 'default': default,
                           'customized': text != default, 'version': version}
    return result


def get_core_prompt(feature, default, config_dir):
    overrides = load_overrides(config_dir / 'prompt_settings.json')
    text = overrides.get(feature, default)
    if text == default:
        return default
    # A custom task cannot remove the fields the UI and verified citations require.
    text += '\n\nREQUIRED OUTPUT: Return only valid JSON with these property names and types:\n'
    text += json.dumps(SCHEMAS[feature], ensure_ascii=False, indent=2)
    text += '\nAnswer in {language}, keeping quoted contract text unchanged. '
    text += 'The structure is an example, not evidence or a preselected reference. '
    text += 'Use only verified source IDs supplied below. Use [] when no reference applies.\n'
    if feature == 'review':
        text += ('iscompliant must be "yes" or "no". When correction is needed, corrected_text '
                 'contains three complete alternative replacement clauses; otherwise use [] and '
                 'an empty suggested_correction.\n')
    if feature in {'summary', 'review'}:
        text += '\nCompany Policies:\n'
    return text
