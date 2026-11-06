"""Author the explicit core-copy SQL and historical test DDL from saved evidence; no database access.

The output is a migration source artifact, not an application SQL-rewriting adapter.
Only the documented optional columns have literal, reviewed NULL/zero branches.
"""
from pathlib import Path
import importlib.util
import json
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('compact_parser',ROOT/'script/schema/build_compact_schema.py')
parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
mapping=json.loads((ROOT/'work/schema-reduction-20261105/core-column-map.json').read_text(encoding='utf-8'))
inventory={t['name']:t for t in json.loads((ROOT/'work/schema-reduction-20261105/schema-inventory.json').read_text(encoding='utf-8'))['tables']}
history=json.loads((ROOT/'work/schema-reduction-20261105/historical-image-detection-ddl.json').read_text(encoding='utf-8'))
targets={}
for statement in parser.split_top_level(parser.without_comments((ROOT/'sql/mysql/compact/baseline/10-core.sql').read_text(encoding='utf-8')),';'):
    if statement.startswith('CREATE TABLE '):
        table=parser.parse_table(statement,'10-core.sql');targets[table['name']]=table

def literal(value):
    if value is None:return 'NULL'
    return "'"+str(value).replace('\\','\\\\').replace("'","''")+"'"

def source_definition(name):
    if name=='image_detection_data':return parser.parse_table(re.sub(r'\s*;\s*$','',history['ddl']),'historical-20261014')
    definitions=inventory[name]['createDefinitions']
    definition=next((d for d in definitions if d['source']=='sql/mysql/schema.sql'),definitions[0])
    statement=re.sub(r'CREATE TABLE IF NOT EXISTS','CREATE TABLE',definition['sql'],count=1,flags=re.I)
    return parser.parse_table(statement,definition['source'])

def metadata(declaration,collation,primary=False):
    declaration=re.sub(r"\s+COMMENT\s+'(?:[^']|'')*'",'',declaration,flags=re.I)
    kind=re.match(parser.IDENT+r'\s+([a-z]+(?:\s*\([^)]*\))?(?:\s+UNSIGNED)?)',declaration,re.I).group(2).lower()
    kind=re.sub(r'\s+',' ',kind).replace('boolean','tinyint(1)')
    charset='utf8mb4' if re.match(r'(?:varchar|char|longtext|mediumtext|text)\b',kind) else None
    explicit=re.search(r'COLLATE\s+(\w+)',declaration,re.I)
    coll=(explicit.group(1).lower() if explicit else collation) if charset else None
    nullable='NO' if primary or re.search(r'\b(?:NOT NULL|PRIMARY KEY)\b',declaration,re.I) else 'YES'
    default=re.search(r"\bDEFAULT\s+('(?:[^']|'')*'|[A-Z_]+(?:\(\d*\))?|[-+]?\d+(?:\.\d+)?)",declaration,re.I)
    value=None;expression=0
    if default:
        value=default.group(1)
        if value.upper()=='NULL':value=None
        elif value.startswith("'"):value=value[1:-1].replace("''","'")
        elif value.upper() in ('TRUE','FALSE'):value='1' if value.upper()=='TRUE' else '0'
        elif value.upper().startswith('CURRENT_TIMESTAMP'):value='CURRENT_TIMESTAMP';expression=1
    extra=[]
    if 'AUTO_INCREMENT' in declaration.upper():extra.append('auto_increment')
    if expression:extra.append('default_generated')
    if re.search(r'ON UPDATE CURRENT_TIMESTAMP',declaration,re.I):extra.append('on update current_timestamp')
    return [kind,nullable,charset,coll,value,expression,' '.join(extra)]

sources={};rows=[];optional={}
for route in mapping['tables']:
    name,target=route['sourceTable'],route['targetTable'];base=source_definition(name)
    sources[name]=base
    target_table=targets[target]
    optional[name]=[]
    for column in route['columns']:
        source_col,target_col=column['sourceColumn'],column['targetColumn']
        is_optional=column['strategy']=='COPY_IF_SOURCE_COLUMN_PRESENT_ELSE_TARGET_DEFAULT'
        if source_col not in base['columns']:
            declarations=[]
            for alter in inventory[name]['alterations']:
                for match in re.finditer(r'\bADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s+(.+?)(?=,\s*ADD\b|$)',alter['sql'],re.I|re.S):
                    if match.group(1)==source_col:
                        declarations.append('`'+source_col+'` '+re.sub(r'\s+AFTER\s+`?\w+`?\s*$','',match.group(2).strip()))
            if not declarations:raise ValueError('No source declaration for '+name+'.'+source_col)
            # ALTER definitions are independent source evidence; never derive historical source types from target columns.
            declaration=declarations[-1]
            table_collation=re.search(r'COLLATE\s*=\s*(\w+)',base['options'],re.I)
            coll=table_collation.group(1) if table_collation else 'utf8mb4_0900_ai_ci'
            base['columns'][source_col]={'declaration':declaration,'collation':coll}
        source_meta=metadata(base['columns'][source_col]['declaration'],base['columns'][source_col]['collation'] or 'utf8mb4_0900_ai_ci',source_col in base['primaryKey'])
        target_meta=metadata(target_table['columns'][target_col]['declaration'],target_table['columns'][target_col]['collation'],target_col in target_table['primaryKey'])
        rows.append([name,target,source_col,target_col,int(is_optional),*source_meta,*target_meta])
        if is_optional:optional[name].append(source_col)

core_names=list(mapping['targetTables']);source_names=list(sources)
sql=[]
def emit(value=''):sql.append(value)
def guard(query):emit('INSERT INTO compact_core_guard '+query+';')
def run_dynamic(expression):
    emit('SET @compact_core_sql='+expression+';\nPREPARE compact_core_statement FROM @compact_core_sql;\nEXECUTE compact_core_statement;\nDEALLOCATE PREPARE compact_core_statement;')
def dynamic_text(pieces):
    return 'CONCAT('+','.join(p if p.startswith('@compact_core_expr_') else literal(p) for p in pieces)+')'

emit('''-- MySQL 8.4 core12 copy, UNVERIFIED. Authoring evidence: core-column-map.json + saved source inventory.
-- Source and target must be distinct schemas on the same admitted isolated server; render __SOURCE_SCHEMA__ as a validated identifier.
-- Source writers must already be stopped. Use a metadata-visible migration account. Never --force; rollback errors on this connection.
-- Stage: create ALL target tables and 35/36 guards, but defer 40-relations until ALL domain data (including chat) is copied.
-- FOREIGN_KEY_CHECKS remains ON. This script never drops source objects, creates business tables or installs compatibility views.
-- Only known optional columns use literal NULL/zero branches. Any other missing/unknown column or changed declaration aborts.
-- High-water ALTERs precede the row transaction and are not rolled back. No target is deployable until final relations and recovery pass.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_core_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;''')
guard("SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0)")
guard("SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)))")
emit('''CREATE TEMPORARY TABLE compact_core_columns(
 source_table VARCHAR(64),target_table VARCHAR(64),source_column VARCHAR(64),target_column VARCHAR(64),optional_column BOOLEAN,
 source_type VARCHAR(128),source_nullable VARCHAR(3),source_charset VARCHAR(32),source_collation VARCHAR(64),source_default TEXT,source_default_expression BOOLEAN,source_extra VARCHAR(128),
 target_type VARCHAR(128),target_nullable VARCHAR(3),target_charset VARCHAR(32),target_collation VARCHAR(64),target_default TEXT,target_default_expression BOOLEAN,target_extra VARCHAR(128),
 PRIMARY KEY(source_table,source_column)
) ENGINE=InnoDB;''')
emit('INSERT INTO compact_core_columns VALUES\n'+',\n'.join('('+','.join(str(x) if isinstance(x,int) else literal(x) for x in row)+')' for row in rows)+';')
source_list=','.join(map(literal,source_names));target_list=','.join(map(literal,core_names))
guard(f"SELECT IF(COUNT(*)={len(source_names)},1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ({source_list}) AND table_type='BASE TABLE' AND engine='InnoDB'")
guard(f"SELECT IF(COUNT(*)={len(core_names)},1,0) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ({target_list}) AND table_type='BASE TABLE' AND engine='InnoDB'")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns c LEFT JOIN compact_core_columns p ON p.source_table=c.table_name AND p.source_column=c.column_name WHERE c.table_schema='__SOURCE_SCHEMA__' AND c.table_name IN ("+source_list+") AND p.source_column IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_core_columns p LEFT JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=p.source_table AND c.column_name=p.source_column WHERE c.column_name IS NULL AND p.optional_column=FALSE")
for side,schema,colname in [('source',"'__SOURCE_SCHEMA__'",'source_column'),('target','DATABASE()','target_column')]:
    mismatch=f"NOT(BINARY LOWER(c.column_type)<=>BINARY p.{side}_type) OR NOT(c.is_nullable<=>p.{side}_nullable) OR NOT(c.character_set_name<=>p.{side}_charset) OR NOT(c.collation_name<=>p.{side}_collation) OR c.generation_expression<>'' OR NOT(LOWER(REPLACE(c.extra,'()',''))<=>p.{side}_extra) OR NOT((CASE WHEN p.{side}_default_expression THEN UPPER(REPLACE(c.column_default,'()','')) ELSE BINARY c.column_default END)<=>p.{side}_default)"
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM compact_core_columns p {'JOIN' if side=='source' else 'LEFT JOIN'} information_schema.columns c ON c.table_schema={schema} AND c.table_name=p.{side}_table AND c.column_name=p.{colname} WHERE "+('c.column_name IS NULL OR ' if side=='target' else '')+'('+mismatch+')')
# New derived columns have no historical counterpart, but their target declarations are still exact contracts.
mapped_targets={(row[1],row[3]) for row in rows}
for name in core_names:
    for column,definition in targets[name]['columns'].items():
        if (name,column) in mapped_targets:continue
        kind,nullable,charset,collation,default,expression,extra=metadata(definition['declaration'],definition['collation'],column in targets[name]['primaryKey'])
        checks=[f"BINARY LOWER(column_type)<=>BINARY {literal(kind)}",f"is_nullable<=>{literal(nullable)}",f"character_set_name<=>{literal(charset)}",f"collation_name<=>{literal(collation)}","generation_expression=''",f"LOWER(REPLACE(extra,'()',''))<=>{literal(extra)}",f"BINARY column_default<=>BINARY {literal(default)}"]
        guard(f"SELECT IF(COUNT(*)=1,1,0) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='{name}' AND column_name='{column}' AND "+' AND '.join('('+check+')' for check in checks))
for name in core_names:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `{name}`")
    columns=','.join(map(literal,targets[name]['columns']))
    guard(f"SELECT IF(COUNT(*)={len(targets[name]['columns'])},1,0) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='{name}' AND column_name IN ({columns})")
    guard(f"SELECT IF(COUNT(*)={len(targets[name]['columns'])},1,0) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='{name}'")
guard("SELECT IF(COUNT(*)=2,1,0) FROM information_schema.triggers WHERE event_object_schema=DATABASE() AND event_object_table='users' AND action_timing='BEFORE' AND ((trigger_name='compact_identity_protect_delete' AND event_manipulation='DELETE') OR (trigger_name='compact_identity_protect_update' AND event_manipulation='UPDATE'))")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN ("+source_list+")")
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ("+source_list+") AND constraint_type='CHECK'")
emit('CREATE TEMPORARY TABLE compact_core_unique_keys(source_table VARCHAR(64),is_primary BOOLEAN,columns_in_key VARCHAR(1024)) ENGINE=InnoDB;')
keys=[]
for name,table in sources.items():
    keys.append((name,1,','.join(table['primaryKey'])))
    keys.extend((name,0,','.join(key)) for key in table['uniqueKeys'])
emit('INSERT INTO compact_core_unique_keys VALUES\n'+',\n'.join('('+literal(n)+','+str(p)+','+literal(k)+')' for n,p,k in keys)+';')
actual_keys="(SELECT table_name,(index_name='PRIMARY') AS is_primary,GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns_in_key,SUM(sub_part IS NOT NULL) AS prefixes FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ("+source_list+") AND non_unique=0 GROUP BY table_name,index_name)"
guard('SELECT IF(COUNT(*)=0,1,0) FROM '+actual_keys+' a LEFT JOIN compact_core_unique_keys e ON e.source_table=a.table_name AND e.is_primary=a.is_primary AND e.columns_in_key=a.columns_in_key WHERE e.source_table IS NULL OR a.prefixes<>0')
guard('SELECT IF(COUNT(*)=0,1,0) FROM compact_core_unique_keys e LEFT JOIN '+actual_keys+' a ON e.source_table=a.table_name AND e.is_primary=a.is_primary AND e.columns_in_key=a.columns_in_key WHERE a.table_name IS NULL')
for name,columns in optional.items():
    for column in columns:
        fallback='0' if column=='assignment_identity_revision' else 'NULL'
        emit(f"SET @compact_core_expr_{name}_{column}=IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='{name}' AND column_name='{column}')=1,'s.`{column}`','{fallback}');")

# Existing FK semantics and source referential integrity. Cross-domain session data is verified here and copied separately.
relations=[('employee','department_id','organization_department','id','RESTRICT','RESTRICT'),('account_employee_binding','user_id','users','id','RESTRICT','RESTRICT'),('account_employee_binding','employee_id','employee','id','RESTRICT','RESTRICT'),('device_management','employee_id','employee','id','SET NULL','RESTRICT'),('device_usage_record','device_id','device_management','id','CASCADE','RESTRICT'),('device_usage_record','employee_id','employee','id','CASCADE','RESTRICT'),('device_capture_alert','device_id','device_management','id','SET NULL','RESTRICT'),('detection_task','model_id','model_management','model_id','SET NULL','CASCADE'),('detection_task','session_id','chat_session','session_id','SET NULL','CASCADE'),('image_detection_data','model_id','model_management','model_id','SET NULL','CASCADE')]
emit('CREATE TEMPORARY TABLE compact_core_relations(source_table VARCHAR(64),source_column VARCHAR(64),parent_table VARCHAR(64),parent_column VARCHAR(64),delete_rule VARCHAR(16),update_rule VARCHAR(16)) ENGINE=InnoDB;')
emit('INSERT INTO compact_core_relations VALUES\n'+',\n'.join('('+','.join(map(literal,r))+')' for r in relations)+';')
guard("SELECT IF(COUNT(*)=0,1,0) FROM information_schema.key_column_usage k JOIN information_schema.referential_constraints r ON r.constraint_schema=k.constraint_schema AND r.table_name=k.table_name AND r.constraint_name=k.constraint_name LEFT JOIN compact_core_relations e ON e.source_table=k.table_name AND e.source_column=k.column_name AND e.parent_table=k.referenced_table_name AND e.parent_column=k.referenced_column_name AND e.delete_rule=(CASE r.delete_rule WHEN 'NO ACTION' THEN 'RESTRICT' ELSE r.delete_rule END) AND e.update_rule=(CASE r.update_rule WHEN 'NO ACTION' THEN 'RESTRICT' ELSE r.update_rule END) WHERE k.table_schema='__SOURCE_SCHEMA__' AND k.table_name IN ("+source_list+") AND (e.source_table IS NULL OR k.referenced_table_schema<>'__SOURCE_SCHEMA__' OR k.ordinal_position<>1)")
guard("SELECT IF(COUNT(*)=0,1,0) FROM compact_core_relations e JOIN information_schema.columns c ON c.table_schema='__SOURCE_SCHEMA__' AND c.table_name=e.source_table AND c.column_name=e.source_column LEFT JOIN information_schema.key_column_usage k ON k.table_schema='__SOURCE_SCHEMA__' AND k.table_name=e.source_table AND k.column_name=e.source_column AND k.referenced_table_schema='__SOURCE_SCHEMA__' AND k.referenced_table_name=e.parent_table AND k.referenced_column_name=e.parent_column WHERE k.constraint_name IS NULL")
for child,column,parent,key,_,_ in relations:
    if column in optional.get(child,[]):
        run_dynamic(dynamic_text(["INSERT INTO compact_core_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`"+child+"` s LEFT JOIN `__SOURCE_SCHEMA__`.`"+parent+"` p ON ",f'@compact_core_expr_{child}_{column}',f'=p.`{key}` WHERE ',f'@compact_core_expr_{child}_{column}',f' IS NOT NULL AND p.`{key}` IS NULL']))
    else:
        binary='BINARY ' if column=='session_id' else ''
        guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`{child}` s LEFT JOIN `__SOURCE_SCHEMA__`.`{parent}` p ON {binary}s.`{column}`={binary}p.`{key}` WHERE s.`{column}` IS NOT NULL AND p.`{key}` IS NULL")
guard("SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.account_employee_binding WHERE version<0")
for column in ['created_user_id','assignee_user_id','reviewer_user_id','disposition_user_id','rework_user_id','assigned_by_user_id']:
    run_dynamic(dynamic_text(["INSERT INTO compact_core_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_task s LEFT JOIN `__SOURCE_SCHEMA__`.users p ON ",f'@compact_core_expr_detection_task_{column}',"=p.id WHERE ",f'@compact_core_expr_detection_task_{column}'," IS NOT NULL AND p.id IS NULL"]))
for column in ['owner_user_id','decider_user_id']:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_quality_report s LEFT JOIN `__SOURCE_SCHEMA__`.users p ON s.`{column}`=p.id WHERE s.`{column}` IS NOT NULL AND p.id IS NULL")
for child,column,parent,key in [('detection_work_unit_image','work_unit_id','detection_work_unit','work_unit_id'),('detection_quality_report','task_id','detection_task','task_id'),('detection_quality_report','previous_report_id','detection_quality_report','report_id')]:
    guard(f"SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`{child}` s LEFT JOIN `__SOURCE_SCHEMA__`.`{parent}` p ON BINARY s.`{column}`=BINARY p.`{key}` WHERE s.`{column}` IS NOT NULL AND p.`{key}` IS NULL")
emit('SET SESSION information_schema_stats_expiry=0;')
auto=[]
for route in mapping['tables']:
    name,target=route['sourceTable'],route['targetTable']
    if name=='account_employee_binding':continue
    pk=targets[target]['primaryKey'][0]
    if 'AUTO_INCREMENT' not in targets[target]['columns'][pk]['declaration'].upper():continue
    auto.append((name,target,pk))
    emit(f"SET @compact_core_next_{target}=(SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='{name}');")
    guard(f"SELECT IF(@compact_core_next_{target} IS NOT NULL AND @compact_core_next_{target} BETWEEN 1 AND 9223372036854775807 AND @compact_core_next_{target}>(SELECT COALESCE(MAX(`{pk}`),0) FROM `__SOURCE_SCHEMA__`.`{name}`),1,0)")
    run_dynamic("CONCAT('ALTER TABLE `"+target+"` AUTO_INCREMENT=',CAST(@compact_core_next_"+target+" AS CHAR))")
emit("SET @compact_core_original_sql_mode=@@SESSION.sql_mode;\nSET SESSION sql_mode=CONCAT_WS(',',@@SESSION.sql_mode,'NO_AUTO_VALUE_ON_ZERO');\nSTART TRANSACTION;")
order=['organization_department','employee','users','model_management','device_management','device_usage','device_alert','detection_work_unit','detection_task','detection_input','quality_report','historical_detection_summary']
routes={r['targetTable']:r for r in mapping['tables'] if r['sourceTable']!='account_employee_binding'}
def expression(route,column):
    name=route['sourceTable']
    if column in optional[name]:return '@compact_core_expr_'+name+'_'+column
    return 's.`'+column+'`'
def pieces_for_expressions(expressions,separator):
    result=[]
    for i,expr in enumerate(expressions):
        if i:result.append(separator)
        result.append(expr)
    return result
for target in order:
    route=routes[target];name=route['sourceTable'];table=targets[target];pk=table['primaryKey'][0]
    cols=[c['targetColumn'] for c in route['columns']];exprs=[expression(route,c['sourceColumn']) for c in route['columns']]
    join=''
    if target=='users':
        cols+=['employee_id','binding_version','binding_history_present'];exprs+=['b.employee_id','CASE WHEN b.user_id IS NULL THEN 0 ELSE b.version END','(b.user_id IS NOT NULL)']
        join=' LEFT JOIN `__SOURCE_SCHEMA__`.account_employee_binding b ON b.user_id=s.id'
    if target=='detection_input':cols+=['content_asset_id','content_version'];exprs+=['NULL','NULL']
    prefix=f"INSERT INTO `{target}`("+','.join('`'+c+'`' for c in cols)+') SELECT '
    suffix=f' FROM `__SOURCE_SCHEMA__`.`{name}` s'+join+f' ORDER BY s.`{pk}`'
    pieces=[prefix]+pieces_for_expressions(exprs,',')+[suffix]
    if optional[name]:run_dynamic(dynamic_text(pieces))
    else:emit(''.join(pieces)+';')
    guard(f"SELECT IF((SELECT COUNT(*) FROM `{target}`)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.`{name}`),1,0)")
    compare=[f'INSERT INTO compact_core_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.`{name}` s'+join+f' LEFT JOIN `{target}` t ON t.`{pk}`=s.`{pk}` WHERE t.`{pk}` IS NULL']
    for column,expr in zip(cols,exprs):
        binary='BINARY ' if re.match(r'(?:VAR)?CHAR|(?:LONG|MEDIUM)?TEXT|JSON',table['columns'][column]['type'],re.I) else ''
        compare+=[' OR NOT('+binary+'t.`'+column+'`<=>'+binary,expr,')']
    if optional[name]:run_dynamic(dynamic_text(compare))
    else:emit(''.join(compare)+';')
guard('SELECT IF((SELECT COUNT(*) FROM users WHERE binding_history_present=TRUE)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.account_employee_binding),1,0)')
for _,target,_ in auto:
    guard(f"SELECT IF(AUTO_INCREMENT=@compact_core_next_{target},1,0) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='{target}'")
emit('COMMIT;\nSET SESSION sql_mode=@compact_core_original_sql_mode;\nDROP TEMPORARY TABLE compact_core_relations;\nDROP TEMPORARY TABLE compact_core_unique_keys;\nDROP TEMPORARY TABLE compact_core_columns;\nDROP TEMPORARY TABLE compact_core_guard;')
with (ROOT/'sql/mysql/compact/copy/10-core.sql').open('w',encoding='utf-8',newline='\n') as output:
    output.write('\n'.join(sql)+'\n')

# A test source reconstructed from captured SOURCE declarations, not renamed target tables.
fixture=['-- Historical source fixture from saved inventory and 2026-10-14 summary DDL. ECS disposable schemas only.']
fixture_order=['organization_department','employee','users','account_employee_binding','model_management','device_management','device_usage_record','device_capture_alert','detection_work_unit','chat_session','detection_task','detection_work_unit_image','detection_quality_report','image_detection_data']
for name in fixture_order:
    table=sources.get(name) or source_definition(name)
    columns=[c['declaration'] for c in table['columns'].values()]
    constraints=[k for k in table['constraints'] if 'FOREIGN KEY' not in k.upper()]
    # Source charset defaults are made explicit only where the V15 source omits a server-dependent default.
    options=table['options']
    if not re.search(r'COLLATE\s*=',options,re.I):options+=' COLLATE=utf8mb4_0900_ai_ci'
    fixture.append('CREATE TABLE `'+name+'` (\n    '+',\n    '.join(columns+constraints)+'\n) '+options+';')
for child,column,parent,key,delete,update in relations:
    # NO ACTION is the omitted-clause default, equivalent to immediate RESTRICT for the admitted InnoDB engine.
    fixture.append(f'ALTER TABLE `{child}` ADD CONSTRAINT `fixture_{child}_{column}` FOREIGN KEY (`{column}`) REFERENCES `{parent}`(`{key}`) ON DELETE {delete} ON UPDATE '+('NO ACTION' if update=='RESTRICT' else update)+';')
for column,key,update in [('username','username','CASCADE'),('user_id','id','RESTRICT')]:
    fixture.append(f'ALTER TABLE chat_session ADD CONSTRAINT fixture_chat_session_{column} FOREIGN KEY (`{column}`) REFERENCES users(`{key}`) ON DELETE CASCADE ON UPDATE {update};')
path=ROOT/'doorhandle-module-detection/src/test/resources/compact/core-source-evidence.sql'
path.parent.mkdir(parents=True,exist_ok=True)
with path.open('w',encoding='utf-8',newline='\n') as output:
    output.write('\n\n'.join(fixture)+'\n')
print(json.dumps({'status':'AUTHORED_NOT_EXECUTED','coreTargets':len(core_names),'sourceTables':len(source_names),'mappedColumns':len(rows),'highWaterMarks':len(auto)}))
