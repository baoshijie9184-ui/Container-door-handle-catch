"""Inspect or apply additive V21 report tables and V22 Agent origins in the configured local database."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import pymysql
from pymysql.constants import CLIENT
from dotenv import dotenv_values

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
env = dotenv_values(root / '.env')
url = urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost', '127.0.0.1') or url.port not in (None, 3306) or url.path != '/doorhandledb':
    raise SystemExit('Only configured local doorhandledb is allowed')
migrations = []
for name in ('migration-V21-quality-report-approval.sql', 'migration-V22-agent-report-origin.sql'):
    sql = root / 'sql/mysql' / name
    copy = root / 'doorhandle-module-app/src/main/resources/db' / name
    if sql.read_bytes() != copy.read_bytes():
        raise SystemExit('Migration copies differ')
    migrations.append(sql)
with pymysql.connect(host=url.hostname, port=url.port or 3306, user=env['DB_USERNAME'], password=env['DB_PASSWORD'],
                     database='doorhandledb', charset='utf8mb4', client_flag=CLIENT.MULTI_STATEMENTS,
                     connect_timeout=5, read_timeout=60, autocommit=True) as connection:
    with connection.cursor() as cursor:
        if args.apply:
            for sql in migrations:
                cursor.execute(sql.read_text(encoding='utf-8'))
                while cursor.nextset():
                    pass
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox')")
        count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='detection_report_agent_origin'")
        origin = cursor.fetchone()[0]
        print(json.dumps({'database':'doorhandledb', 'applied':args.apply, 'reportTables':count, 'originTables':origin, 'ready':count==5 and origin==1}))
        if count != 5 or origin != 1:
            raise SystemExit(1)
