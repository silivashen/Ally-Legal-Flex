"""Prompt editing uses isolated files and mocked model boundaries only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_local_api_security import invoke, load_server
from test_summary_policy_sets import FLOWS, execute, load_module
from test_ask_response_contract import CANDIDATES, execute as execute_ask
from test_policy_citations import execute_review, policy, review_result


class PromptSettingsTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server('prompt_config_test', 'index_server.py')
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.config = self.directory / 'prompt_settings.json'
        patcher = patch.object(self.server, 'PROMPT_SETTINGS_FILE', self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self):
        status, body = invoke(self.server, 'GET', '/prompt-settings')
        self.assertEqual(status, 200)
        return body['prompts']

    def save(self, feature, text, **extra):
        version = self.read()[feature]['version']
        return invoke(self.server, 'POST', '/prompt-settings', {
            'feature': feature, 'text': text, 'expectedVersion': version, **extra,
        })

    def test_defaults_are_read_from_actual_source_without_creating_a_config(self):
        prompts = self.read()
        self.assertEqual(set(prompts), {'ask', 'summary', 'review'})
        for key, name in [('ask', 'ORIGINAL_ASK_PROMPT'), ('summary', 'ORIGINAL_CLAUSE_PROMPT'), ('review', 'ORIGINAL_REVIEW_PROMPT')]:
            filename = {'ask': 'ask_result_format.py', 'summary': 'summary_full_doc.py', 'review': 'documen_summary.py'}[key]
            module = load_module(FLOWS[0] / filename)
            self.assertEqual(prompts[key]['text'], getattr(module, name))
            self.assertEqual(prompts[key]['text'], prompts[key]['default'])
            self.assertFalse(prompts[key]['customized'])
        self.assertFalse(self.config.exists())

    def test_saving_and_restoring_one_feature_preserves_other_features(self):
        self.assertEqual(self.save('ask', 'CUSTOM ASK')[0], 200)
        self.assertEqual(self.save('summary', 'CUSTOM SUMMARY')[0], 200)
        prompts = self.read()
        self.assertTrue(prompts['ask']['customized'])
        self.assertFalse(prompts['review']['customized'])
        self.assertEqual(self.save('ask', '', reset=True)[0], 200)
        prompts = self.read()
        self.assertFalse(prompts['ask']['customized'])
        self.assertEqual(prompts['summary']['text'], 'CUSTOM SUMMARY')
        self.assertNotIn('ask', json.loads(self.config.read_text()))

    def test_stale_editor_cannot_overwrite_another_saved_prompt(self):
        version = self.read()['ask']['version']
        self.save('ask', 'Saved in another window')
        status, _ = invoke(self.server, 'POST', '/prompt-settings', {
            'feature': 'ask', 'text': 'Stale draft', 'expectedVersion': version,
        })
        self.assertEqual(status, 409)
        self.assertEqual(self.read()['ask']['text'], 'Saved in another window')

    def test_invalid_input_or_foreign_origin_never_writes_configuration(self):
        for payload in ({'feature': 'unknown', 'text': 'bad'}, {'feature': 'ask', 'text': ''},
                        {'feature': 'ask', 'text': 123}, {'feature': 'review', 'text': 'x' * 20001},
                        {'feature': 'ask', 'text': 'Bad\x00text'}, {'feature': 'ask', 'reset': 'true'}):
            body = {'expectedVersion': self.read()['ask']['version'], **payload}
            status, _ = invoke(self.server, 'POST', '/prompt-settings', body)
            self.assertEqual(status, 400)
            self.assertFalse(self.config.exists())
        status, _ = invoke(self.server, 'POST', '/prompt-settings', {}, {'Origin': 'https://attacker.invalid'})
        self.assertEqual(status, 403)
        self.assertFalse(self.config.exists())

    def test_bad_file_and_failed_write_do_not_report_success(self):
        self.config.write_text('{invalid')
        status, _ = invoke(self.server, 'GET', '/prompt-settings')
        self.assertEqual(status, 500)
        self.config.unlink()
        current = self.read()['ask']['version']
        with patch.object(self.server, 'save_json_atomic', side_effect=OSError('Disk full')):
            status, _ = invoke(self.server, 'POST', '/prompt-settings', {
                'feature': 'ask', 'text': 'Draft', 'expectedVersion': current,
            })
        self.assertEqual(status, 500)
        self.assertFalse(self.config.exists())

    def test_saved_prompts_are_used_on_next_request_in_both_flow_copies(self):
        for feature in ('ask', 'summary', 'review'):
            self.assertEqual(self.save(feature, f'CUSTOM_{feature}: explain concisely in {{language}}.')[0], 200)
        cases = [
            ('ask', 'ask_result_format.py', lambda module: execute_ask(module, CANDIDATES)),
            ('summary', 'summary_full_doc.py', lambda module: execute(module, ['NDA'])),
            ('review', 'documen_summary.py', lambda module: execute_review(module, [policy()], review_result([7]))),
        ]
        for flow in FLOWS:
            for feature, filename, run in cases:
                with self.subTest(flow=flow, feature=feature):
                    module = load_module(flow / filename)
                    with patch.object(module, 'get_local_config_dir', return_value=self.directory):
                        _, create = run(module)
                    prompt = create.call_args.kwargs['messages'][0]['content']
                    self.assertTrue(prompt.startswith(f'CUSTOM_{feature}:'))
                    self.assertNotIn('{language}', prompt)
                    self.assertIn('REQUIRED OUTPUT', prompt)
                    if feature == 'ask':
                        self.assertIn('REFERENCE FORMAT', prompt)
                        self.assertNotIn('CUSTOM_summary', prompt)
                    else:
                        self.assertIn('Do not cite policy numbers in narrative text', prompt)
                        self.assertIn('policy_ids', prompt)
                    if feature == 'summary':
                        self.assertIn('NDA_ONLY', prompt)
                        self.assertNotIn('GENERAL_ONLY', prompt)
                        self.assertNotIn('SERVICES_ONLY', prompt)


if __name__ == '__main__':
    unittest.main()
