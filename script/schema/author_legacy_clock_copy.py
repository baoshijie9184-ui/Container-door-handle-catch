"""Compile explicit UNRESOLVED clock support into reviewed copy SQL/DDL sources.

Source authoring only: no application, database, cloud or test execution. Fixed
copy inputs remain separate source templates so rebuilding is deterministic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re

from build_compact_schema import ROOT, parse_table, split_top_level, without_comments


PROTOCOL = 'doorhandle-legacy-clock-v1'
COPIES = ('22-skills.sql', '23-skill-downloads.sql', '24-chat-evidence.sql', '25-agent-runs.sql',
          '31-conversation-inbox.sql', '32-agent-journal.sql', '33-sdk-checkpoint.sql',
          '34-quality-report-workflow.sql', '36-memory-governance.sql',
          '40-model-operations.sql', '41-infra-operations.sql', '43-workspace.sql',
          '44-confirmation-actions.sql', '48-mcp.sql')
TABLE_FILES = {'content_asset': '20-content.sql', 'content_revision': '20-content.sql',
               'content_link': '20-content.sql', 'agent_run': '25-agent.sql',
               'agent_connector': '25-agent.sql', 'runtime_state': '30-operations.sql',
               'workflow_instance': '30-operations.sql', 'audit_event': '30-operations.sql'}
SCHEMA_FILE = ROOT / 'docs/database/legacy-clock-source-catalog.json'
VALIDATION = '@compact_validation_wall_offset'
UNKNOWN = '@compact_source_clock_unresolved'
GENERATED = '-- Generated explicit legacy-clock protocol by author_legacy_clock_copy.py.'
RAW_TIME = {'legacy_created_at', 'mcp_source_created_at', 'mcp_source_updated_at'}
PROJECTION_CLOCKS = {'chat_message': {'execution_created_at', 'workspace_snapshot_created_at'}}


def q(value):
    return "'" + value.replace('\\', '\\\\').replace("'", "''") + "'"


def paren(text, opening):
    depth, quote, i = 1, None, opening + 1
    while i < len(text):
        char = text[i]
        if quote:
            if char == '\\':
                i += 2; continue
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2; continue
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError('Unbalanced source SQL expression')


def keyword(text, wanted):
    """Find a keyword outside strings and nested expressions."""
    quote, depth, i = None, 0, 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == '\\':
                i += 2; continue
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2; continue
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and re.match(r'\b' + wanted + r'\b', text[i:], re.I):
            return i
        i += 1
    return -1


def parsed_insert(statement):
    match = re.match(r'INSERT\s+INTO\s+`?([a-z_]+)`?\s*\(', statement, re.I)
    if not match or match[1] not in TABLE_FILES:
        return None
    end = paren(statement, match.end() - 1)
    columns = [value.strip().strip('`') for value in split_top_level(statement[match.end():end], ',')]
    rest = statement[end + 1:].strip()
    if not re.match(r'SELECT\s+', rest, re.I):
        return None
    start = re.match(r'SELECT\s+', rest, re.I).end()
    position = keyword(rest[start:], 'FROM')
    if position < 0:
        return None
    position += start
    expressions = list(split_top_level(rest[start:position], ','))
    if expressions and expressions[0].startswith('DISTINCT '):
        expressions[0] = expressions[0][9:]
        distinct = 'DISTINCT '
    else:
        distinct = ''
    if len(columns) != len(expressions):
        raise ValueError('Every target column must have one original source expression: ' + match[1])
    tail = rest[position:]
    sources = {alias or name: name for name, alias in re.findall(
        r'`__SOURCE_SCHEMA__`\.`?([a-z_]+)`?(?:\s+(?!WHERE\b|ORDER\b|JOIN\b|ON\b|LEFT\b|FOR\b|GROUP\b)([a-z][a-z0-9_]*))?', tail, re.I)}
    if not sources:
        return None
    mapping = dict(zip(columns, expressions))
    origin = mapping.get('legacy_source', '')
    origin = origin[1:-1] if re.fullmatch(r"'[a-z_]+\'", origin) else next(iter(sources.values()))
    # Synthetic historical labels never masquerade as an original source table.
    if origin not in sources.values():
        origin = next(iter(sources.values()))
    alias = next(key for key, value in sources.items() if value == origin)
    return match[1], columns, expressions, tail, origin, alias, sources, distinct


def catalog():
    value = json.loads(SCHEMA_FILE.read_text('utf8'))
    if value.get('algorithm') != 'MYSQL_JSON_SHA256_V1':
        raise ValueError('Unreviewed full-row source encoding')
    if value.get('sourceFileDigestEncoding') != 'UTF8_LF_WITHOUT_BOM':
        raise ValueError('Original source DDL digest encoding must be explicit')
    for source in value['tables'].values():
        for name, expected in source['sourceFiles'].items():
            normalized = (ROOT / name).read_text(encoding='utf-8-sig').encode('utf8')
            if hashlib.sha256(normalized).hexdigest() != expected:
                raise ValueError('Original source DDL changed; review the complete clock catalog: ' + name)
    return value['tables']


def expression(source, alias, column):
    value = alias + '.`' + column + '`'
    kind = source['columns'][column]['type'].upper()
    if kind.startswith(('DATETIME', 'TIMESTAMP', 'DATE', 'TIME', 'JSON')):
        return 'CAST(' + value + ' AS CHAR CHARACTER SET utf8mb4)'
    if kind.startswith(('BINARY', 'VARBINARY', 'BLOB', 'TINYBLOB', 'MEDIUMBLOB', 'LONGBLOB')):
        return 'HEX(' + value + ')'
    return value


def object_sql(parts):
    return 'JSON_OBJECT(' + ','.join(q(name) + ',' + value for name, value in parts) + ')'


def sidecar(name, alias, sources):
    source = sources[name]
    row = object_sql([(column, expression(source, alias, column)) for column in source['columns']])
    keys = object_sql([(column, expression(source, alias, column)) for column in source['primaryKey']])
    times = object_sql([(column, 'CAST(' + alias + '.`' + column + '` AS CHAR)')
                        for column in source['columns'] if source['columns'][column]['type'].upper().startswith(('DATETIME', 'TIMESTAMP'))])
    return object_sql([('protocol', q(PROTOCOL)), ('status', "'UNRESOLVED'"), ('sourceTable', q(name)),
                       ('sourceKey', keys), ('sourceSnapshotSha256', "'__SOURCE_SNAPSHOT_SHA256__'"),
                       ('sourceRowSha256', 'SHA2(CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4),256)'),
                       ('sourceWallTimes', times)])


def targets():
    result = {}
    for filename in set(TABLE_FILES.values()):
        for statement in split_top_level(without_comments((ROOT / 'sql/mysql/compact/baseline' / filename).read_text('utf8')), ';'):
            if statement.startswith('CREATE TABLE '):
                table = parse_table(statement, filename)
                result[table['name']] = table
    return result


def clock_columns(table):
    return {column for column, value in table['columns'].items()
            if value['type'].upper().startswith(('DATETIME', 'TIMESTAMP')) and column not in RAW_TIME}


def normalized(value):
    return 'IF(' + UNKNOWN + ',NULL,' + value + ')'


def payload_offsets(text):
    # Only persisted/expected JSON offset values are nullable. The separately
    # named validation offset proves wall-value round trips and is never evidence.
    text = re.sub(r"('sourceUtcOffset'\s*,\s*)" + re.escape(VALIDATION),
                  lambda m: m[1] + normalized(VALIDATION), text)
    # Some typed payload fields (for example memory legacyUpdatedAt) contain
    # normalized absolute times rather than raw wall evidence.
    position = 0
    pattern = re.compile(r'JSON_OBJECT\s*\(', re.I)
    while match := pattern.search(text, position):
        end = paren(text, match.end() - 1) + 1
        value = text[match.start():end]
        conversions = []
        for conversion in re.finditer(r'CONVERT_TZ\s*\(', value, re.I):
            stop = paren(value, conversion.end() - 1) + 1
            conversions.append((conversion.start(), stop))
        for begin, stop in reversed(conversions):
            value = value[:begin] + normalized(value[begin:stop]) + value[stop:]
        text = text[:match.start()] + value + text[end:]
        position = match.start() + len(value)
    return text


def workspace_manifest(text):
    pattern = re.compile(r'JSON_OBJECT\s*\(', re.I)
    result, position = [], 0
    while match := pattern.search(text, position):
        end = paren(text, match.end() - 1)
        body = text[match.end():end]
        parts = list(split_top_level(body, ','))
        keys = parts[::2]
        if keys == ["'folder'", "'createdAtSource'", "'sourceUtcOffset'"]:
            values = dict(zip(keys, parts[1::2]))
            raw = re.search(r'DATE_FORMAT\(([^,]+),', values["'createdAtSource'"], re.I)
            if raw is None:
                raise ValueError('Workspace source wall-time expression changed')
            old = text[match.start():end + 1]
            new = object_sql([('protocolVersion', '2'), ('folder', values["'folder'"]),
                              ('createdAtSource', 'CAST(' + raw[1] + ' AS CHAR)'), ('clockStatus', "'UNRESOLVED'")])
            result += [text[position:match.start()], 'IF(' + UNKNOWN + ',' + new + ',' + old + ')']
        else:
            result.append(text[position:end + 1])
        position = end + 1
    result.append(text[position:])
    return ''.join(result)


def projection_checks(statement, table_catalog):
    """Rewrite only target comparisons; source validation remains a wall check."""
    aliases = {}
    for table, alias in re.findall(r'\b(?:FROM|JOIN)\s+`?([a-z_]+)`?\s+([a-z][a-z0-9_]*)', statement, re.I):
        if table in TABLE_FILES or table in PROJECTION_CLOCKS:
            aliases[alias] = table
    for alias, table in aliases.items():
        clocks = PROJECTION_CLOCKS[table] if table in PROJECTION_CLOCKS else clock_columns(table_catalog[table])
        for column in clocks | {'legacy_utc_offset', 'mcp_source_utc_offset'}:
            pattern = re.compile(r'(?P<left>(?:BINARY\s+)?' + re.escape(alias) + r'\.`?' + re.escape(column)
                                 + r'`?\s*)(?P<op><=>|<>|!=|=)\s*(?P<binary>BINARY\s+)?(?P<rhs>(?:\(\s*)*(?:(?:CONVERT_TZ|IF|COALESCE)\s*\(|' + re.escape(VALIDATION) + r'\b))', re.I)
            position = 0
            while match := pattern.search(statement, position):
                if '(' in match['rhs']:
                    # Full-row reconciliation wraps source expressions in
                    # parentheses. Normalize that complete RHS just like the
                    # INSERT projection, including nested grouping.
                    opening = statement.index('(', match.start('rhs'))
                    end = paren(statement, opening) + 1
                else:
                    end = match.end('rhs')
                right = statement[match.start('rhs'):end]
                right = (match['binary'] or '') + normalized(right)
                left = match['left'].rstrip()
                replacement = ('NOT(' + left + '<=>' + right + ')' if match['op'] in ('<>', '!=')
                               else '(' + left + '<=>' + right + ')')
                statement = statement[:match.start()] + replacement + statement[end:]
                position = match.start() + len(replacement)
    return statement


def chat_payloads(statement):
    """Keep V1 keys, with exact raw wall values and a JSON null offset."""
    pattern = re.compile(r"('createdAtSource'\s*,\s*)DATE_FORMAT\s*\(", re.I)
    position = 0
    while match := pattern.search(statement, position):
        opening = statement.index('(', match.end() - 1)
        end = paren(statement, opening) + 1
        parts = list(split_top_level(statement[opening + 1:end - 1], ','))
        if len(parts) != 2 or not re.fullmatch(r's\.created_at', parts[0], re.I):
            raise ValueError('Reviewed chat raw wall source changed')
        old = statement[match.end(1):end]
        value = 'IF(' + UNKNOWN + ',CAST(' + parts[0] + ' AS CHAR),' + old + ')'
        statement = statement[:match.end(1)] + value + statement[end:]
        position = match.end(1) + len(value)
    return statement


def chat_projection_writes(statement):
    if not re.match(r'UPDATE\s+chat_message\s+', statement, re.I):
        return statement
    pattern = re.compile(r'(\bm\.(?:execution_created_at|workspace_snapshot_created_at)\s*=\s*)CONVERT_TZ\s*\(', re.I)
    position = 0
    while match := pattern.search(statement, position):
        end = paren(statement, statement.index('(', match.end() - 1)) + 1
        expression = statement[match.end(1):end]
        value = normalized(expression)
        statement = statement[:match.end(1)] + value + statement[end:]
        position = match.end(1) + len(value)
    return statement


def identity_join(table, mapping, table_catalog):
    definition = table_catalog[table]
    candidates = []
    if 'legacy_source' in mapping:
        for key in ('legacy_id', 'legacy_key'):
            if key in mapping:
                candidates.append(['legacy_source', key])
    if table == 'content_link' and mapping.get('link_kind') == "'CONNECTOR_RETENTION'":
        # connector_retention_gate is a generated discriminator in this unique
        # key; its value follows the explicit constant link_kind projection.
        candidates.append(['link_kind', 'subject_id', 'target_id'])
    candidates += [definition['primaryKey'], *definition['uniqueKeys']]
    for keys in candidates:
        if keys and all(key in mapping and mapping[key] != 'NULL' for key in keys):
            return ' AND '.join('BINARY clock_target.`' + key + '`<=>BINARY ' + mapping[key] for key in keys)
    raise ValueError('No explicit target identity for complete clock provenance: ' + table)


def compile_copy(text, filename, sources=None):
    if text.startswith(GENERATED):
        raise ValueError('Compile the fixed-source template, never an already generated copy')
    sources = catalog() if sources is None else sources
    table_catalog = targets()
    tokens = set(re.findall(r'__SOURCE_[A-Z_]+_OFFSET__', text))
    if len(tokens) != 1:
        raise ValueError('Each reviewed legacy clock segment has exactly one source domain')
    token = tokens.pop()
    setup = [GENERATED,
        '-- validation_wall_offset is ONLY a zero-shift wall-value validator when unresolved.',
        '-- It is never persisted as a source offset or used to manufacture UTC.',
        'SET ' + UNKNOWN + "=BINARY '" + token + "'=BINARY 'UNRESOLVED';",
        'SET ' + VALIDATION + '=IF(' + UNKNOWN + ",'+00:00','" + token + "');"]
    output, final_guards = [], []
    guard_match = re.search(r'CREATE TEMPORARY TABLE\s+([a-z_]+guard)\s*\(', text, re.I)
    if guard_match is None:
        raise ValueError('A reviewed copy rejection guard is required')
    guard = guard_match[1]
    statements = list(split_top_level(without_comments(text), ';'))
    for statement in statements:
        original = parsed_insert(statement)
        statement = statement.replace(q(token), VALIDATION)
        statement = payload_offsets(statement)
        statement = workspace_manifest(statement)
        if filename == '24-chat-evidence.sql':
            statement = chat_projection_writes(chat_payloads(statement))
        if original:
            table, columns, expressions, tail, origin, alias, aliases, distinct = original
            if origin not in sources:
                raise ValueError('Original typed source shape is absent: ' + origin)
            clocks = [key for key, value in sources[origin]['columns'].items()
                      if value['type'].upper().startswith(('DATETIME', 'TIMESTAMP'))]
            updated = parsed_insert(statement)
            _, columns, expressions, tail, _, _, _, _ = updated
            new = []
            for column, value in zip(columns, expressions):
                if column in clock_columns(table_catalog[table]) and value != 'NULL' and clocks:
                    value = normalized(value)
                elif column in ('legacy_utc_offset', 'mcp_source_utc_offset'):
                    value = normalized(value)
                new.append(value)
            clock = 'IF(' + UNKNOWN + ',' + sidecar(origin, alias, sources) + ',NULL)' if clocks else 'NULL'
            if 'legacy_clock_json' in columns:
                new[columns.index('legacy_clock_json')] = clock
            else:
                columns.append('legacy_clock_json'); new.append(clock)
            statement = 'INSERT INTO ' + table + '(' + ','.join(columns) + ') SELECT ' + distinct + ','.join(new) + ' ' + tail
            if clocks:
                mapping = dict(zip(columns, new))
                join = identity_join(table, mapping, table_catalog)
                boundary = min([p for p in (keyword(tail, 'ORDER'), keyword(tail, 'ON DUPLICATE'), keyword(tail, 'FOR')) if p >= 0], default=len(tail))
                domain_tail = tail[:boundary].rstrip()
                where = keyword(domain_tail, 'WHERE')
                if where >= 0:
                    base, condition = domain_tail[:where], domain_tail[where + 5:]
                    condition = '(' + condition.strip() + ') AND '
                else:
                    base, condition = domain_tail, ''
                identity = 'clock_target.' + ('namespace' if table == 'runtime_state' else 'id')
                verified = ['NOT(clock_target.legacy_clock_json<=>' + clock + ')']
                temporal_columns = {name for name, metadata in table_catalog[table]['columns'].items()
                                    if metadata['type'].upper().startswith(('DATETIME', 'TIMESTAMP'))}
                for column, value in mapping.items():
                    if column in temporal_columns:
                        # DATETIME(0) and DATETIME(6) can hold the same instant
                        # with different text. Compare all temporal precision
                        # as typed values; raw text and JSON remain byte exact.
                        verified.append('NOT(clock_target.`' + column + '`<=>' + value + ')')
                    elif column in RAW_TIME | {'legacy_utc_offset', 'mcp_source_utc_offset', 'payload_json', 'manifest_json'}:
                        verified.append('NOT(BINARY clock_target.`' + column + '`<=>BINARY ' + value + ')')
                final_guards.append('INSERT INTO ' + guard + ' SELECT IF(COUNT(*)=0,1,0) ' + base
                    + ' LEFT JOIN ' + table + ' clock_target ON ' + join + ' WHERE ' + condition + '(' + identity
                    + ' IS NULL OR ' + ' OR '.join(verified) + ')')
        elif statement.startswith('INSERT INTO ' + guard):
            statement = projection_checks(statement, table_catalog)
        if statement.upper() == 'START TRANSACTION':
            output.append(statement)
            output.append('INSERT INTO ' + guard + " SELECT IF(NOT " + UNKNOWN
                + " OR REGEXP_LIKE('__SOURCE_SNAPSHOT_SHA256__','^[a-f0-9]{64}$','c'),1,0)")
            for name in ({'25-agent-runs.sql': ('agent_research_answer',), '23-skill-downloads.sql': ('agent_skill_download_lease',)}.get(filename, ())):
                output.append('INSERT INTO ' + guard + ' SELECT IF(NOT ' + UNKNOWN
                    + ' OR (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.' + name + ')=0,1,0)')
            continue
        if statement.upper() == 'COMMIT':
            output += final_guards
        output.append(statement)
    rendered = '\n'.join(setup) + '\n' + ';\n'.join(output) + ';\n'
    # Comment masking preserves source positions. These reviewed templates do
    # not contain multiline data literals; blank masked comments are not data.
    return re.sub(r'(?m)^[ \t]+$', '', rendered)


def write_copy(filename, text):
    source = ROOT / 'sql/mysql/compact/copy-fixed-clock' / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(text.encode('utf8'))
    (ROOT / 'sql/mysql/compact/copy' / filename).write_bytes(compile_copy(text, filename).encode('utf8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for filename in COPIES:
        source = ROOT / 'sql/mysql/compact/copy-fixed-clock' / filename
        actual = ROOT / 'sql/mysql/compact/copy' / filename
        expected = compile_copy(source.read_text('utf8'), filename)
        if args.check:
            if actual.read_text('utf8') != expected:
                raise ValueError('Stale generated legacy-clock copy: ' + filename)
        else:
            actual.write_bytes(expected.encode('utf8'))
        print(filename)


if __name__ == '__main__':
    main()
