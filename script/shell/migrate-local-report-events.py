"""Inspect/apply additive V30 report delivery columns and receipts in local doorhandledb."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import pymysql
from dotenv import dotenv_values

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply',action='store_true')
args=parser.parse_args();root=Path(__file__).resolve().parents[2]
env=dotenv_values(root/'.env');url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.port not in (None,3306) or url.path!='/doorhandledb':
    raise SystemExit('Only configured local doorhandledb is allowed')
source=root/'sql/mysql/migration-V30-report-event-delivery.sql'
copy=root/'doorhandle-module-app/src/main/resources/db'/source.name
if source.read_bytes()!=copy.read_bytes():raise SystemExit('Migration copies differ')
columns={'attempts','next_attempt_at','lease_token','lease_expires_at','delivered_at','last_error_code'}
indexes={'idx_report_event_due','idx_report_event_lease','idx_report_event_report'}
tables={'detection_report_event_receipt','detection_report_event_state'}
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',connect_timeout=5,read_timeout=60,autocommit=True) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_report_outbox'")
        existing={row[0] for row in cursor.fetchall()}
        if not existing:raise SystemExit('Apply V21 first')
        cursor.execute("SELECT DISTINCT index_name FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='detection_report_outbox'")
        present_indexes={row[0] for row in cursor.fetchall()}
        if args.apply:
            sql='\n'.join(line for line in source.read_text(encoding='utf-8').splitlines() if not line.strip().startswith('--'))
            for statement in sql.split(';'):
                if not statement.strip():continue
                if 'ADD COLUMN' in statement:
                    if statement.split('ADD COLUMN',1)[1].strip().split()[0] in existing:continue
                elif 'CREATE INDEX' in statement:
                    if statement.split('CREATE INDEX',1)[1].strip().split()[0] in present_indexes:continue
                cursor.execute(statement)
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_report_outbox'")
        found_columns={row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT DISTINCT index_name FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='detection_report_outbox'")
        found_indexes={row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()")
        found_tables={row[0] for row in cursor.fetchall()}
        ready=columns<=found_columns and indexes<=found_indexes and tables<=found_tables
        cursor.execute("SELECT delivery_status,COUNT(*) FROM detection_report_outbox GROUP BY delivery_status")
        status_counts={status:count for status,count in cursor.fetchall()}
        print(json.dumps({'applied':args.apply,'ready':ready,'columns':len(columns & found_columns),'indexes':len(indexes & found_indexes),'tables':len(tables & found_tables),'outboxStatusCounts':status_counts}))
        if not ready:raise SystemExit(1)
