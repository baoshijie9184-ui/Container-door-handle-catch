"""Verify account/employee identity against local MySQL and the running backend.
Only inserts marked org-fixture-* accounts/employees; never binds original accounts.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
import pymysql
import requests
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
env = dotenv_values(root / '.env')
url = urlparse(env['DB_URL'].removeprefix('jdbc:'))
assert url.hostname in ('localhost', '127.0.0.1') and url.path == '/doorhandledb' and url.port in (None, 3306)
base = 'http://127.0.0.1:8080'
headers = {'X-Organization-Action': 'update'}
prefix = 'org-fixture-' + uuid4().hex[:8]
checks = []

def check(name, condition):
    assert condition, name
    checks.append({'name': name, 'passed': True})

def login(username):
    client = requests.Session(); client.trust_env = False
    response = client.post(base + '/api/auth/login', json={'username': username, 'password': '123456'}, timeout=20)
    assert response.status_code == 200 and response.json()['code'] == 200, 'Fixture login failed'
    return client

def data(client, method, path, **kwargs):
    response = client.request(method, base + path, timeout=20, **kwargs)
    assert response.status_code == 200 and response.json()['code'] == 200, (path, response.status_code, response.json().get('message'))
    return response.json()['data']

boss = login('supervisor.demo')
depart = data(boss, 'POST', '/api/organization/departments', json={'name': prefix}, headers=headers)
duplicate = boss.post(base + '/api/organization/departments', json={'name': prefix}, headers=headers, timeout=20)
check('duplicate_department_409', duplicate.status_code == 409)
staff_ids = []
for number in range(3):
    employee = data(boss, 'POST', '/api/employees', json={
        'name': prefix + '-' + str(number), 'employeeNumber': prefix + '-' + str(number), 'contact': '13900000000',
        'departmentId': depart['id'], 'department': 'untrusted-name', 'employeeType': 'DETECTION',
        'gender': '男', 'hireDate': '2026-10-13', 'status': 'ACTIVE'
    })
    check('canonical_department_' + str(number), employee['department'] == prefix and employee['departmentId'] == depart['id'])
    staff_ids.append(employee['id'])

usernames = [prefix + '-a', prefix + '-b']
with pymysql.connect(host=url.hostname, port=url.port or 3306, user=env['DB_USERNAME'], password=env['DB_PASSWORD'],
                     database='doorhandledb', charset='utf8mb4', autocommit=True) as connection:
    with connection.cursor() as cursor:
        for username in usernames:
            cursor.execute("INSERT INTO users(username,password,role) SELECT %s,password,'INSPECTOR' FROM users WHERE username='inspector.demo'", (username,))
        cursor.execute('SELECT id,username FROM users WHERE username IN (%s,%s) ORDER BY username', usernames)
        user_ids = {name: id for id, name in cursor.fetchall()}

a = login(usernames[0]); b = login(usernames[1]); aid = user_ids[usernames[0]]; bid = user_ids[usernames[1]]
accounts = data(boss, 'GET', '/api/organization/accounts', params={'keyword': prefix, 'page': 1, 'size': 20})
check('safe_account_list', accounts['total'] == 2 and all(not set(row).intersection({'password', 'email', 'phone', 'token'}) for row in accounts['records']))
check('employee_cannot_list_accounts', a.get(base + '/api/organization/accounts', timeout=20).status_code == 403)
check('employee_cannot_bind', a.put(base + f'/api/organization/accounts/{bid}/employee', json={'employeeId': staff_ids[0], 'version': 0}, headers=headers, timeout=20).status_code == 403)
check('employee_cannot_read_other_audit', a.get(base + f'/api/organization/accounts/{bid}/audit', timeout=20).status_code == 403)

bound = data(boss, 'PUT', f'/api/organization/accounts/{aid}/employee', json={'employeeId': staff_ids[0], 'version': 0}, headers=headers)
check('bound_identity_and_scope', bound['bindingVersion'] == 1 and bound['dataScope'] == 'OWNED_OR_ASSIGNED' and bound['employeeId'] == staff_ids[0])
check('mine_refreshes_without_login', data(a, 'GET', '/api/organization/me')['employeeId'] == staff_ids[0])
check('auth_check_includes_identity', data(a, 'GET', '/api/auth/check')['identity']['departmentId'] == depart['id'])
data(boss, 'PUT', f'/api/organization/accounts/{aid}/employee', json={'employeeId': staff_ids[0], 'version': 1}, headers=headers)
check('repeat_has_one_audit', len(data(boss, 'GET', f'/api/organization/accounts/{aid}/audit')) == 1)
check('duplicate_employee_409', boss.put(base + f'/api/organization/accounts/{bid}/employee', json={'employeeId': staff_ids[0], 'version': 0}, headers=headers, timeout=20).status_code == 409)
check('stale_version_409', boss.put(base + f'/api/organization/accounts/{aid}/employee', json={'employeeId': staff_ids[1], 'version': 0}, headers=headers, timeout=20).status_code == 409)
deleted = boss.delete(base + f'/api/employees/{staff_ids[0]}', timeout=20)
check('bound_employee_delete_denied', deleted.json()['code'] == 409)
check('missing_header_denied', boss.put(base + f'/api/organization/accounts/{aid}/employee', json={'employeeId': None, 'version': 1}, timeout=20).json()['code'] == 400)
check('missing_employee_404', boss.put(base + f'/api/organization/accounts/{bid}/employee', json={'employeeId': 9223372036854775806, 'version': 0}, headers=headers, timeout=20).status_code == 404)

employee = data(boss, 'GET', f'/api/employees/{staff_ids[0]}')
employee['status'] = 'RESIGNED'
data(boss, 'PUT', f'/api/employees/{staff_ids[0]}', json=employee)
check('departed_employee_still_readable', data(boss, 'GET', f'/api/employees/{staff_ids[0]}')['status'] == 'RESIGNED')
check('identity_reads_current_status', data(a, 'GET', '/api/organization/me')['employeeStatus'] == 'RESIGNED')
check('inactive_employee_binding_denied', boss.put(base + f'/api/organization/accounts/{bid}/employee', json={'employeeId': staff_ids[0], 'version': 0}, headers=headers, timeout=20).status_code == 409)
employee = data(boss, 'GET', f'/api/employees/{staff_ids[0]}'); employee['status'] = 'ACTIVE'
data(boss, 'PUT', f'/api/employees/{staff_ids[0]}', json=employee)
cleared = data(boss, 'PUT', f'/api/organization/accounts/{aid}/employee', json={'employeeId': None, 'version': 1}, headers=headers)
check('unbind_preserves_version', cleared['bindingVersion'] == 2 and cleared.get('employeeId') is None)

def compete(item):
    user_id, version = item
    client = requests.Session(); client.trust_env = False; client.cookies.update(boss.cookies)
    return client.put(base + f'/api/organization/accounts/{user_id}/employee', json={'employeeId': staff_ids[0], 'version': version}, headers=headers, timeout=20).status_code

with ThreadPoolExecutor(max_workers=2) as workers:
    statuses = list(workers.map(compete, [(aid, 2), (bid, 0)]))
check('mysql_concurrent_binding_one_winner', sorted(statuses) == [200, 409])
for row in data(boss, 'GET', '/api/organization/accounts', params={'keyword': prefix, 'size': 20})['records']:
    if row.get('employeeId') is not None:
        data(boss, 'PUT', f"/api/organization/accounts/{row['userId']}/employee", json={'employeeId': None, 'version': row['bindingVersion']}, headers=headers)

artifact = {'prefix': prefix, 'usernames': usernames, 'userIds': user_ids, 'employeeIds': staff_ids, 'departmentId': depart['id'], 'checks': checks, 'fixtureDataRetained': True}
(root / 'work/organization-local-acceptance.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'checks': len(checks), 'allPassed': True, 'artifact': 'work/organization-local-acceptance.json'}))
