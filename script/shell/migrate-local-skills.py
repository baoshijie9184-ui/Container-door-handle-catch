"""Inspect/apply V23 and V24 skill tables/nullable source columns in local doorhandledb."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import pymysql
from pymysql.constants import CLIENT
from dotenv import dotenv_values

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply',action='store_true')
args=parser.parse_args(); root=Path(__file__).resolve().parents[2]
env=dotenv_values(root/'.env'); url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.port not in (None,3306) or url.path!='/doorhandledb':
    raise SystemExit('Only configured local doorhandledb is allowed')
migrations=[]
for name in ['migration-V23-agent-skill-evolution.sql','migration-V24-external-skill-import.sql']:
    sql=root/'sql/mysql'/name; copy=root/'doorhandle-module-app/src/main/resources/db'/name
    if sql.read_bytes()!=copy.read_bytes(): raise SystemExit('Migration copies differ')
    migrations.append(sql.read_text(encoding='utf-8'))
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',client_flag=CLIENT.MULTI_STATEMENTS,autocommit=True) as connection:
    with connection.cursor() as cursor:
        if args.apply:
            cursor.execute(migrations[0])
            while cursor.nextset(): pass
            # 每个 DDL 独立检查，重复执行及上次中途退出均不会覆盖已有数据。
            cursor.execute(migrations[1].split('-- 以下列变更')[0])
            while cursor.nextset(): pass
            cursor.execute("SELECT COLUMN_NAME,IS_NULLABLE FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_skill_version'")
            columns=dict(cursor.fetchall())
            if columns.get('source_run_id')!='YES': cursor.execute('ALTER TABLE agent_skill_version MODIFY source_run_id VARCHAR(128) NULL')
            if 'source_type' not in columns: cursor.execute("ALTER TABLE agent_skill_version ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'RUN'")
            if 'source_import_id' not in columns: cursor.execute('ALTER TABLE agent_skill_version ADD COLUMN source_import_id VARCHAR(64) NULL')
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_skill_source','agent_learned_skill','agent_skill_version','agent_skill_eval','agent_skill_audit')")
        count=cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_skill_import'")
        imports=cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_skill_version' AND (COLUMN_NAME IN ('source_type','source_import_id') OR COLUMN_NAME='source_run_id' AND IS_NULLABLE='YES')")
        source_columns=cursor.fetchone()[0]; ready=count==5 and imports==1 and source_columns==3
        print(json.dumps({'database':'doorhandledb','applied':args.apply,'skillTables':count,'importTables':imports,'sourceColumns':source_columns,'ready':ready}))
        if not ready: raise SystemExit(1)
