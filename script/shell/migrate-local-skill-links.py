"""Inspect/apply additive V27/V28/V29/V46 to local doorhandledb; preserve existing Skill history."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import pymysql
from pymysql.constants import CLIENT
from dotenv import dotenv_values

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply',action='store_true')
args=parser.parse_args();root=Path(__file__).resolve().parents[2]
env=dotenv_values(root/'.env');url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.port not in (None,3306) or url.path!='/doorhandledb':
    raise SystemExit('Only configured local doorhandledb is allowed')
name='migration-V27-linked-skill-download.sql'
sql=root/'sql/mysql'/name;copy=root/'doorhandle-module-app/src/main/resources/db'/name
if sql.read_bytes()!=copy.read_bytes():raise SystemExit('Migration copies differ')
upgrade=root/'sql/mysql/migration-V28-linked-skill-upgrade.sql';upgrade_copy=root/'doorhandle-module-app/src/main/resources/db/migration-V28-linked-skill-upgrade.sql'
if upgrade.read_bytes()!=upgrade_copy.read_bytes():raise SystemExit('Upgrade migration copies differ')
cleanup=root/'sql/mysql/migration-V29-skill-storage-cleanup.sql';cleanup_copy=root/'doorhandle-module-app/src/main/resources/db/migration-V29-skill-storage-cleanup.sql'
if cleanup.read_bytes()!=cleanup_copy.read_bytes():raise SystemExit('Cleanup migration copies differ')
lease=root/'sql/mysql/migration-V46-skill-download-leases.sql';lease_copy=root/'doorhandle-module-ai/src/main/resources/db/migration-V46-skill-download-leases.sql'
if lease.read_bytes()!=lease_copy.read_bytes():raise SystemExit('Lease migration copies differ')
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',client_flag=CLIENT.MULTI_STATEMENTS,autocommit=True) as connection:
    with connection.cursor() as cursor:
        if args.apply:
            cursor.execute(sql.read_text(encoding='utf-8'))
            while cursor.nextset():pass
            cursor.execute("SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_skill_download'")
            columns={row[0] for row in cursor.fetchall()}
            for statement in '\n'.join(line for line in upgrade.read_text(encoding='utf-8').splitlines() if not line.strip().startswith('--')).split(';'):
                if 'ADD COLUMN' in statement:
                    column=statement.split('ADD COLUMN',1)[1].strip().split()[0]
                    if column not in columns:cursor.execute(statement)
            cursor.execute(cleanup.read_text(encoding='utf-8'))
            while cursor.nextset():pass
            cursor.execute(lease.read_text(encoding='utf-8'))
            while cursor.nextset():pass

        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_skill_download'")
        tables=cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_skill_download' AND column_name IN ('target_skill_id','expected_skill_revision')")
        upgrade_columns=cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_skill_storage_command'")
        cleanup_tables=cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_skill_download_owner','agent_skill_download_lease','agent_skill_download_event')")
        lease_tables=cursor.fetchone()[0];ready=tables==1 and upgrade_columns==2 and cleanup_tables==1 and lease_tables==3
        print(json.dumps({'applied':args.apply,'ready':ready,'downloadTables':tables,'upgradeColumns':upgrade_columns,'cleanupTables':cleanup_tables,'leaseTables':lease_tables}))
        if not ready:raise SystemExit(1)
