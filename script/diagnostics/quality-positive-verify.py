"""Read-only business recheck of a completed demo run, without recreating tasks or repeating approvals."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
import requests

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory', required=True)
parser.add_argument('--base-url', default='http://127.0.0.1:18088')
args = parser.parse_args()
directory = Path(args.directory).resolve(strict=True)
if not directory.is_relative_to(ROOT / 'work'):
    parser.error('Use an existing project work evidence directory')
original = json.loads((directory / 'result.json').read_text(encoding='utf8'))
if original.get('passed') is not True:
    parser.error('Inspect partial work manually; this verifier only reads completed runs')
checks = []
session = requests.Session()
session.trust_env = False

def api(method, path, body=None):
    response = session.request(method, args.base_url.rstrip('/') + path, json=body, timeout=20)
    response.raise_for_status()
    value = response.json()
    assert value['code'] == 200
    return value['data']

def check(name, condition):
    assert condition, name
    checks.append(name)

api('POST', '/api/auth/login', {'username': 'supervisor.demo', 'password': os.environ['DOORHANDLE_DEMO_PASSWORD']})
report_id = original['reportId']
assert re.fullmatch(r'qr-[a-f0-9-]{36}', report_id)
tasks = original['tasks']
for kind, flow in [('normal-release', 'RELEASED'), ('rework-recheck', 'HOLD')]:
    task_id = tasks[kind]['taskId']
    assert re.fullmatch(r'det_[0-9]{8}_[0-9]{6}_[a-f0-9]{8}', task_id)
    task = api('GET', '/api/detection/tasks/' + task_id)
    trace = api('GET', '/api/detection/tasks/' + task_id + '/trace')
    check(kind + ' retains completed PTH result and disposition', task['status'] == 'COMPLETED' and task['successfulImages'] == 1 and trace['flowStatus'] == flow)
    if kind == 'rework-recheck':
        check('Rework record and timeline remain available after recheck', bool(trace['reworkResult']) and bool(trace['reworkCompletedAt']) and
              {'REWORK_COMPLETED', 'DISPATCHED', 'FINISHED', 'REVIEWED', 'DISPOSED'}.issubset({event['eventType'] for event in trace['timeline']}))
report = api('GET', '/api/detection/reports/' + report_id)
check('Approved report version persists on independent read', report['status'] == 'APPROVED')
audit = api('GET', '/api/detection/reports/' + report_id + '/audit')
check('All four report audit actions persist', {'CREATE', 'SUBMIT', 'APPROVE', 'EXPORT'}.issubset({entry['action'] for entry in audit}))
deadline = time.monotonic() + 30
while True:
    events = api('GET', '/api/detection/reports/' + report_id + '/events')
    if events and all(event['deliveryStatus'] == 'DELIVERED' and event.get('consumedAt') for event in events):
        break
    if time.monotonic() >= deadline:
        raise AssertionError('Report delivery/consumption is still unverified; no resend performed')
    time.sleep(1)
check('Both submit and approval events were delivered and consumed',
      {'detection.report.submitted.v1', 'detection.report.approved.v1'}.issubset({event['eventType'] for event in events}))
old = api('GET', '/api/detection/tasks/det_20261017_141939_23b7fd92/trace')
check('Previous needs-recheck task was not released', old['reviewConclusion'] == 'NEEDS_RECHECK' and old['flowStatus'] != 'RELEASED')
old_report = api('GET', '/api/detection/reports/qr-9bb5dc2f-656a-4a60-be54-0bc2b939da56')
check('Previous blocked report remains unapproved', old_report['status'] == 'SUBMITTED')
result = {'at': datetime.now(timezone(timedelta(hours=8))).isoformat(), 'passed': True, 'checks': checks,
          'events': events, 'businessMutationsExecuted': False}
(directory / 'persisted-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps({'passed': True, 'checks': len(checks), 'businessMutationsExecuted': False}))
