"""Author the remaining chat, image fingerprint and owner-lock copies; source work only."""
from pathlib import Path
import json
import re

from build_compact_schema import ROOT, parse_table, without_comments

CATALOG = ROOT / 'docs/database/compact-support-source-map.json'
SOURCES = ('chat_project', 'chat_session', 'chat_message', 'detection_image_fingerprint',
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


def source_statement(lines, name, statement):
    # The original schema has 14 session columns; the observed project
    # extension adds only project_id. Both copy all present source fields.
    if name != 'chat_session' or 's.`project_id`' not in statement:
        lines.append(statement)
        return
    absent = statement.replace('s.`project_id`', 'NULL')
    lines += ['SET @support_session_sql=IF(@support_session_has_project,' + literal(statement) + ',' + literal(absent) + ');',
              'PREPARE compact_support_session FROM @support_session_sql;',
              'EXECUTE compact_support_session;', 'DEALLOCATE PREPARE compact_support_session;']


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
        if name == 'chat_session':
            lines.append("SET @support_session_has_project=(SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='chat_session' AND BINARY column_name=BINARY 'project_id');")
        lines.append("INSERT INTO compact_support_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + " AND table_type='BASE TABLE' AND engine='InnoDB';")
        expected = str(count - 1) + '+@support_session_has_project' if name == 'chat_session' else str(count)
        lines.append("INSERT INTO compact_support_guard SELECT IF(COUNT(*)=" + expected + ",1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + ';')
        for column, spec in table['columns'].items():
            declaration = spec['declaration']
            datatype = re.match(r'`?' + re.escape(column) + r'`?\s+([A-Za-z]+(?:\s*\([^)]*\))?(?:\s+UNSIGNED)?)', declaration, re.I).group(1).lower()
            datatype = re.sub(r'\s+', ' ', datatype).replace('boolean', 'tinyint(1)')
            nullable = 'NO' if column in table['primaryKey'] or re.search(r'\bNOT NULL\b', declaration, re.I) else 'YES'
            present = '@support_session_has_project=0 OR ' if name == 'chat_session' and column == 'project_id' else ''
            lines.append("INSERT INTO compact_support_guard SELECT IF(" + present + "COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name=" + literal(name) + ' AND column_name=' + literal(column) + ' AND BINARY column_type=BINARY ' + literal(datatype) + ' AND is_nullable=' + literal(nullable) + ';')
        if name == 'chat_session':
            session_metadata(lines)
        temporary = 'compact_support_' + name
        lines.append('CREATE TEMPORARY TABLE `' + temporary + '`(source_key VARCHAR(512) COLLATE utf8mb4_bin PRIMARY KEY,source_json LONGTEXT NOT NULL,source_sha256 CHAR(64) NOT NULL) ENGINE=InnoDB;')
        row = object_sql(table)
        source_statement(lines, name, 'INSERT INTO `' + temporary + '` SELECT ' + key_sql(table) + ',CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4),SHA2(CAST(' + row + ' AS CHAR CHARACTER SET utf8mb4),256) FROM `__SOURCE_SCHEMA__`.`' + name + '` s;')
    return lines


def guard(lines, query):
    lines.append('INSERT INTO compact_support_guard ' + query + ';')


def session_metadata(lines):
    """Admit the canonical 14-column and captured 15-column session identities."""
    where = "table_schema='__SOURCE_SCHEMA__' AND table_name='chat_session'"
    guard(lines, "SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns WHERE " + where
          + " AND ((character_set_name IS NOT NULL AND (BINARY character_set_name<>BINARY 'utf8mb4' OR BINARY collation_name<>BINARY 'utf8mb4_unicode_ci'))"
          + " OR (column_name='id' AND extra<>'auto_increment') OR generation_expression<>'')")
    guard(lines, "SELECT IF(COUNT(*)=2 AND SUM(index_name='PRIMARY' AND column_name='id' AND seq_in_index=1)=1"
          + " AND SUM(index_name='uk_chat_session_id' AND column_name='session_id' AND seq_in_index=1)=1,1,0)"
          + " FROM information_schema.statistics WHERE " + where + " AND non_unique=0")
    guard(lines, "SELECT IF(COUNT(*)=2-@support_session_has_project,1,0) FROM information_schema.referential_constraints WHERE constraint_schema='__SOURCE_SCHEMA__' AND table_name='chat_session'")
    guard(lines, "SELECT IF(COUNT(*)=2-@support_session_has_project,1,0) FROM information_schema.key_column_usage WHERE " + where + " AND referenced_table_name IS NOT NULL")
    for constraint, column, parent_column, update_rule, optional in [
        ('fk_chat_session_tenant_user', 'user_id', 'id', 'RESTRICT', False),
        ('fk_chat_session_user', 'username', 'username', 'CASCADE', True),
    ]:
        prefix = '@support_session_has_project=1 OR ' if optional else ''
        guard(lines, 'SELECT IF(' + prefix + 'COUNT(*)=1,1,0) FROM information_schema.referential_constraints r'
              + ' JOIN information_schema.key_column_usage k ON k.constraint_schema=r.constraint_schema AND k.table_name=r.table_name AND k.constraint_name=r.constraint_name'
              + " WHERE r.constraint_schema='__SOURCE_SCHEMA__' AND r.table_name='chat_session' AND BINARY r.constraint_name=BINARY " + literal(constraint)
              + " AND r.delete_rule='CASCADE' AND r.update_rule=" + literal(update_rule)
              + ' AND BINARY k.column_name=BINARY ' + literal(column)
              + " AND k.referenced_table_schema='__SOURCE_SCHEMA__' AND k.referenced_table_name='users' AND BINARY k.referenced_column_name=BINARY " + literal(parent_column)
              + ' AND k.ordinal_position=1 AND k.position_in_unique_constraint=1')
    guard(lines, "SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.chat_session s LEFT JOIN `__SOURCE_SCHEMA__`.users u ON u.id=s.user_id WHERE u.id IS NULL")
    guard(lines, "SELECT IF(@support_session_has_project=1 OR COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.chat_session s LEFT JOIN `__SOURCE_SCHEMA__`.users u ON u.username=s.username WHERE u.id IS NULL")
    lines += ['CREATE TEMPORARY TABLE compact_support_session_state(valid INT NOT NULL CONSTRAINT compact_support_session_state_json_chk CHECK(valid=1)) ENGINE=InnoDB;',
              "INSERT INTO compact_support_session_state SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.chat_session WHERE state_json IS NOT NULL AND NOT JSON_VALID(state_json);",
              'DROP TEMPORARY TABLE compact_support_session_state;']


def finish(lines, names, catalog):
    for name in names:
        table = catalog[name]
        old = '`compact_support_' + name + '`'
        guard(lines, 'SELECT IF((SELECT COUNT(*) FROM ' + old + ')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`' + name + '`),1,0)')
        source_statement(lines, name, 'INSERT INTO compact_support_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`' + name + '` s LEFT JOIN ' + old + ' p ON BINARY p.source_key=BINARY ' + key_sql(table) + ' WHERE p.source_key IS NULL OR BINARY p.source_sha256<>BINARY SHA2(CAST(' + object_sql(table) + ' AS CHAR CHARACTER SET utf8mb4),256);')
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
    guard(lines, "SELECT IF(AUTO_INCREMENT>=@support_next_auto,1,0) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=" + literal(name))


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
    names = list(SOURCES[:4])
    lines = header(names, tables)
    lines.remove('START TRANSACTION;')
    # ALTER TABLE implicitly commits. Reserve every chat HWM before any copied
    # business row, so all INSERTs below retain one rollback boundary.
    for name in names[:3]:
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `' + name + '`')
        raise_auto_increment(lines, name)
    lines.append('START TRANSACTION;')
    for name in names[:3]:
        table = tables[name]
        columns = ','.join('`' + column + '`' for column in table['columns'])
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `' + name + '`')
        selected = ','.join('s.`' + column + '`' for column in table['columns'])
        source_statement(lines, name, 'INSERT INTO `' + name + '`(' + columns + ') SELECT ' + selected + ' FROM `__SOURCE_SCHEMA__`.`' + name + '` s;')
        guard(lines, 'SELECT IF((SELECT COUNT(*) FROM `' + name + '`)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`' + name + '`),1,0)')
        guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM `' + name + '` t LEFT JOIN `compact_support_' + name + '` p ON BINARY p.source_key=BINARY ' + key_sql(table, 't') + ' WHERE p.source_key IS NULL OR BINARY p.source_sha256<>BINARY SHA2(CAST(' + object_sql(table, 't') + ' AS CHAR CHARACTER SET utf8mb4),256)')
        if name == 'chat_session':
            guard(lines, 'SELECT IF(COUNT(*)=0,1,0) FROM chat_session WHERE fork_owner_user_id IS NOT NULL OR fork_request_id IS NOT NULL OR fork_source_session_id IS NOT NULL OR fork_through_message_id IS NOT NULL OR fork_legacy_id IS NOT NULL')
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
        inserted = {**values, 'lifecycle': "'PREPARING'", 'current_version': 'NULL'} if target == 'content_asset' else values
        lines.append('INSERT INTO ' + target + '(' + ','.join(inserted) + ') SELECT ' + ','.join(inserted.values()) + ' FROM ' + source + ';')
    # Both content foreign keys remain enabled: establish the asset, then its
    # revision, before pointing the asset at that revision in this transaction.
    lines.append('UPDATE content_asset a JOIN ' + source + ' ON BINARY a.asset_id=BINARY ' + asset
                 + " AND a.asset_kind='DETECTION_IMAGE' AND BINARY a.legacy_source=BINARY 'detection_image_fingerprint' AND a.legacy_id=s.id"
                 + " SET a.current_version=1,a.lifecycle='ACTIVE';")
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
    owners = list(SOURCES[4:])
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
    fixtures.write_text('-- Source DDL only. Create the referenced users fixture first.\n' + '\n\n'.join(definitions[name]['ddl'].rstrip(';') + ';' for name in SOURCES) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_SQL_EXECUTED', 'sourceTables': len(tables)}))


if __name__ == '__main__':
    main()
