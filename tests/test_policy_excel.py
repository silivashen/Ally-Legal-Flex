"""Excel policy imports use synthetic workbooks and isolated local policy files."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import policy_excel


def workbook(rows, *, shared=False, formula=False):
    buffer = io.BytesIO()
    cells = []
    strings = []
    for number, values in enumerate(rows, 1):
        values_xml = []
        for column, value in enumerate(values):
            address = f'{chr(65 + column)}{number}'
            if shared:
                strings.append(str(value))
                value_xml = f'<c r="{address}" t="s"><v>{len(strings)-1}</v></c>'
            else:
                value_xml = f'<c r="{address}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            if formula and number == 2 and column == 1:
                value_xml = f'<c r="{address}"><f>"calculated"</f><v>0</v></c>'
            values_xml.append(value_xml)
        cells.append(f'<row r="{number}">{"".join(values_xml)}</row>')
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Policies" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(cells) + '</sheetData></worksheet>')
        if shared:
            archive.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' + ''.join(f'<si><t>{escape(value)}</t></si>' for value in strings) + '</sst>')
    return buffer.getvalue()


HEADERS = ['政策名称', '审核要求', 'Severity', '标签（选填）']
RULE = ['责任上限', '应设置责任上限。', 'Critical', '责任, 赔偿']
TEMPLATE = Path(__file__).resolve().parents[1] / 'docs/templates/policy-import-template.xlsx'


def replace_part(content, name, value):
    buffer = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as source, ZipFile(buffer, 'w') as target:
        for item in source.infolist():
            target.writestr(item.filename, value if item.filename == name else source.read(item.filename))
    return buffer.getvalue()


class ExcelReadingTests(unittest.TestCase):
    def test_inline_and_shared_strings_preserve_chinese_and_severity(self):
        for shared in (False, True):
            result = policy_excel.read_policy_workbook(workbook([HEADERS, RULE], shared=shared))
            self.assertEqual(result[0]['row'], 2)
            self.assertEqual(result[0]['title'], '责任上限')
            self.assertEqual(result[0]['severity'], 1)
            self.assertEqual(result[0]['tags'], ['责任', '赔偿'])

    def test_english_headers_and_numeric_severity_are_supported(self):
        result = policy_excel.read_policy_workbook(workbook([
            ['Policy title', 'Policy instruction', 'Severity'],
            ['Term', 'Limit the term.', '2'], ['', '', ''],
        ]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['severity'], 2)

    def test_errors_include_excel_row_and_never_default_invalid_severity(self):
        for row in (["", 'Check this', 'Critical'], ['Term', '', 'Warning'], ['Term', 'Check this', 'Severe']):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r'Row 2'):
                policy_excel.read_policy_workbook(workbook([HEADERS, row]))

    def test_missing_headers_formulas_and_non_excel_content_are_rejected(self):
        for content in (b'not excel', workbook([['Wrong'], RULE]), workbook([HEADERS, RULE], formula=True)):
            with self.subTest(size=len(content)), self.assertRaises(ValueError):
                policy_excel.read_policy_workbook(content)

    def test_generated_template_has_headers_and_no_importable_example_rules(self):
        self.assertEqual(policy_excel.read_policy_workbook(TEMPLATE.read_bytes()), [])
        with ZipFile(TEMPLATE) as archive:
            xml = archive.read('xl/worksheets/sheet1.xml')
            self.assertIn(b'dataValidation', xml)
            self.assertNotIn(b'<f>', xml)
            sheet = policy_excel._xml(archive, 'xl/worksheets/sheet1.xml')
            headers = [policy_excel._text(cell) for cell in sheet.findall('m:sheetData/m:row', policy_excel.NS)[0]]
            self.assertEqual(headers, ['Policy Title', 'Policy Instruction', 'Severity', 'Tags (optional)', 'Groups (optional)'])

    def test_english_template_headers_include_optional_groups_and_tags(self):
        rows = policy_excel.read_policy_workbook(workbook([
            policy_excel.HEADERS, ['Cap', 'Check cap.', 'Critical', 'Liability, Cap', 'Legal, Sales'],
        ]))
        self.assertEqual(rows[0]['groups'], ['Legal', 'Sales'])
        self.assertEqual(rows[0]['tags'], ['Liability', 'Cap'])

    def test_file_and_policy_count_limits(self):
        for content in (b'', b'x' * (policy_excel.MAX_FILE_BYTES + 1),
                        workbook([HEADERS] + [RULE] * (policy_excel.MAX_ROWS + 1))):
            with self.assertRaises(ValueError):
                policy_excel.read_policy_workbook(content)

    def test_dtd_external_sheet_and_data_outside_headers_are_rejected(self):
        valid = workbook([HEADERS, RULE])
        attacks = [
            replace_part(valid, 'xl/workbook.xml', '<!DOCTYPE x [<!ENTITY secret "expanded">]><workbook/>'),
            replace_part(valid, 'xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" TargetMode="External" Target="https://example.invalid"/></Relationships>'),
            workbook([HEADERS, RULE + ['unexpected']]),
            workbook([HEADERS + ['Policy Set'], RULE + ['Other']]),
        ]
        for content in attacks:
            with self.assertRaises(ValueError):
                policy_excel.read_policy_workbook(content)

    def test_hidden_sheets_invalid_references_and_cells_are_rejected(self):
        valid = workbook([HEADERS, RULE], shared=True)
        with ZipFile(io.BytesIO(valid)) as archive:
            book = archive.read('xl/workbook.xml')
            relationships = archive.read('xl/_rels/workbook.xml.rels')
            sheet = archive.read('xl/worksheets/sheet1.xml')
        attacks = [
            replace_part(valid, 'xl/workbook.xml', book.replace(b'sheetId="1"', b'sheetId="1" state="hidden"')),
            replace_part(valid, 'xl/_rels/workbook.xml.rels', relationships.replace(b'rId1', b'other')),
            replace_part(valid, 'xl/_rels/workbook.xml.rels', relationships.replace(b'worksheets/sheet1.xml', b'../../outside.xml')),
            replace_part(valid, 'xl/worksheets/sheet1.xml', sheet.replace(b'r="2"', b'r="0"')),
            replace_part(valid, 'xl/worksheets/sheet1.xml', sheet.replace(b'r="A2"', b'r="A3"')),
            replace_part(valid, 'xl/worksheets/sheet1.xml', sheet.replace(b'<v>4</v>', b'<v>-1</v>')),
            replace_part(valid, 'xl/worksheets/sheet1.xml', sheet.replace(b't="s"><v>4</v>', b't="b"><v>1</v>')),
        ]
        for content in attacks:
            with self.assertRaises(ValueError):
                policy_excel.read_policy_workbook(content)

    def test_expansion_limits_reject_small_files_with_excessive_zip_contents(self):
        for mode in ('many_parts', 'large_part'):
            content = io.BytesIO()
            with ZipFile(content, 'w', ZIP_DEFLATED) as archive:
                if mode == 'many_parts':
                    for index in range(257):
                        archive.writestr(str(index), '')
                else:
                    archive.writestr('expanded', b'0' * (16 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, 'too large'):
                policy_excel.read_policy_workbook(content.getvalue())

    def test_export_roundtrip_preserves_severity_tags_groups_and_literal_formula_text(self):
        policies = [
            {'title': '=HYPERLINK("https://example.invalid")', 'instruction': 'Text < & >\n第二行', 'severity': 1, 'tags': ['责任', '赔偿'], 'groups': ['legal', 'sales']},
            {'title': 'Warning', 'instruction': '+literal text', 'severity': 2, 'tags': [], 'groups': []},
            {'title': 'Information', 'instruction': 'Keep me', 'severity': 3},
            {'title': 'Legacy empty metadata', 'instruction': 'Keep values blank.', 'severity': 2, 'tags': None, 'groups': None},
        ]
        content = policy_excel.export_policy_workbook(TEMPLATE.read_bytes(), policies)
        restored = policy_excel.read_policy_workbook(content)
        for expected, actual in zip(policies, restored):
            for key in ('title', 'instruction', 'severity'):
                self.assertEqual(actual[key], expected[key])
            for key in ('tags', 'groups'):
                self.assertEqual(actual[key], expected.get(key) or [])
        with ZipFile(io.BytesIO(content)) as archive:
            sheet = policy_excel._xml(archive, 'xl/worksheets/sheet1.xml')
            self.assertEqual(sheet.findall('.//m:f', policy_excel.NS), [])
            self.assertIsNotNone(sheet.find('m:dataValidations', policy_excel.NS))

    def test_export_empty_set_produces_import_template(self):
        content = policy_excel.export_policy_workbook(TEMPLATE.read_bytes(), [])
        self.assertEqual(policy_excel.read_policy_workbook(content), [])

    def test_preview_identifies_duplicates_and_conflicts_within_same_workbook(self):
        content = workbook([HEADERS, RULE, RULE, [RULE[0], 'Different requirement', 'Warning']])
        preview = policy_excel.preview_import(content, 'Selected', [], ['Selected'])
        self.assertEqual([row['status'] for row in preview['rows']], ['ready', 'duplicate', 'conflict'])
        self.assertEqual((preview['added'], preview['skipped'], preview['conflicts']), (1, 1, 1))

    def test_export_rejects_invalid_severity_instead_of_silently_changing_it(self):
        for severity in (0, 4, 1.5, 'unknown'):
            with self.subTest(severity=severity), self.assertRaises(ValueError):
                policy_excel.export_policy_workbook(TEMPLATE.read_bytes(), [{'severity': severity}])


class ExcelImportAPITests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('excel_import_server', Path(__file__).resolve().parents[1] / 'index_server.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, filename in [('POLICY', 'policy.json'), ('POLICY_SETS', 'policy_sets.json'), ('POLICY_CACHE', 'cache.json')]:
            patcher = patch.object(self.server, name, Path(directory.name) / filename)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.old = {'id': 12, 'title': 'Existing', 'instruction': 'Preserve me', 'severity': 2, 'policySet': 'Other', 'groups': ['private'], 'custom': {'keep': True}}
        self.server.save_json_atomic(self.server.POLICY, [self.old])
        self.server.save_json_atomic(self.server.POLICY_SETS, ['Selected', 'Other'])
        self.server.save_json_atomic(self.server.POLICY_CACHE, {'cache': 'old'})
        self.body = {'filename': 'rules.xlsx', 'contentBase64': base64.b64encode(workbook([HEADERS, RULE])).decode(), 'policySet': 'Selected'}

    def post(self, route, body):
        raw = json.dumps(body).encode()
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = route
        handler.server = SimpleNamespace(server_port=8084)
        handler.headers = {'Content-Length': str(len(raw)), 'Host': 'localhost:3000', 'Origin': 'https://localhost:3000', 'Content-Type': 'application/json'}
        handler.rfile = io.BytesIO(raw)
        handler.send_json = Mock()
        handler.do_POST()
        handler.send_json.assert_called_once()
        return handler.send_json.call_args.args

    def get(self, route):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = route
        handler.server = SimpleNamespace(server_port=8084)
        handler.headers = {'Host': 'localhost:3000', 'Origin': 'https://localhost:3000'}
        handler.send_json = Mock()
        handler.send_excel = Mock()
        handler.do_GET()
        return handler

    def test_download_only_exports_target_set_and_preserves_permissions(self):
        selected = dict(self.old, id=13, policySet='Selected', severity=3, tags=['限制'])
        self.server.save_json_atomic(self.server.POLICY, [self.old, selected])
        before = self.server.POLICY.read_bytes()
        handler = self.get('/policies/export?policySet=' + quote('Selected'))
        handler.send_json.assert_not_called()
        content, _ = handler.send_excel.call_args.args
        rows = policy_excel.read_policy_workbook(content)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['groups'], ['private'])
        self.assertEqual(rows[0]['severity'], 3)
        self.assertEqual(self.server.POLICY.read_bytes(), before)
        invalid = self.get('/policies/export?policySet=Missing')
        self.assertEqual(invalid.send_json.call_args.args[0], 400)
        invalid.send_excel.assert_not_called()
        template = self.get('/policies/import-template')
        self.assertEqual(template.send_excel.call_args.args[0], TEMPLATE.read_bytes())

    def test_download_headers_prevent_caching_and_return_complete_workbook(self):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        handler._cors_origin = 'https://localhost:3000'
        content = TEMPLATE.read_bytes()
        handler.send_excel(content, 'template.xlsx')
        headers = dict(call.args for call in handler.send_header.call_args_list)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(int(headers['Content-Length']), len(content))
        self.assertEqual(headers['Access-Control-Allow-Origin'], handler._cors_origin)
        self.assertEqual(handler.wfile.getvalue(), content)

    def test_preview_does_not_write_and_confirmation_appends_to_only_selected_set(self):
        before = self.server.POLICY.read_bytes()
        status, preview = self.post('/policies/import/preview', self.body)
        self.assertEqual(status, 200)
        self.assertEqual(preview['added'], 1)
        self.assertEqual(self.server.POLICY.read_bytes(), before)
        self.assertTrue(self.server.POLICY_CACHE.exists())
        status, result = self.post('/policies/import', dict(self.body, previewToken=preview['previewToken']))
        self.assertEqual(status, 200)
        self.assertEqual(result['added'], 1)
        rules = self.server.load_policies()
        self.assertEqual(rules[0], self.old)
        self.assertEqual(rules[1]['policySet'], 'Selected')
        self.assertEqual(rules[1]['severity'], 1)
        self.assertEqual(rules[1]['groups'], [])
        self.assertGreater(rules[1]['id'], self.old['id'])
        self.assertFalse(self.server.POLICY_CACHE.exists())

    def test_repeat_upload_is_skipped_and_does_not_duplicate_rules(self):
        _, preview = self.post('/policies/import/preview', self.body)
        self.post('/policies/import', dict(self.body, previewToken=preview['previewToken']))
        _, preview = self.post('/policies/import/preview', self.body)
        self.assertEqual(preview['added'], 0)
        self.assertEqual(preview['skipped'], 1)
        self.assertEqual(len(self.server.load_policies()), 2)

    def test_import_id_does_not_collide_with_existing_numeric_string_id(self):
        self.server.save_json_atomic(self.server.POLICY, [dict(self.old, id='1')])
        _, preview = self.post('/policies/import/preview', self.body)
        status, _ = self.post('/policies/import', dict(self.body, previewToken=preview['previewToken']))
        self.assertEqual(status, 200)
        ids = [str(rule['id']).strip() for rule in self.server.load_policies()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_same_name_with_changed_content_is_a_conflict_and_nothing_is_written(self):
        old = dict(self.old, title=RULE[0], policySet='Selected')
        self.server.save_json_atomic(self.server.POLICY, [old])
        before = self.server.POLICY.read_bytes()
        status, result = self.post('/policies/import/preview', self.body)
        self.assertEqual(status, 200)
        self.assertEqual(result['conflicts'], 1)
        status, _ = self.post('/policies/import', dict(self.body, previewToken=result['previewToken']))
        self.assertEqual(status, 409)
        self.assertEqual(self.server.POLICY.read_bytes(), before)

    def test_policy_changes_after_preview_require_preview_again(self):
        _, preview = self.post('/policies/import/preview', self.body)
        changed = dict(self.old, instruction='Updated while the import preview was open')
        self.server.save_json_atomic(self.server.POLICY, [changed])
        status, _ = self.post('/policies/import', dict(self.body, previewToken=preview['previewToken']))
        self.assertEqual(status, 409)
        self.assertEqual(self.server.load_policies(), [changed])

    def test_missing_target_bad_encoding_and_invalid_rows_never_change_files(self):
        before = self.server.POLICY.read_bytes()
        for change in ({'policySet': 'Missing'}, {'contentBase64': '!invalid!'}, {'filename': 'rules.xls'}, {'contentBase64': base64.b64encode(workbook([HEADERS, ['Bad', '', 'Critical']])).decode()}):
            status, _ = self.post('/policies/import/preview', dict(self.body, **change))
            self.assertIn(status, [400, 409])
            self.assertEqual(self.server.POLICY.read_bytes(), before)

    def test_commit_requires_preview_token_and_cache_failure_preserves_policies(self):
        status, _ = self.post('/policies/import', self.body)
        self.assertEqual(status, 409)
        _, preview = self.post('/policies/import/preview', self.body)
        before = self.server.POLICY.read_bytes()
        with patch.object(Path, 'unlink', side_effect=PermissionError('Cache busy')):
            status, _ = self.post('/policies/import', dict(self.body, previewToken=preview['previewToken']))
        self.assertEqual(status, 500)
        self.assertEqual(self.server.POLICY.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
