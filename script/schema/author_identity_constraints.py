"""Integrate reviewed identity protocol columns/checks into the compact source DDL.

This is an offline source author. It never connects to or mutates a database.
"""
from pathlib import Path
import json
import re

from compact_identity_ddl import (WORKFLOW_KINDS, AUDIT_KINDS, RUNTIME_NAMESPACES,
                                  FIELDS, lookup_columns, closed_object)

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'sql/mysql/compact/baseline/30-operations.sql'
LEGACY = {
    'DETECTION_IDENTITY_CONTROL': 'detection_identity_control',
    'DETECTION_IDENTITY_SOURCE_CONTROL': 'detection_identity_source_control',
    'DETECTION_IDENTITY_BINDING': 'detection_identity_binding',
    'DETECTION_IDENTITY_COMMAND': 'detection_identity_command',
    'DETECTION_IDENTITY_MAP_BATCH': 'detection_identity_mapping_batch',
    'DETECTION_IDENTITY_MAP_ITEM': 'detection_identity_mapping_item',
    'DETECTION_IDENTITY_REPORT': 'detection_identity_reconciliation_report',
    'DETECTION_ASSIGNMENT_IDENTITY': 'detection_assignment_identity_event',
    'DETECTION_IDENTITY_BINDING_EVENT': 'detection_identity_binding_event',
    'DETECTION_IDENTITY_RECON_ITEM': 'detection_identity_reconciliation_item',
    'DETECTION_IDENTITY_MISSING_NAME': 'detection_identity_missing_name_evidence',
}


def relax(sql, name, exception):
    pattern = re.compile(r'(?m)^(\s*CONSTRAINT ' + re.escape(name) + r' CHECK \()(.*)(\),?\s*)$')
    found = pattern.search(sql)
    if not found:
        raise ValueError('Missing baseline invariant: ' + name)
    # Repeated authorship must not append the same narrowly scoped exception twice.
    expression = found.group(2)
    if exception in expression:
        return sql
    return sql[:found.start()] + found.group(1) + '(' + expression + ') OR (' + exception + ')' + found.group(3) + sql[found.end():]


def checks(kind, discriminator):
    terms = [closed_object(kind)]
    name = 'ck_id_' + ('runtime_' if discriminator == 'namespace' else '') + kind.removeprefix('DETECTION_').lower()
    return f"CONSTRAINT {name} CHECK ({discriminator}<>'{kind}' OR COALESCE((" + ' AND '.join(terms) + '),0)=1)'


def main():
    sql = BASELINE.read_text(encoding='utf8')
    kind_line = next(line for line in sql.splitlines() if 'CONSTRAINT ck_workflow_kind CHECK' in line)
    missing = [kind for kind in WORKFLOW_KINDS if "'" + kind + "'" not in kind_line]
    if missing:
        replacement = kind_line.rstrip().removesuffix(')),') + ',' + ','.join("'" + kind + "'" for kind in missing) + ')),'
        sql = sql.replace(kind_line, replacement)
    legacy_runtime = "created_at IS NULL AND payload_json IS NOT NULL AND payload_version=1 AND (" + ' OR '.join(
        f"(namespace='{kind}' AND BINARY JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.legacySource'))=BINARY '{LEGACY[kind]}')"
        for kind in RUNTIME_NAMESPACES) + ')'
    sql = relax(sql, 'ck_runtime_updated', legacy_runtime)
    imported_item = "kind='DETECTION_IDENTITY_MAP_ITEM' AND BINARY legacy_source=BINARY 'detection_identity_mapping_item' AND legacy_key IS NOT NULL"
    for name in ('ck_workflow_created_time', 'ck_workflow_updated_time'):
        sql = relax(sql, name, imported_item)
    legacy_owner = "owner_user_id=0 AND actor_user_id IS NULL AND legacy_key IS NOT NULL AND (" + ' OR '.join(
        f"(kind='{kind}' AND BINARY legacy_source=BINARY '{LEGACY[kind]}')" for kind in WORKFLOW_KINDS) + ')'
    sql = relax(sql, 'ck_workflow_owner', legacy_owner)
    # This source row never had an event timestamp; its original absence must survive import.
    sql = relax(sql, 'ck_audit_event_time', "kind='DETECTION_IDENTITY_RECON_ITEM' AND BINARY legacy_source=BINARY 'detection_identity_reconciliation_item' AND legacy_key IS NOT NULL")
    for table, kinds, discriminator in (('runtime_state', RUNTIME_NAMESPACES, 'namespace'),
                                         ('workflow_instance', WORKFLOW_KINDS, 'kind'),
                                         ('audit_event', AUDIT_KINDS, 'kind')):
        pattern = re.compile(r'(CREATE TABLE ' + table + r' \()(.*?)(\n\) ENGINE=)', re.S)
        found = pattern.search(sql)
        if not found:
            raise ValueError('Missing target table ' + table)
        body = re.sub(r'[ \t\r\n]*,\r?\n -- BEGIN GENERATED IDENTITY.*?\n -- END GENERATED IDENTITY', '', found.group(2), flags=re.S).rstrip()
        additions = lookup_columns(table) + [checks(kind, discriminator) for kind in kinds]
        # A previous generated section ends in a line comment; put the comma
        # on its own SQL line so the next column cannot disappear into a CHECK.
        body = re.sub(r'(?m)^(\s*-- END GENERATED [^\r\n,]+),\s*$', r'\1\n ,', body)
        body += '\n ,\n -- BEGIN GENERATED IDENTITY\n ' + ',\n '.join(additions) + '\n -- END GENERATED IDENTITY'
        sql = sql[:found.start()] + found.group(1) + body + found.group(3) + sql[found.end():]
    BASELINE.write_text(sql, encoding='utf8', newline='\n')
    enum_path = ROOT / 'doorhandle-framework/src/main/java/com/ruanzhu/doorhandle/framework/persistence/workflow/WorkflowKind.java'
    enum = enum_path.read_text(encoding='utf8')
    absent = [kind for kind in WORKFLOW_KINDS if not re.search(r'\b' + kind + r'\b', enum)]
    if absent:
        enum = enum.rstrip().removesuffix('}').rstrip() + ',\n    ' + ', '.join(absent) + '\n}\n'
        enum_path.write_text(enum, encoding='utf8', newline='\n')
    contract_path = ROOT / 'docs/database/compact-schema-contract.json'
    contract = json.loads(contract_path.read_text(encoding='utf8'))
    source = 'detection_identity_missing_name_evidence'
    for mapping in contract['mapping']:
        if mapping['target'] != 'audit_event' and source in mapping['sources']:
            mapping['sources'].remove(source)
        elif mapping['target'] == 'audit_event' and source not in mapping['sources']:
            mapping['sources'].append(source)
            mapping['sources'].sort()
    for route in contract.get('additionalRoutes', []):
        if route.get('source') == source:
            route['target'] = 'audit_event'
            route['rule'] = 'Retain immutable missing-name evidence as DETECTION_IDENTITY_MISSING_NAME; do not create a fabricated content asset anchor.'
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_SQL_EXECUTED', 'identityKinds': len(FIELDS)}))


if __name__ == '__main__':
    main()
