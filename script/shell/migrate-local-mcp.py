"""Explicit additive V25 migration, restricted to configured local doorhandledb."""
import argparse,json
from pathlib import Path
from urllib.parse import urlparse
import pymysql
from pymysql.constants import CLIENT
from dotenv import dotenv_values
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
root=Path(__file__).resolve().parents[2];env=dotenv_values(root/'.env');url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.path!='/doorhandledb' or url.port not in (None,3306):raise SystemExit('Only configured local doorhandledb is allowed')
name='migration-V25-local-mcp.sql';sql=root/'sql/mysql'/name;copy=root/'doorhandle-module-app/src/main/resources/db'/name
if sql.read_bytes()!=copy.read_bytes():raise SystemExit('Migration copies differ')
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',client_flag=CLIENT.MULTI_STATEMENTS,autocommit=True) as connection:
    with connection.cursor() as cursor:
        if args.apply:
            cursor.execute(sql.read_text(encoding='utf-8'))
            while cursor.nextset():pass
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_local_mcp','agent_local_mcp_audit')")
        count=cursor.fetchone()[0];print(json.dumps({'database':'doorhandledb','applied':args.apply,'mcpTables':count,'ready':count==2}))
        if count!=2:raise SystemExit(1)
