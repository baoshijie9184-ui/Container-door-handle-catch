"""Add fixed-offset conversion guards to reviewed copy sources; never execute SQL.

CONVERT_TZ can return the input unchanged outside its supported conversion range.
The copy must prove the requested microsecond shift, including for nullable dates.
The explicit source-column inventory prevents alias reuse from hiding a timestamp.
"""
from pathlib import Path
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[2]
BEGIN = '-- BEGIN reviewed fixed-offset conversion guards'
END = '-- END reviewed fixed-offset conversion guards'
COPIES = {
    '21-research.sql': ('RESEARCH', {
        'agent_research_source': ('fetched_at', 'expires_at'),
        'agent_research_content_purge': ('purged_at',)}),
    '22-skills.sql': ('SKILL', {
        'agent_learned_skill': ('created_at', 'updated_at', 'activated_at', 'last_used_at'),
        'agent_skill_version': ('created_at', 'submitted_at', 'reviewed_at'),
        'agent_skill_eval': ('created_at',), 'agent_skill_audit': ('created_at',),
        'agent_skill_import': ('created_at',), 'agent_skill_source': ('captured_at',)}),
    '23-skill-downloads.sql': ('SKILL', {
        'agent_skill_download': ('created_at', 'updated_at'),
        'agent_skill_download_event': ('created_at',),
        'agent_skill_download_lease': ('created_at', 'updated_at', 'lease_expires_at'),
        'agent_skill_storage_command': ('created_at', 'updated_at')}),
    '25-agent-runs.sql': ('AGENT', {
        'agent_run': ('started_at', 'ended_at', 'heartbeat_at', 'lease_expires_at'),
        'agent_research_answer': ('recorded_at',)}),
    '26-model-configuration.sql': ('MODEL', {
        'agent_model_configuration': ('created_at', 'published_at'),
        'agent_model_config_command': ('created_at',),
        'agent_model_json_probe': ('created_at',), 'agent_model_revoked_key': ('created_at',)}),
    '31-conversation-inbox.sql': ('INBOX', {
        'agent_conversation_input': ('created_at', 'updated_at', 'expires_at'),
        'agent_conversation_input_audit': ('created_at',)}),
    '32-agent-journal.sql': ('AGENT', {'agent_run_event': ('occurred_at',)}),
    '33-sdk-checkpoint.sql': ('SDK', {'agent_workbench_sdk_state': ('updated_at',)}),
    '34-quality-report-workflow.sql': ('REPORT', {
        'detection_report_command': ('created_at',),
        'detection_report_confirmation': ('expires_at', 'used_at'),
        'detection_report_outbox': ('created_at', 'next_attempt_at', 'lease_expires_at', 'delivered_at'),
        'detection_report_event_state': ('updated_at',),
        'detection_report_event_receipt': ('consumed_at',),
        'detection_report_audit': ('created_at',), 'detection_report_agent_origin': ('created_at',)}),
}


def author():
    spec = importlib.util.spec_from_file_location('compact_parser', ROOT / 'script/schema/build_compact_schema.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    expected = {table for _, tables in COPIES.values() for table in tables}
    source_columns = {}
    # Read only checked-in original MySQL declarations, never work/ checkouts or a database.
    for source in (ROOT / 'sql/mysql').glob('*.sql'):
        for statement in parser.split_top_level(parser.without_comments(source.read_text(encoding='utf-8-sig')), ';'):
            match = re.match(r'CREATE TABLE(?: IF NOT EXISTS)?\s+`?([a-z_]+)`?\s*\(', statement, re.I)
            if match and match.group(1) in expected:
                definition = parser.parse_table(statement.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1), source.name)
                source_columns.setdefault(match.group(1), set()).update(definition['columns'])
            alteration = re.match(r'ALTER TABLE\s+`?([a-z_]+)`?\s+(.+)', statement, re.I | re.S)
            if alteration and alteration.group(1) in expected:
                for clause in parser.split_top_level(alteration.group(2), ','):
                    added = re.match(r'ADD\s+COLUMN\s+(?:IF NOT EXISTS\s+)?`?([a-z_]+)`?\s+', clause, re.I)
                    if added:
                        source_columns.setdefault(alteration.group(1), set()).add(added.group(1))
    changes = {}
    for filename, (domain, tables) in COPIES.items():
        path = ROOT / 'sql/mysql/compact/copy' / filename
        text = path.read_text(encoding='utf-8')
        offset = f'__SOURCE_{domain}_OFFSET__'
        if offset not in text or text.count('START TRANSACTION;') != 1:
            raise ValueError(f'Unreviewed copy structure: {filename}')
        guard = re.search(r'CREATE TEMPORARY TABLE\s+([a-z_]+guard)\s*\(', text)
        if guard is None or guard.start() > text.index('START TRANSACTION;'):
            raise ValueError(f'Expected a pre-existing one-column rejection guard: {filename}')
        name = guard.group(1)
        seconds = (f"(IF(LEFT('{offset}',1)='-',-1,1)*(CAST(SUBSTRING('{offset}',2,2) AS UNSIGNED)*3600"
                   f"+CAST(SUBSTRING('{offset}',5,2) AS UNSIGNED)*60))")
        lines = [BEGIN,
                 f"INSERT INTO {name} SELECT IF(REGEXP_LIKE('{offset}','^[+-][0-9]{{2}}:[0-9]{{2}}$','c') "
                 f"AND CONVERT_TZ('2026-01-01','{offset}','+00:00') IS NOT NULL,1,0);"]
        for table, columns in tables.items():
            if not set(columns).issubset(source_columns.get(table, set())):
                raise ValueError(f'Original DDL does not prove {filename}: {table} {columns}')
            failures = []
            for column in columns:
                original = f's.{column}'
                converted = f"CONVERT_TZ({original},'{offset}','+00:00')"
                failures.append(f"({original} IS NOT NULL AND ({converted} IS NULL OR "
                                f"NOT(TIMESTAMPDIFF(MICROSECOND,{converted},{original})<=>({seconds}*1000000))))")
            lines.append(f"INSERT INTO {name} SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.{table} s WHERE "
                         + ' OR '.join(failures) + ');')
        lines.append(END)
        if BEGIN in text:
            if text.count(BEGIN) != 1 or text.count(END) != 1:
                raise ValueError(f'Ambiguous generated guard block: {filename}')
            text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END), lambda _: '\n'.join(lines), text, flags=re.S)
        else:
            text = text.replace('START TRANSACTION;', 'START TRANSACTION;\n' + '\n'.join(lines), 1)
        list(parser.split_top_level(parser.without_comments(text), ';'))
        changes[path] = text
    for path, text in changes.items():
        path.write_text(text, encoding='utf-8')
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_EXECUTED', 'copies': len(changes),
                      'timestampFields': sum(len(columns) for _, tables in COPIES.values() for columns in tables.values())}))


if __name__ == '__main__':
    author()
