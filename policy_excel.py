"""Read and write the bounded, text-only Excel format used for policy exchange."""
from io import BytesIO
import hashlib
import json
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_ROWS = 500
MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'m': MAIN}
SEVERITIES = {'critical': 1, 'warning': 2, 'informational': 3, '1': 1, '2': 2, '3': 3}
SEVERITY_LABELS = {1: 'Critical', 2: 'Warning', 3: 'Informational'}
HEADERS = ['Policy Title', 'Policy Instruction', 'Severity', 'Tags (optional)', 'Groups (optional)']
ALIASES = {
    '政策名称': 'title', 'policy title': 'title', 'title': 'title',
    '审核要求': 'instruction', 'policy instruction': 'instruction', 'instruction': 'instruction',
    'severity': 'severity', '级别': 'severity',
    '标签（选填）': 'tags', '标签': 'tags', 'tags': 'tags',
    'tags (optional)': 'tags', 'groups (optional)': 'groups', 'groups': 'groups',
    'permission groups': 'groups', 'permission groups (optional)': 'groups', '权限组（选填）': 'groups',
}


def _xml(archive, name):
    raw = archive.read(name)
    # The exchange format uses UTF-8 XML; DTDs and entity declarations are not needed.
    if b'\x00' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported Excel XML. Save the workbook as a standard .xlsx file.')
    return ET.fromstring(raw)


def _text(node):
    return ''.join(part.text or '' for part in node.iter(f'{{{MAIN}}}t')).strip()


def _list(value):
    return list(dict.fromkeys(item.strip() for item in re.split(r'[,，\n]', value) if item.strip()))


def read_policy_workbook(content):
    """Read Policies (or the first visible sheet); never evaluate formulas or links."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('Upload an .xlsx file no larger than 3 MB.')
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 256 or sum(item.file_size for item in entries) > 16 * 1024 * 1024:
                raise ValueError('Excel workbook is too large. Use the policy template.')
            if len({item.filename for item in entries}) != len(entries):
                raise ValueError('Excel workbook contains duplicate parts.')
            if any(item.flag_bits & 1 for item in entries):
                raise ValueError('Password-protected Excel files are not supported.')
            book = _xml(archive, 'xl/workbook.xml')
            sheets = [s for s in book.findall('m:sheets/m:sheet', NS) if s.get('state', 'visible') == 'visible']
            if not sheets:
                raise ValueError('The workbook needs a visible policy worksheet.')
            sheet = next((s for s in sheets if s.get('name') == 'Policies'), sheets[0])
            relationships = _xml(archive, 'xl/_rels/workbook.xml.rels')
            relation = next((r for r in relationships if r.get('Id') == sheet.get(f'{{{REL}}}id')), None)
            if relation is None or relation.get('TargetMode') == 'External':
                raise ValueError('The policy worksheet must be inside the Excel file.')
            target = relation.get('Target', '')
            part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not part.startswith('xl/') or not part.endswith('.xml'):
                raise ValueError('Unsupported worksheet location.')
            shared = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                shared = [_text(item) for item in _xml(archive, 'xl/sharedStrings.xml')]
            sheet_xml = _xml(archive, part)
            rows = {}
            for row in sheet_xml.findall('m:sheetData/m:row', NS):
                number = int(row.get('r', '0'))
                if number < 1 or number in rows:
                    raise ValueError('Invalid Excel row numbers.')
                values = {}
                for cell in row.findall('m:c', NS):
                    address = cell.get('r', '')
                    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', address)
                    if not match or int(match[2]) != number or match[1] in values:
                        raise ValueError(f'Row {number}: invalid cell address.')
                    if cell.find('m:f', NS) is not None:
                        raise ValueError(f'Row {number}: use plain text instead of formulas.')
                    kind = cell.get('t')
                    if kind == 'inlineStr':
                        value = _text(cell)
                    else:
                        value = cell.findtext('m:v', '', NS).strip()
                        if kind == 's':
                            index = int(value)
                            if index < 0 or index >= len(shared):
                                raise ValueError(f'Row {number}: invalid shared text.')
                            value = shared[index]
                        elif kind in {'e', 'b'} and value:
                            raise ValueError(f'Row {number}: use text values, not errors or booleans.')
                    if value:
                        values[match[1]] = value
                if values:
                    rows[number] = values
            header = rows.pop(1, {})
            columns = {}
            for column, label in header.items():
                key = ALIASES.get(label.casefold())
                if key is None or key in columns.values():
                    raise ValueError('Use the template headings: Policy Title, Policy Instruction, Severity, Tags (optional), Groups (optional).')
                columns[column] = key
            if not {'title', 'instruction', 'severity'} <= set(columns.values()):
                raise ValueError('The first row must contain policy title, instruction and Severity headings.')
            if len(rows) > MAX_ROWS:
                raise ValueError(f'Import no more than {MAX_ROWS} policies at a time.')
            result = []
            for number, values in sorted(rows.items()):
                if set(values) - set(columns):
                    raise ValueError(f'Row {number}: data appears outside the named columns.')
                record = {columns[column]: value for column, value in values.items()}
                if not record.get('title') or not record.get('instruction'):
                    raise ValueError(f'Row {number}: policy title and instruction are required.')
                severity = SEVERITIES.get(record.get('severity', '').casefold())
                if severity is None:
                    raise ValueError(f'Row {number}: Severity must be Critical, Warning or Informational (1, 2 or 3).')
                if len(record['title']) > 200 or len(record['instruction']) > 16000:
                    raise ValueError(f'Row {number}: title or instruction is too long (200 / 16000 characters).')
                result.append({
                    'row': number, 'title': record['title'], 'instruction': record['instruction'],
                    'severity': severity, 'tags': _list(record.get('tags', '')),
                    'groups': _list(record.get('groups', '')),
                })
            return result
    except (BadZipFile, KeyError, ET.ParseError, UnicodeError, IndexError, OverflowError) as error:
        raise ValueError('Cannot read this Excel file. Use the provided .xlsx template.') from error


def _identity(policy):
    return (str(policy.get('title', '')).strip().casefold(),
            str(policy.get('instruction', '')).strip(), str(policy.get('severity', 2)),
            tuple(sorted(policy.get('tags', []) or [])), tuple(sorted(policy.get('groups', []) or [])))


def preview_import(content, policy_set, policies, policy_sets):
    if not isinstance(policy_set, str) or policy_set not in policy_sets:
        raise ValueError('The target Policy Set no longer exists. Refresh and select it again.')
    incoming = read_policy_workbook(content)
    if not incoming:
        raise ValueError('The policy worksheet is empty. Add policies below the first row.')
    names = {}
    for policy in policies:
        if (str(policy.get('policySet') or '').strip() or 'General Policies') == policy_set:
            names.setdefault(str(policy.get('title', '')).strip().casefold(), []).append(policy)
    rows = []
    for incoming_row in incoming:
        policy = {**incoming_row, 'policySet': policy_set}
        existing = names.get(policy['title'].casefold(), [])
        status = 'ready'
        if any(_identity(item) == _identity(policy) for item in existing):
            status = 'duplicate'
        elif existing:
            status = 'conflict'
        rows.append({**policy, 'status': status})
        names.setdefault(policy['title'].casefold(), []).append(policy)
    digest = hashlib.sha256()
    digest.update(content)
    digest.update(json.dumps([policy_set, policies, policy_sets], sort_keys=True, ensure_ascii=False).encode())
    return {'rows': rows, 'added': sum(row['status'] == 'ready' for row in rows),
            'skipped': sum(row['status'] == 'duplicate' for row in rows),
            'conflicts': sum(row['status'] == 'conflict' for row in rows), 'previewToken': digest.hexdigest()}


def export_policy_workbook(template, policies):
    """Write text cells into the supplied template, retaining its style and dropdowns."""
    sheet = ET.Element(f'{{{MAIN}}}worksheet')
    views = ET.SubElement(sheet, f'{{{MAIN}}}sheetViews')
    view = ET.SubElement(views, f'{{{MAIN}}}sheetView', workbookViewId='0')
    ET.SubElement(view, f'{{{MAIN}}}pane', ySplit='1', topLeftCell='A2', state='frozen')
    columns = ET.SubElement(sheet, f'{{{MAIN}}}cols')
    for index, width in enumerate([26, 85, 22, 25, 28], 1):
        ET.SubElement(columns, f'{{{MAIN}}}col', min=str(index), max=str(index), width=str(width), customWidth='1')
    data = ET.SubElement(sheet, f'{{{MAIN}}}sheetData')
    values = [HEADERS]
    for item in policies:
        severity = SEVERITY_LABELS.get(SEVERITIES.get(str(item.get('severity', 2)).casefold()))
        if severity is None:
            raise ValueError('An existing policy has an invalid Severity. Correct it before exporting.')
        tags = item.get('tags') or []
        groups = item.get('groups') or []
        values.append([item.get('title', ''), item.get('instruction', ''), severity,
                       ', '.join(tags) if isinstance(tags, list) else str(tags),
                       ', '.join(groups) if isinstance(groups, list) else str(groups)])
    for number, row_values in enumerate(values, 1):
        row = ET.SubElement(data, f'{{{MAIN}}}row', r=str(number))
        for column, value in enumerate(row_values):
            cell = ET.SubElement(row, f'{{{MAIN}}}c', r=f'{chr(65+column)}{number}', t='inlineStr', s='1' if number == 1 else '2')
            text = ET.SubElement(ET.SubElement(cell, f'{{{MAIN}}}is'), f'{{{MAIN}}}t')
            text.text = str(value)
    output = BytesIO()
    with ZipFile(BytesIO(template)) as source, ZipFile(output, 'w', ZIP_DEFLATED) as destination:
        original = _xml(source, 'xl/worksheets/sheet1.xml')
        validation = original.find('m:dataValidations', NS)
        if validation is not None:
            sheet.append(validation)
        for item in source.infolist():
            destination.writestr(item.filename, ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
                                 if item.filename == 'xl/worksheets/sheet1.xml' else source.read(item.filename))
    return output.getvalue()
