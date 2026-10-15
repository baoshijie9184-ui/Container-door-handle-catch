"""Explicit local-only V20 migration. Credentials stay in the ignored project .env."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import pymysql
from pymysql.constants import CLIENT
from dotenv import dotenv_values

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true', help='Apply the additive V20 migration; otherwise inspect readiness only')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
env = dotenv_values(root / '.env')
url = urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost', '127.0.0.1') or url.port not in (None, 3306) or url.path != '/doorhandledb':
    raise SystemExit('Only the configured local doorhandledb is allowed')
sql = root / 'sql/mysql/migration-V20-account-employee-department.sql'
classpath = root / 'doorhandle-module-app/src/main/resources/db/migration-V20-account-employee-department.sql'
if sql.read_bytes() != classpath.read_bytes():
    raise SystemExit('Migration copies differ')
with pymysql.connect(host=url.hostname, port=url.port or 3306, user=env['DB_USERNAME'], password=env['DB_PASSWORD'],
                     database='doorhandledb', charset='utf8mb4', client_flag=CLIENT.MULTI_STATEMENTS,
                     connect_timeout=5, read_timeout=60, autocommit=True) as connection:
    with connection.cursor() as cursor:
        if args.apply:
            cursor.execute(sql.read_text(encoding='utf-8'))
            while cursor.nextset():
                pass
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('organization_department','account_employee_binding','organization_binding_audit')")
        tables = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='employee' AND column_name='department_id'")
        column = cursor.fetchone()[0]
        result = {'database': 'doorhandledb', 'applied': args.apply, 'tables': tables, 'employeeDepartmentColumn': column, 'ready': tables == 3 and column == 1}
        if result['ready']:
            cursor.execute('SELECT COUNT(*) FROM organization_department')
            result['departments'] = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM employee WHERE department_id IS NULL')
            result['employeesWithoutDepartment'] = cursor.fetchone()[0]
        print(json.dumps(result))
        if not result['ready']:
            raise SystemExit(1)
