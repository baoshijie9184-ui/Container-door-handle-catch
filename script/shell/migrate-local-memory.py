"""Apply additive V26 memory governance tables and configure a private local bridge token."""
import argparse
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values
import pymysql
from pymysql.constants import CLIENT

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply',action='store_true')
args=parser.parse_args();root=Path(__file__).resolve().parents[2]
env_file=root/'.env';env=dotenv_values(env_file);url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.port not in (None,3306) or url.path!='/doorhandledb':raise SystemExit('Only configured local doorhandledb is allowed')
source=root/'sql/mysql/migration-V26-personal-memory-governance.sql'
copy=root/'doorhandle-module-app/src/main/resources/db'/source.name
if source.read_bytes()!=copy.read_bytes():raise SystemExit('Migration copies differ')
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',client_flag=CLIENT.MULTI_STATEMENTS,autocommit=True) as connection:
    with connection.cursor() as cursor:
        if args.apply:
            cursor.execute(source.read_text(encoding='utf-8'))
            while cursor.nextset():pass
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_memory_preference','agent_memory_audit')")
        tables=cursor.fetchone()[0]
configured=bool(env.get('MEM0_BRIDGE_TOKEN'))
if args.apply and not configured:
    # 已忽略的本机配置；不输出密钥，也不覆盖已有非空密钥。
    content=env_file.read_text(encoding='utf-8');line='MEM0_BRIDGE_TOKEN='+secrets.token_urlsafe(36)
    pattern=r'^\s*(?:export\s+)?MEM0_BRIDGE_TOKEN\s*=.*$'
    if re.search(pattern,content,re.M):content=re.sub(pattern,line,content,flags=re.M)
    else:content=content.rstrip()+'\n'+line+'\n'
    env_file.write_text(content,encoding='utf-8');configured=True
print(json.dumps({'database':'doorhandledb','applied':args.apply,'memoryTables':tables,'bridgeTokenConfigured':configured,'ready':tables==2 and configured}))
if tables!=2 or not configured:raise SystemExit(1)
