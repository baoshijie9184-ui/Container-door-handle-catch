"""Explicit additive fixed MCP migrations, restricted to configured local doorhandledb."""
import argparse,json
from pathlib import Path
from urllib.parse import urlparse
import pymysql
from pymysql.constants import CLIENT
from dotenv import dotenv_values
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true')
parser.add_argument('--execution-receipts',action='store_true',help='Include V47-V49 receipt tables and process evidence; does not enable runtime flags')
parser.add_argument('--lifecycle',action='store_true',help='Include V34/V47-V49/V58 for current lifecycle readers; does not enable runtime flags')
parser.add_argument('--native-install',action='store_true',help='Select lifecycle and V58 native installer evidence; does not enable runtime flags')
parser.add_argument('--shared-images',action='store_true',help='Select lifecycle and V59/V60 image and deployment fences; does not enable runtime flags')
args=parser.parse_args()
args.lifecycle=args.lifecycle or args.native_install or args.shared_images
root=Path(__file__).resolve().parents[2];env=dotenv_values(root/'.env');url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.path!='/doorhandledb' or url.port not in (None,3306):raise SystemExit('Only configured local doorhandledb is allowed')
name='migration-V25-local-mcp.sql';sql=root/'sql/mysql'/name;copy=root/'doorhandle-module-app/src/main/resources/db'/name
if sql.read_bytes()!=copy.read_bytes():raise SystemExit('Migration copies differ')
additional=[]
if args.lifecycle:additional.append(('migration-V34-mcp-install-queue.sql','doorhandle-module-app'))
if args.execution_receipts or args.lifecycle:
    additional += [(name,'doorhandle-module-ai') for name in ('migration-V47-mcp-execution-receipts.sql','migration-V48-fetch-installation-lifecycle.sql','migration-V49-mcp-process-evidence.sql')]
if args.lifecycle:additional.append(('migration-V58-native-fetch-install-evidence.sql','doorhandle-module-ai'))
if args.shared_images:additional.extend([(name,'doorhandle-module-ai') for name in ('migration-V59-fetch-shared-images.sql','migration-V60-fetch-deployment-retention.sql')])
for migration,module in additional:
    original=root/'sql/mysql'/migration;mirror=root/module/'src/main/resources/db'/migration
    if original.read_bytes()!=mirror.read_bytes():raise SystemExit('Additional migration copies differ')
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',client_flag=CLIENT.MULTI_STATEMENTS,autocommit=True) as connection:
    with connection.cursor() as cursor:
        process_columns={
            ('agent_mcp_execution','transport'):('VARCHAR(32) NOT NULL DEFAULT \'STREAMABLE_HTTP\'','varchar(32)','NO','STREAMABLE_HTTP',None),
            ('agent_fetch_installation','reconcile_request'):('VARCHAR(64) COLLATE utf8mb4_bin NULL','varchar(64)','YES',None,'utf8mb4_bin'),
            ('agent_fetch_installation','reconcile_expires_at'):('DATETIME(6) NULL','datetime(6)','YES',None,None),
            ('agent_fetch_installation','writer_evidence_code'):('VARCHAR(48) NULL','varchar(48)','YES',None,None),
        }
        native_columns={
            ('agent_mcp_install_worker','writer_transport'):('VARCHAR(32) NOT NULL DEFAULT \'STREAMABLE_HTTP\'','varchar(32)','NO','STREAMABLE_HTTP',None),
            ('agent_mcp_install_worker','native_pool_id'):('CHAR(32) COLLATE utf8mb4_bin NULL','char(32)','YES',None,'utf8mb4_bin'),
            ('agent_fetch_installation','reserved_bytes'):('BIGINT NOT NULL DEFAULT 2097152','bigint','NO','2097152',None),
        }
        image_columns={('agent_mcp_execution','image_id'):('VARCHAR(80) COLLATE utf8mb4_bin NULL','varchar(80)','YES',None,'utf8mb4_bin')}
        retention_columns={('agent_fetch_image_command','retention_protocol'):('INT NOT NULL DEFAULT 3','int','NO','3',None)}
        def process_column(table,column,expected,apply):
            cursor.execute('SELECT COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,COLLATION_NAME FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s',(table,column))
            row=cursor.fetchone()
            if row is None:
                if apply:cursor.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+expected[0]);return True
                return False
            if row[:3]!=(expected[1],expected[2],expected[3]) or expected[4] is not None and row[3]!=expected[4]:raise SystemExit('Existing process column signature differs')
            return True
        if args.apply:
            cursor.execute(sql.read_text(encoding='utf-8'))
            while cursor.nextset():pass
            for migration,_ in additional:
                text=(root/'sql/mysql'/migration).read_text(encoding='utf-8')
                if migration=='migration-V49-mcp-process-evidence.sql':
                    for (table,column),expected in process_columns.items():process_column(table,column,expected,True)
                    text=text[text.index('CREATE TABLE'):]
                if migration=='migration-V58-native-fetch-install-evidence.sql':
                    for (table,column),expected in native_columns.items():process_column(table,column,expected,True)
                    continue
                if migration=='migration-V59-fetch-shared-images.sql':
                    text=text[:text.index('ALTER TABLE')]
                if migration=='migration-V60-fetch-deployment-retention.sql':
                    for (table,column),expected in retention_columns.items():process_column(table,column,expected,True)
                    text=text[text.index('CREATE TABLE'):]
                cursor.execute(text)
                while cursor.nextset():pass
                if migration=='migration-V59-fetch-shared-images.sql':
                    for (table,column),expected in image_columns.items():process_column(table,column,expected,True)
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('agent_local_mcp','agent_local_mcp_audit')")
        count=cursor.fetchone()[0];expected=['agent_local_mcp','agent_local_mcp_audit']
        if args.lifecycle:expected+=['agent_mcp_install_job']
        if args.execution_receipts or args.lifecycle:expected+=['agent_mcp_execution','agent_mcp_execution_command','agent_fetch_installation','agent_fetch_lifecycle_command','agent_mcp_install_worker']
        if args.shared_images:expected+=['agent_fetch_image','agent_fetch_image_command','agent_fetch_image_retention','agent_fetch_image_retention_control','agent_fetch_image_retention_event']
        placeholders=','.join(['%s']*len(expected))
        cursor.execute('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('+placeholders+')',expected)
        ready=cursor.fetchone()[0]==len(expected)
        if args.execution_receipts or args.lifecycle:
            for (table,column),signature in process_columns.items():ready=process_column(table,column,signature,False) and ready
        if args.lifecycle:
            for (table,column),signature in native_columns.items():ready=process_column(table,column,signature,False) and ready
        if args.shared_images:
            for (table,column),signature in image_columns.items():ready=process_column(table,column,signature,False) and ready
            for (table,column),signature in retention_columns.items():ready=process_column(table,column,signature,False) and ready
        print(json.dumps({'database':'doorhandledb','applied':args.apply,'mcpTables':count,'selectedAdditionalMigrations':[entry[0] for entry in additional],'ready':ready}))
        if not ready:raise SystemExit(1)
