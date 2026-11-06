"""Author the remaining chat, image fingerprint and owner-lock copies; source work only."""
from pathlib import Path
import json
import re

from build_compact_schema import ROOT, parse_table, without_comments

CATALOG = ROOT / 'docs/database/compact-support-source-map.json'
SOURCES = ('chat_project', 'chat_message', 'detection_image_fingerprint',
           'agent_research_storage_owner', 'agent_skill_download_owner')


def literal(value):
    if value is None:
        return 'NULL'
    return "'" + str(value).replace('\\', '\\\\').replace("'", "''") + "'"


def object_sql(table, alias='s'):
    parts = []
    for name in table['columns']:
        parts += [literal(name), alias + '.`' + name + '`']
    return 'JSON_OBJECT(' + ','.join(parts) + ')'


def key_sql(table, alias='s'):
    return 'CAST(JSON_ARRAY(' + ','.join(alias + '.`' + name + '`' for name in table['primaryKey']) + ') AS CHAR CHARACTER SET utf8mb4)'


def header(names, catalog):
    lines = [
        '-- Source artifact only. Run on the admitted ECS against a fresh compact target.',
        '-- The orchestrator holds an independent READ lock on the entire frozen source.',
        '-- Preserve source DATETIME values as recorded; no import clock replaces an unknown source time.',
        '-- Render __SOURCE_SCHEMA__ only after validating the schema identifier.',
        'CREATE TEMPORARY TABLE compact_support_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;',
        "INSERT INTO compact_support_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1,1,0);",
        'START TRANSACTION;',
    ]
    for name in names:
        table = catalog[name]
        count = len(table['columns'])
        lines.append("INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + " AND table_type='BASE TABLE' AND engine='InnoDB';")
        lines.append("INSERT INTO compact_support_guard SELECT IF(COUNT(*)=" + str(count) + ",1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + ';')
        for column, spec in table['columns'].items():
            declaration = spec['declaration']
            datatype = re.match(r'`?' + re.escape(column) + r'`?\s+([A-Za-z]+(?:\s*\([^)]*\))?(?:\s+UNSIGNED)?)', declaration, re.I).group(1).lower()
            datatype = re.sub(r'\s+', ' ', datatype).replace('boolean', 'tinyint(1)')
            nullable = 'NO' if column in table['primaryKey'] or re.search(r'\bNOT NULL\b', declaration, re.I) else 'YES'
            lines.append("INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + ' AND column_name=' + literal(column) + ' AND BINARY column_type=BINARY ' + literal(datatype) + ' AND is_nullable=' + literal(nullable) + ';')
        temporary = 'compact_support_' + name
        lines.append('CREATE TEMPORARY TABLE `' + temporary + '`(source_key VARCHAR(512) COLLATE utf8mb4_bin PRIMARY KEY,source_json LONGTEXT NOT NULL,source_sha256 CHAR(64) NOT NULL) ENGINE=InnoDB;')
        row = object_sql(table)
        lines.append('INSERT INTO `' + temporary + '` SELECT ' + key_sql(table) + ',CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4),SHA2(CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4),256) FROM `__SOURCE_SCHEMA__`.`' + name + '` s;')
    return lines


def guard(lines, query):
    lines.append('INSERT INTO compact_support_guard ' + query + ';')


def finish(lines, names, catalog):
    for name in names:
        table = catalog[name]
        old = '`compact_support_' + name + '`'
        guard(lines, 'SELECT IF((SELECT COUNT(*) FROM ' + old + ')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`' + name + '`),1,0)')
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`' + name + '` s LEFT JOIN ' + old + ' p ON BINARY p.source_key=BINARY ' + key_sql(table) + ' WHERE p.source_key IS NULL OR BINARY p.source_sha256<>BINARY SHA2(CAST(' + object_sql(table) + ' AS CHAR CHARACTER SET utf8mb4),256)')
    lines.append('COMMIT;')
    lines += ['DROP TEMPORARY TABLE `compact_support_' + name + '`;' for name in names]
    lines.append('DROP TEMPORARY TABLE compact_support_guard;')
    return '\n'.join(lines) + '\n'


def raise_auto_increment(lines, name):
    lines += ["SET @support_source_auto=(SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + ');',
              "SET @support_target_auto=(SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=" + literal(name) + ');',
              'SET @support_next_auto=GREATEST(COALESCE(@support_source_auto,1),COALESCE(@support_target_auto,1));',
              "SET @support_auto_sql=CONCAT('ALTER TABLE `" + name + "` AUTO_INCREMENT=',@support_next_auto);",
              'PREPARE compact_support_auto FROM @support_auto_sql;',
              'EXECUTE compact_support_auto;', 'DEALLOCATE PREPARE compact_support_auto;']


def main():
    if not CATALOG.exists():
        source = ROOT / 'work/schema-reduction-20261105/schema-inventory.json'
        inventory = json.loads(source.read_text(encoding='utf8'))
        descriptions = {}
        for item in inventory['tables']:
            if item['name'] not in SOURCES:
                continue
            chosen = next((d for d in item['createDefinitions'] if d['source'] == 'sql/mysql/schema.sql'), item['createDefinitions'][0])
            descriptions[item['name']] = {'source': chosen['source'], 'ddl': chosen['sql']}
        if set(descriptions) != set(SOURCES):
            raise ValueError('Missing reviewed support source DDL')
        CATALOG.write_text(json.dumps({'schemaVersion': 1, 'tables': descriptions}, ensure_ascii=False, indent=2) + '\n', encoding='utf8', newline='\n')
    definitions = json.loads(CATALOG.read_text(encoding='utf8'))['tables']
    tables = {name: parse_table(re.sub(r'CREATE TABLE IF NOT EXISTS', 'CREATE TABLE',
                  without_comments(item['ddl']), count=1, flags=re.I), item['source']) for name, item in definitions.items()}
    names = list(SOURCES[:3])
    lines = header(names, tables)
    lines.remove('START TRANSACTION;')
    # ALTER TABLE implicitly commits. Reserve both HWM values before any copied
    # business row, so all INSERTs below retain one rollback boundary.
    for name in names[:2]:
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `' + name + '`')
        raise_auto_increment(lines, name)
    lines.append('START TRANSACTION;')
    for name in names[:2]:
        table = tables[name]
        columns = ','.join('`' + column + '`' for column in table['columns'])
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `' + name + '`')
        lines.append('INSERT INTO `' + name + '`(' + columns + ') SELECT ' + columns + ' FROM `__SOURCE_SCHEMA__`.`' + name + '`;')
        guard(lines, 'SELECT IF((SELECT COUNT(*) FROM `' + name + '`)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`' + name + '`),1,0)')
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `' + name + '` t LEFT JOIN `compact_support_' + name + '` p ON BINARY p.source_key=BINARY ' + key_sql(table, 't') + ' WHERE p.source_key IS NULL OR BINARY p.source_sha256<>BINARY SHA2(CAST(' + object_sql(table, 't') + ' AS CHAR CHARACTER SET utf8mb4),256)')
    name = 'detection_image_fingerprint'
    source = '`__SOURCE_SCHEMA__`.`' + name + '` s'
    asset = "CONCAT('det-image:',LOWER(s.sha256))"
    guard(lines, "SELECT IF(COUNT(*)=0,1,0) FROM " + source + " WHERE s.id<=0 OR OCTET_LENGTH(s.sha256)<>64 OR s.sha256 NOT REGEXP '^[a-fA-F0-9]{64}$' OR s.version<0")
    guard(lines, "SELECT IF(COUNT(*)=0,1,0) FROM content_asset WHERE asset_kind='DETECTION_IMAGE'")
    guard(lines, "SELECT IF(COUNT(*)=0,1,0) FROM content_revision WHERE asset_kind='DETECTION_IMAGE'")
    guard(lines, "SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace='DETECTION_FINGERPRINT'")
    row = object_sql(tables[name])
    projections = {
        'content_asset': {'asset_id': asset, 'asset_kind': "'DETECTION_IMAGE'", 'owner_user_id': 'NULL',
            'legacy_owner_reference': 's.owner_user_id', 'identity_key': 'LOWER(s.sha256)', 'title': 's.file_name',
            'filename': 's.file_name', 'visibility': "'SYSTEM'", 'lifecycle': "'ACTIVE'", 'current_version': '1',
            'revision': 's.version', 'created_at': 's.created_at', 'updated_at': 's.updated_at',
            'legacy_source': "'detection_image_fingerprint'", 'legacy_id': 's.id'},
        'content_revision': {'asset_id': asset, 'asset_kind': "'DETECTION_IMAGE'", 'version': '1',
            'owner_user_id': 'NULL', 'filename': 's.file_name', 'object_key': 's.object_key',
            'content_sha256': 'LOWER(s.sha256)', 'manifest_json': 'CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4)',
            'manifest_sha256': 'SHA2(CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4),256)',
            'created_at': 's.created_at', 'legacy_source': "'detection_image_fingerprint'", 'legacy_id': 's.id'},
        'runtime_state': {'namespace': "'DETECTION_FINGERPRINT'", 'owner_id': '0', 'scope_key': 'LOWER(s.sha256)',
            'revision': 's.version', 'state_code': 's.status', 'current_ref': 's.last_task_id', 'payload_version': '1',
            'payload_json': "CAST(JSON_OBJECT('originalId',s.id,'sourceOwnerKey',s.owner_user_id) AS CHAR CHARACTER SET utf8mb4)",
            'created_at': 's.created_at', 'updated_at': 's.updated_at'},
    }
    for target, values in projections.items():
        lines.append('INSERT INTO ' + target + '(' + ','.join(values) + ') SELECT ' + ','.join(values.values()) + ' FROM ' + source + ';')
    textual = {'asset_id', 'asset_kind', 'legacy_owner_reference', 'identity_key', 'title', 'filename',
               'visibility', 'lifecycle', 'legacy_source', 'object_key', 'content_sha256', 'manifest_json',
               'manifest_sha256', 'namespace', 'scope_key', 'state_code', 'current_ref', 'payload_json'}
    joins = {'content_asset': 'BINARY t.asset_id=BINARY ' + asset + " AND t.asset_kind='DETECTION_IMAGE'",
             'content_revision': 'BINARY t.asset_id=BINARY ' + asset + " AND t.asset_kind='DETECTION_IMAGE' AND t.version=1",
             'runtime_state': "t.namespace='DETECTION_FINGERPRINT' AND t.owner_id=0 AND BINARY t.scope_key=BINARY LOWER(s.sha256)"}
    for target, values in projections.items():
        predicate = "namespace='DETECTION_FINGERPRINT'" if target == 'runtime_state' else "asset_kind='DETECTION_IMAGE'"
        missing = 't.owner_id IS NULL' if target == 'runtime_state' else 't.id IS NULL'
        guard(lines, 'SELECT IF((SELECT COUNT(*) FROM ' + target + ' WHERE ' + predicate + ')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_image_fingerprint),1,0)')
        changed = []
        for column, expected in values.items():
            binary = 'BINARY ' if column in textual else ''
            changed.append('NOT(' + binary + 't.' + column + '<=>' + binary + expected + ')')
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM ' + source + ' LEFT JOIN ' + target + ' t ON ' + joins[target] + ' WHERE ' + missing + ' OR ' + ' OR '.join(changed))
    (ROOT / 'sql/mysql/compact/copy/12-chat-and-fingerprints.sql').write_text(finish(lines, names, tables), encoding='utf8', newline='\n')
    owners = list(SOURCES[3:])
    lines = header(owners, tables)
    for name, namespace, key in [('agent_research_storage_owner', 'RESEARCH_STORAGE', 'user_id'), ('agent_skill_download_owner', 'SKILL_DOWNLOAD', 'owner_user_id')]:
        clock = 's.created_at' if 'created_at' in tables[name]['columns'] else 'NULL'
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace=' + literal(namespace))
        lines.append("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at,updated_at) SELECT " + literal(namespace) + ",s.`" + key + "`,'',0," + clock + ',NULL FROM `__SOURCE_SCHEMA__`.`' + name + '` s;')
        guard(lines, 'SELECT IF((SELECT COUNT(*) FROM runtime_state WHERE namespace=' + literal(namespace) + ')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`' + name + '`),1,0)')
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`' + name + '` s LEFT JOIN runtime_state t ON t.namespace=' + literal(namespace) + ' AND t.owner_id=s.`' + key + "` AND t.scope_key='' WHERE t.owner_id IS NULL OR t.revision<>0 OR t.updated_at IS NOT NULL OR NOT(t.created_at<=>" + clock + ')')
    (ROOT / 'sql/mysql/compact/copy/50-owner-locks.sql').write_text(finish(lines, owners, tables), encoding='utf8', newline='\n')
    fixtures = ROOT / 'doorhandle-module-app/src/test/resources/compact-support-source.sql'
    fixtures.parent.mkdir(parents=True, exist_ok=True)
    fixtures.write_text('-- Source DDL only. Create referenced users/chat_session fixtures first.\n' + '\n\n'.join(item['ddl'].rstrip(';') + ';' for item in definitions.values()) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_SQL_EXECUTED', 'sourceTables': len(tables)}))


if __name__ == '__main__':
    main()
