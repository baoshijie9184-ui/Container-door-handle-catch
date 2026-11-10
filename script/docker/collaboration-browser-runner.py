#!/usr/bin/env python3
"""Actual Vue/React collaboration acceptance, inside a runtime-owned ECS container.

No mock routes, alternate business pages, external model calls, host Docker access, or
credential artifacts. Runtime owns provisioning/cleanup and the full nine
business scenarios; this component consumes that stack without replacing them.
Exit: 0 required browser checks pass; 1 assertion/coverage missing; 2 admission.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit, urlencode


PLAYWRIGHT_VERSION = '1.65.0'
CHROMIUM_VERSION = '158.0.8127.18'
REQUIRED = ('four-roles-real-ui', 'react-real-workbench', 'real-device-created',
            'same-version-ui-conflict', 'real-history-diff', 'request-replay',
            'inspector-report-and-scope', 'native-sse-reconnect',
            'notification-failure-recovery', 'same-account-device-logout',
            'late-account-switch', 'refresh-logout-race', 'twenty-accounts-forty-tabs',
            'http1-shared-connections', 'latency-p95', 'resource-samples',
            'account-disable-revocation', 'artifact-secret-boundary',
            'model-stream-save-connection-budget')
CASE_CHECKS = {
    'A01': ('four-roles-real-ui',), 'A03': ('inspector-report-and-scope',),
    'A04': ('same-version-ui-conflict',), 'A06': ('request-replay',),
    'A07': ('request-replay',), 'A09': ('twenty-accounts-forty-tabs',),
    'A10': ('same-version-ui-conflict',), 'A11': ('inspector-report-and-scope',),
    'A12': ('account-disable-revocation',), 'A13': ('native-sse-reconnect',),
    'A14': ('notification-failure-recovery',),
    'A15': ('http1-shared-connections', 'late-account-switch'),
    'A17': ('artifact-secret-boundary',), 'A20': ('resource-samples',),
    'A21': ('http1-shared-connections', 'latency-p95', 'model-stream-save-connection-budget'),
    'A22': ('native-sse-reconnect', 'account-disable-revocation'),
    'A23': ('native-sse-reconnect',), 'A24': ('four-roles-real-ui',),
    'A25': ('same-account-device-logout',), 'A26': ('late-account-switch',),
    'A27': ('refresh-logout-race',),
    'A28': ('account-disable-revocation',)}
LIMITS = {
    'A02': 'No collector/maintenance login fixture: retained HTTP/eligibility gates must supply this evidence.',
    'A03': 'Actual inspector report edit only; other mutation routes remain with HTTP/DB gates.',
    'A04': 'Actual device form concurrent CAS only; employee/model/task compound paths remain with HTTP/DB gates.',
    'A05': 'Provided worker-completed task is already reviewed; no mutually readable unclaimed task fixture is manufactured.',
    'A06': 'Real device UI command replay only; quota/model creation replay remains in the original business scenarios.',
    'A08': 'No audit-failure injection privilege in a browser container; existing transaction/DB gates remain required.',
    'A09': 'Real filtered first page/focus/scroll and background convergence; multi-page deletion boundary is not asserted.',
    'A11': 'Private report guessed by a peer is denied; exhaustive event/filter guessing remains with HTTP gates.',
    'A12': 'Actual account disable and page cleanup only; assignment and role downgrade need separate fixtures.',
    'A13': 'Actual SSE proxy disconnect/reconnect only; backend restart and event reordering are not simulated as success.',
    'A16': 'No legacy/deleted-resource fixture; retained migration/history gates must supply this evidence.',
    'A17': 'Evidence redaction and locator-only SSE checked; attachment/large result field fixtures remain with HTTP gates.',
    'A18': 'Browser component does not alter or replace migration, table-count, constraints or recovery gates.',
    'A19': 'Browser component has no service restart privilege; persistence/restart gate remains required.',
    'A20': 'Browser cgroup/connection samples only; bounded backend queues and slow-client isolation remain with runtime gates.',
    'A21': 'Two actual AGUI streams use the owned scripted provider while actual device forms save; public HTTP/2 and external model capacity are not asserted.',
    'A24': 'Independent Chromium browser contexts and cookie jars; no claim of distinct physical devices or browser engines.',
    'A26': 'Actual delayed logout/GET completion and old device draft; upload/hash and AGUI/MCP delayed intents remain in frontend/HTTP gates.',
    'A27': 'Actual concurrent browser refresh and delayed refresh headers after logout/B login; expiry, process restart and DB transaction interleavings remain with session gates.',
    'A28': 'Actual disable with existing session; employee-type/status qualification revocation remains with HTTP/DB gates.'}


class AdmissionError(Exception): pass
class CheckError(Exception): pass


def controlled_error(error):
    result = {'errorType': type(error).__name__}
    if isinstance(error, (CheckError, AdmissionError)) and re.fullmatch(r'[a-z0-9_]{1,120}', str(error)):
        result['reason'] = str(error)
    frames = [frame for frame in traceback.extract_tb(error.__traceback__)
              if Path(frame.filename).name == Path(__file__).name]
    if frames:
        result['runnerLine'] = frames[-1].lineno
    return result


def require(condition, code):
    if not condition:
        raise CheckError(code)


def sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def load_module(path):
    spec = importlib.util.spec_from_file_location('collaboration_browser_proxy', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def unwrap(value):
    if isinstance(value, dict) and 'code' in value:
        require(value['code'] == 200, 'business_response_rejected')
        return value.get('data')
    return value


def stream_probe_spec(descriptor):
    spec = descriptor.get('fixtures', {}).get('modelStreamProbes', {})
    require(isinstance(spec, dict) and set(spec) == {'schemaVersion', 'kind', 'modelId', 'streamDelayMillis',
            'saveMaxMillis', 'completionTimeoutMillis', 'markers'}, 'actual_model_stream_fixture_required')
    require(spec.get('schemaVersion') == 1 and spec.get('kind') == 'doorhandle-owned-model-stream-probes'
            and isinstance(spec.get('modelId'), str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', spec['modelId']),
            'owned_model_stream_descriptor_invalid')
    require(all(type(spec.get(key)) is int and spec[key] == value for key, value in {
        'streamDelayMillis': 15000, 'saveMaxMillis': 2000, 'completionTimeoutMillis': 45000}.items()),
        'bounded_model_stream_timing_required')
    markers = spec.get('markers')
    require(isinstance(markers, list) and len(markers) == 2
            and all(isinstance(value, str) and re.fullmatch(r'a21-stream-[a-f0-9]{24}', value)
                    and descriptor['ownership']['token'] not in value for value in markers)
            and len(set(markers)) == 2, 'two_safe_model_stream_markers_required')
    return spec


def read_cgroup():
    root = Path('/sys/fs/cgroup')
    def read(name):
        path = root / name
        return path.read_text().strip() if path.is_file() else None
    return {name: read(name) for name in ('memory.max', 'memory.current', 'memory.peak',
            'memory.events', 'cpu.max', 'cpu.stat', 'pids.max', 'pids.current', 'pids.events')}


class ResourceSampler:
    def __init__(self):
        self.samples = []
        self.ended = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.ended.is_set():
            value = read_cgroup()
            value['at'] = now()
            try:
                value['runnerThreads'] = len(list(Path('/proc/self/task').iterdir()))
            except OSError:
                value['runnerThreads'] = None
            self.samples.append(value)
            self.ended.wait(1)

    def start(self): self.thread.start()
    def close(self): self.ended.set(); self.thread.join(timeout=2)


def validate(descriptor, accounts, output):
    if sys.platform != 'linux' or not Path('/.dockerenv').is_file():
        raise AdmissionError('owned_linux_container_required')
    if descriptor.get('schemaVersion') != 1 or descriptor.get('upstream') != 'http://ui:80':
        raise AdmissionError('descriptor_schema_or_upstream_invalid')
    if not re.fullmatch(r'[a-f0-9]{40}', descriptor.get('commit', '')) or not re.fullmatch(r'[a-f0-9]{64}', descriptor.get('sourceSha256', '')):
        raise AdmissionError('fixed_source_identity_required')
    owner = descriptor.get('ownership', {})
    if not all(isinstance(owner.get(key), str) and owner[key] for key in ('project', 'network', 'token')):
        raise AdmissionError('runtime_ownership_required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', owner['project']) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', owner['network']):
        raise AdmissionError('invalid_ownership_name')
    runtime = descriptor.get('runtime', {})
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', runtime.get('browserImageId', '')) or not re.fullmatch(r'[a-f0-9]{64}', runtime.get('browserContainerId', '')):
        raise AdmissionError('externally_verified_browser_identity_required')
    if socket.gethostname() != runtime['browserContainerId'][:12]:
        raise AdmissionError('browser_container_hostname_identity_mismatch')
    # Docker cgroup namespaces legitimately expose 0::/. Finite readable limits,
    # Docker's marker, no socket, and the external runtime inspect are all needed.
    if Path('/var/run/docker.sock').exists():
        raise AdmissionError('host_docker_socket_forbidden')
    limits = read_cgroup()
    try:
        memory = int(limits['memory.max'])
        pids = int(limits['pids.max'])
        quota, period = map(int, limits['cpu.max'].split())
    except (ValueError, TypeError, AttributeError):
        raise AdmissionError('finite_cgroup_v2_limits_required') from None
    if memory != runtime.get('memoryLimitBytes') or memory < 2 * 1024**3 or pids != runtime.get('pidsLimit') or not 256 <= pids <= 2048:
        raise AdmissionError('browser_memory_or_pids_budget_mismatch')
    if quota <= 0 or period <= 0 or abs(quota / period - float(runtime.get('cpuLimit', 0))) > .001:
        raise AdmissionError('browser_cpu_budget_mismatch')
    if importlib.metadata.version('playwright') != PLAYWRIGHT_VERSION:
        raise AdmissionError('pinned_playwright_required')
    expected = {'inspector', 'peer', 'supervisor', 'reviewer'} | {f'load_{index:02}' for index in range(1, 17)}
    if set(accounts) != expected or len({str(item.get('userId')) for item in accounts.values()}) != 20:
        raise AdmissionError('twenty_distinct_owned_accounts_required')
    for alias, item in accounts.items():
        if item.get('role') not in ('SUPERVISOR', 'INSPECTOR') or not isinstance(item.get('username'), str) or not item.get('password') or not re.fullmatch(r'[1-9]\d*', str(item.get('userId', ''))):
            raise AdmissionError('account_contract_invalid')
        if alias in ('supervisor', 'reviewer') and item['role'] != 'SUPERVISOR':
            raise AdmissionError('two_supervisors_required')
        if alias in ('inspector', 'peer') and item['role'] != 'INSPECTOR':
            raise AdmissionError('two_inspectors_required')
    budgets = descriptor.get('budgets', {})
    if budgets.get('accounts') != 20 or budgets.get('tabsPerAccount') != 2 or not 20 <= budgets.get('minimumLatencySamples', 0) <= 2000 or not 1 <= budgets.get('p95MaxMs', 0) <= 2000 or not 300 <= budgets.get('timeoutSeconds', 0) <= 1800:
        raise AdmissionError('browser_acceptance_budget_invalid')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(descriptor.get('fixtures', {}).get('reportTaskId', ''))):
        raise AdmissionError('actual_completed_task_fixture_required')
    stream_probe_spec(descriptor)
    if output.resolve() != Path('/evidence') or output.is_symlink():
        raise AdmissionError('owned_evidence_mount_required')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise AdmissionError('empty_owned_evidence_directory_required')
    return limits


class Evidence:
    def __init__(self, descriptor, accounts, output):
        self.output = output
        self.usernames = {str(value['username']) for value in accounts.values()}
        self.passwords = {str(value['password']) for value in accounts.values()}
        self.secrets = set(self.passwords)
        self.secrets.add(descriptor['ownership']['token'])
        self.data = {'schemaVersion': 1, 'startedAt': now(), 'status': 'FAIL',
            'commit': descriptor['commit'], 'sourceSha256': descriptor['sourceSha256'],
            'ownership': {key + 'Sha256': sha(descriptor['ownership'][key]) for key in ('project', 'network')},
            'runtime': descriptor['runtime'], 'accounts': {key: {'userId': str(value['userId']), 'role': value['role']} for key, value in accounts.items()},
            'tool': {'playwright': PLAYWRIGHT_VERSION, 'expectedChromium': CHROMIUM_VERSION},
            'topology': {'browserOrigin': 'container-loopback-ephemeral-port', 'upstream': 'http://ui:80',
                'transport': 'transparent-streaming-http1.1', 'secureContextReason': 'standard localhost trust; no insecure-origin flags',
                'originHostPreserved': True, 'publicHttp2Claimed': False, 'syntheticBusinessPages': False},
            'checks': {key: {'status': 'NOT_EXECUTED'} for key in REQUIRED},
            'coverage': {}, 'screenshots': [], 'failures': [], 'latencySamples': [],
            'pageErrors': [], 'resourceSamples': []}

    def save(self):
        text = json.dumps(self.data, ensure_ascii=False, indent=2)
        # Exact secret matching is an additional artifact boundary; do not emit
        # raw exceptions/HTTP bodies/headers in the first place.
        for secret in self.secrets:
            if len(secret) >= 4 and secret in text:
                raise CheckError('secret_artifact_rejected')
        temporary = self.output / 'browser-evidence.json.tmp'
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(self.output / 'browser-evidence.json')

    def passed(self, name, **details):
        self.data['checks'][name] = {'status': 'PASS', **details}
        self.save()

    def failure(self, name, error):
        # Playwright errors can include password fill values, URLs and headers.
        # Store only controlled stage and exception class, never error text.
        self.data['checks'][name] = {'status': 'FAIL', **controlled_error(error)}
        self.data['failures'].append({'check': name, **controlled_error(error)})
        self.save()

    def finalize(self):
        for index in range(1, 29):
            case = f'A{index:02}'
            checks = CASE_CHECKS.get(case, ())
            if not checks:
                self.data['coverage'][case] = {'status': 'NOT_COVERED', 'limitation': LIMITS[case]}
            else:
                statuses = [self.data['checks'][key]['status'] for key in checks]
                self.data['coverage'][case] = {'status': 'BROWSER_PORTION_PASS' if all(value == 'PASS' for value in statuses) else 'FAIL', 'checks': list(checks)}
                if case in LIMITS:
                    self.data['coverage'][case]['limitation'] = LIMITS[case]
        self.data['finishedAt'] = now()
        self.data['status'] = 'PASS' if all(self.data['checks'][name]['status'] == 'PASS' for name in REQUIRED) and not self.data['failures'] else 'FAIL'
        self.data['fullA01A28AcceptanceClaimed'] = False
        self.save()


class Runner:
    def __init__(self, descriptor, accounts, output, evidence, proxy):
        self.descriptor, self.accounts, self.output = descriptor, accounts, output
        self.evidence, self.proxy = evidence, proxy
        self.base = proxy.origin
        self.browser = None
        self.contexts, self.pages, self.auth = {}, {}, {}
        self.events, self.requests, self.active_sse = [], [], {}
        self.model_requests = []
        self.save_requests = []
        self.peak_sse = 0
        self.device = None
        self.command = None
        self.last_receipt = None
        self.report = None
        self.marker = 'BRW-' + descriptor['commit'][:8] + '-' + str(int(time.time()))[-6:]

    async def screenshot(self, page, name):
        folder = self.output / 'screenshots'
        folder.mkdir(exist_ok=True)
        target = folder / (name + '.png')
        # No tracing/video/HAR/storage-state artifacts are enabled.
        private_text = re.compile('|'.join(re.escape(value) for value in self.evidence.usernames
                                          | {self.descriptor['ownership']['token']} if value))
        await page.screenshot(path=str(target), full_page=True, animations='disabled',
            mask=[page.locator('input[type="password"],input[name="username"],#organization-account-query'),
                  page.get_by_text(private_text)])
        self.evidence.data['screenshots'].append({'path': 'screenshots/' + target.name,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        self.evidence.save()

    async def attach(self, page, alias, tab):
        page.set_default_timeout(12000)
        page.set_default_navigation_timeout(30000)
        page.on('pageerror', lambda error: self.evidence.data['pageErrors'].append({'account': alias, 'tab': tab, 'messageSha256': sha(str(error))}))
        cdp = await page.context.new_cdp_session(page)
        await cdp.send('Network.enable')
        pending = set()
        models, saves = {}, {}
        def request(event):
            value = event.get('request', {})
            path = urlsplit(value.get('url', '')).path
            if path == '/agui/run' and value.get('method') == 'POST':
                require(len(self.model_requests) < 8, 'model_stream_request_budget_exceeded')
                entry = {'account': alias, 'tab': tab, 'id': event['requestId'], 'at': time.time() * 1000, 'finished': False}
                models[event['requestId']] = entry
                self.model_requests.append(entry)
            if path.startswith('/api/devices/') and value.get('method') == 'PUT':
                entry = {'account': alias, 'tab': tab, 'id': event['requestId'], 'at': time.time() * 1000, 'finished': False}
                saves[event['requestId']] = entry
                self.save_requests.append(entry)
            if path != '/api/realtime/changes': return
            headers = {key.lower(): value for key, value in value.get('headers', {}).items()}
            self.requests.append({'account': alias, 'tab': tab, 'id': event['requestId'],
                'at': time.time() * 1000, 'lastEventId': headers.get('last-event-id')})
            pending.add(event['requestId'])
        def response(event):
            for tracked in (models, saves):
                if event['requestId'] in tracked:
                    value = event['response']
                    tracked[event['requestId']].update(status=value['status'], protocol=value.get('protocol'),
                        connectionId=str(value.get('connectionId')), responseAt=time.time() * 1000)
            if event['requestId'] not in pending: return
            value = event['response']
            if value['status'] == 200:
                self.active_sse[event['requestId'] + ':' + alias + ':' + str(tab)] = (alias, tab)
                self.peak_sse = max(self.peak_sse, len(self.active_sse))
            for item in reversed(self.requests):
                if item['id'] == event['requestId'] and item['account'] == alias and item['tab'] == tab:
                    item.update(status=value['status'], protocol=value.get('protocol'), connectionId=str(value.get('connectionId')))
                    break
        def finish(event):
            for tracked in (models, saves):
                if event['requestId'] in tracked:
                    tracked[event['requestId']].update(finished=True, failed='errorText' in event, finishedAt=time.time() * 1000)
            self.active_sse.pop(event['requestId'] + ':' + alias + ':' + str(tab), None)
        def message(event):
            if event['requestId'] not in pending: return
            try:
                value = json.loads(event['data'])
            except (ValueError, TypeError):
                self.events.append({'account': alias, 'tab': tab, 'type': 'INVALID_JSON'})
                return
            allowed = {'schemaVersion', 'eventId', 'auditId', 'domain', 'resourceType', 'resourceId',
                       'resourceVersion', 'afterVersion', 'action', 'requestId', 'occurredAt', 'reason', 'accountContext'}
            entry = {key: value[key] for key in allowed - {'accountContext'} if key in value}
            entry.update(account=alias, tab=tab, type=event.get('eventName'), lastEventId=event.get('eventId'),
                         receivedAtMs=time.time() * 1000, locatorOnly=set(value) <= allowed,
                         contextKnown=alias in self.auth,
                         contextMatches=value.get('accountContext') == self.auth.get(alias, {}).get('accountContext') if alias in self.auth else None)
            self.events.append(entry)
            for item in reversed(self.requests):
                if item['id'] == event['requestId'] and item['account'] == alias and item['tab'] == tab:
                    item.setdefault('firstNamedEvent', event.get('eventName'))
                    break
        cdp.on('Network.requestWillBeSent', request)
        cdp.on('Network.responseReceived', response)
        cdp.on('Network.loadingFinished', finish)
        cdp.on('Network.loadingFailed', finish)
        cdp.on('Network.eventSourceMessageReceived', message)
        page.on('close', lambda: [self.active_sse.pop(key, None) for key, value in tuple(self.active_sse.items()) if value == (alias, tab)])

    async def new_context(self, alias, key=None):
        context = await self.browser.new_context(viewport={'width': 1440, 'height': 1000},
            reduced_motion='reduce', timezone_id='Asia/Shanghai', accept_downloads=False, service_workers='block')
        async def owned_origin_only(route):
            target = urlsplit(route.request.url)
            if target.scheme + '://' + target.netloc != self.base:
                self.evidence.data['failures'].append({'check': 'browser-network-boundary', 'errorType': 'UnexpectedOrigin'})
                await route.abort('blockedbyclient')
                return
            await route.continue_()
        await context.route('**/*', owned_origin_only)
        page = await context.new_page()
        self.contexts[key or alias] = context
        self.pages[key or alias] = [page]
        await self.attach(page, key or alias, 0)
        await self.login(page, alias, auth_key=key or alias)
        return context, page

    async def login(self, page, alias, auth_key=None, navigate=True):
        account = self.accounts[alias]
        # Initial authentication and deliberate account changes have no accepted
        # expected context until the real check response is validated below.
        self.auth.pop(auth_key or alias, None)
        if navigate:
            await page.goto(self.base + '/#/login', wait_until='domcontentloaded')
        else:
            await page.evaluate("location.hash='/login'")
        await page.get_by_placeholder('请输入用户名').fill(account['username'])
        await page.get_by_placeholder('请输入密码').fill(account['password'])
        await page.get_by_role('button', name='登录系统', exact=True).click()
        await page.wait_for_url('**/#/home')
        await page.get_by_role('heading', name='登录工作空间', exact=True).wait_for(state='hidden')
        data = await self.api(page.context, 'GET', '/api/auth/check', auth_key=None)
        require(str(data.get('userId')) == str(account['userId']) and data.get('role') == account['role'], 'actual_identity_mismatch')
        require(all(data.get('capabilities', {}).get(key) is True for key in ('sessionTracking', 'changeHistory', 'mutations', 'realtime')), 'actual_collaboration_flags_required')
        require(bool(data.get('accountContext')), 'actual_server_context_required')
        self.evidence.secrets.add(data['accountContext'])
        self.auth[auth_key or alias] = data
        actual = await page.evaluate('({secure:window.isSecureContext,locks:!!navigator.locks,broadcast:!!window.BroadcastChannel})')
        require(all(actual.values()), 'standard_loopback_coordination_required')
        return data

    async def api(self, context, method, path, body=None, auth_key=None, expected=(200,)):
        headers = {'Origin': self.base, 'X-Agent-Action': 'workbench'}
        if auth_key:
            headers['X-Account-Context'] = self.auth[auth_key]['accountContext']
        response = await context.request.fetch(self.base + path, method=method, data=body, headers=headers, timeout=30000)
        require(response.status in expected, 'actual_api_status_mismatch')
        if response.status != 200:
            return {'httpStatus': response.status}
        return unwrap(await response.json())

    async def goto(self, page, path):
        await page.goto(self.base + '/#' + path, wait_until='domcontentloaded')

    async def click_logout(self, page):
        await page.get_by_role('button', name=re.compile('^账号菜单：')).click()
        await page.get_by_role('menuitem', name='退出登录', exact=True).click()

    async def device_list(self, page):
        await self.goto(page, '/devices')
        await page.locator('#device-code-query').fill(self.device['deviceCode'])
        await page.get_by_role('button', name='查询', exact=True).click()
        row = page.locator('[aria-label="设备记录"] .el-table__body tr').filter(has_text=self.device['deviceCode'])
        await row.wait_for()
        require(await row.count() == 1, 'actual_filtered_device_row_required')
        return row

    async def edit_device(self, page, marker):
        await self.goto(page, '/devices/edit/' + str(self.device['id']))
        await page.get_by_placeholder('填写实物型号或登记型号').wait_for()
        await page.locator('.managed-form-version').wait_for()
        text = await page.locator('.managed-form-version').inner_text()
        version = re.search(r'版本\s+(\d+)', text)
        require(version is not None, 'opened_form_version_required')
        await page.get_by_placeholder('填写实物型号或登记型号').fill(marker)
        return version.group(1)

    async def save_device(self, page):
        async with page.expect_response(lambda response: response.request.method == 'PUT' and urlsplit(response.url).path == '/api/devices/' + str(self.device['id'])) as pending:
            await page.get_by_role('button', name='保存设备', exact=True).click()
        response = await pending.value
        request = response.request
        headers = await request.all_headers()
        body = request.post_data_json
        self.command = {'body': body, 'requestId': headers.get('x-request-id'),
                        'expectedVersion': headers.get('x-expected-version'),
                        'accountContext': headers.get('x-account-context')}
        require(self.command['requestId'] and self.command['accountContext'], 'ui_mutation_headers_required')
        if response.status == 200:
            returned = unwrap(await response.json())
            version = response.headers.get('x-resource-version') or returned.get('version')
            require(re.fullmatch(r'\d+', str(version)) is not None, 'actual_mutation_version_receipt_required')
            self.last_receipt = {'version': str(version), 'auditId': response.headers.get('x-audit-id'),
                                 'eventId': response.headers.get('x-change-event-id')}
        return response, time.time() * 1000

    async def four_roles(self):
        for alias in ('supervisor', 'reviewer', 'inspector', 'peer'):
            _, page = await self.new_context(alias)
            await self.goto(page, '/organization')
            await page.locator('section[aria-label="我的身份"]').wait_for()
            expected = 1 if self.accounts[alias]['role'] == 'SUPERVISOR' else 0
            require(await page.get_by_placeholder('查找登录账号').count() == expected, 'actual_role_menu_mismatch')
            await self.screenshot(page, 'identity-' + alias)
        self.evidence.passed('four-roles-real-ui', simultaneousContexts=4,
            identitiesReadFromServer=True, roleSpecificOrganizationControls=True)

    async def react(self):
        page = await self.contexts['inspector'].new_page()
        self.pages['inspector'].append(page)
        await self.attach(page, 'inspector', 1)
        async with page.expect_response(lambda response: response.request.method == 'GET'
                and re.fullmatch(r'/api/agent/conversations/[A-Za-z0-9_-]+/workbench', urlsplit(response.url).path) is not None) as read:
            await page.goto(self.base + '/agent-ui/', wait_until='domcontentloaded')
        response = await read.value
        require(response.status == 200, 'actual_react_workbench_read_must_succeed')
        value = await response.json()
        require(isinstance(value.get('items'), list) and isinstance(value.get('files'), list), 'actual_react_workbench_schema_required')
        toggle = page.get_by_role('button', name='查看助手信息', exact=True)
        if await toggle.count() and await toggle.is_visible(): await toggle.click()
        workbench = page.get_by_role('region', name='Agent 持久工作台', exact=True)
        await workbench.wait_for()
        await workbench.get_by_role('navigation', name='工作台视图').get_by_role('button', name=re.compile('文件')).click()
        await page.wait_for_function("document.querySelector('.agent-workbench input[type=file]')?.disabled===false")
        require(await workbench.locator('.wb-error').count() == 0, 'actual_react_workbench_must_be_loaded_without_error')
        require(await page.evaluate('document.compatMode') == 'CSS1Compat', 'actual_react_document_required')
        await self.screenshot(page, 'react-actual-workbench')
        self.evidence.passed('react-real-workbench', actualEntry='/agent-ui/', actualWorkbenchGetStatus=200,
            actualLoadedFileControlEnabled=True, workItems=len(value['items']), files=len(value['files']))
        await page.close()
        self.pages['inspector'] = self.pages['inspector'][:1]

    async def create_device(self):
        page = self.pages['supervisor'][0]
        if self.descriptor.get('fixtures', {}).get('deviceId'):
            self.device = await self.api(page.context, 'GET', '/api/devices/' + str(self.descriptor['fixtures']['deviceId']), auth_key='supervisor')
            # Only explicitly runtime-owned fixture resources may be edited.
            require(self.descriptor['fixtures'].get('deviceOwned') is True, 'provided_device_ownership_required')
        else:
            await self.goto(page, '/devices/add')
            await page.get_by_placeholder('填写设备登记编号').fill('BW' + sha(self.marker)[:14])
            await page.get_by_placeholder('选择设备业务类型').click()
            await page.get_by_role('option', name='图像检测设备', exact=True).click()
            await page.get_by_placeholder('填写实物型号或登记型号').fill(self.marker + '-initial')
            await page.get_by_placeholder('填写实物序列号').fill(self.marker + '-serial')
            await page.get_by_placeholder('选择业务状态').click()
            await page.get_by_role('option', name='未使用', exact=True).click()
            async with page.expect_response(lambda response: response.request.method == 'POST' and urlsplit(response.url).path == '/api/devices') as pending:
                await page.get_by_role('button', name='保存设备', exact=True).click()
            response = await pending.value
            require(response.status == 200, 'actual_device_creation_failed')
            self.device = unwrap(await response.json())
        require(self.device and str(self.device.get('id', '')).isdigit(), 'actual_device_id_required')
        await self.device_list(page)
        await self.screenshot(page, 'owned-device-created')
        self.evidence.data['ownedCreatedResources'] = [{'resourceType': 'DEVICE', 'resourceId': str(self.device['id'])}]
        self.evidence.passed('real-device-created', resourceId=str(self.device['id']), createdViaActualUi=not bool(self.descriptor.get('fixtures', {}).get('deviceId')))

    async def conflict(self):
        first, second = self.pages['supervisor'][0], self.pages['reviewer'][0]
        version1 = await self.edit_device(first, self.marker + '-winner')
        version2 = await self.edit_device(second, self.marker + '-draft')
        require(version1 == version2, 'two_actual_opened_versions_must_match')
        # Both forms capture the same version before either save. The losing
        # editor must keep its draft, even after the other real UI commits.
        responses = await asyncio.gather(self.save_device(first), self.save_device(second))
        require(sorted(response.status for response, _at in responses) == [200, 409], 'actual_concurrent_single_winner_required')
        loser = second if responses[1][0].status == 409 else first
        marker = self.marker + ('-draft' if loser == second else '-winner')
        await loser.wait_for_function("document.querySelector('button[form=\"device-maintenance-form\"]')?.disabled===true")
        require(await loser.get_by_placeholder('填写实物型号或登记型号').input_value() == marker, 'conflict_draft_must_survive')
        require(await loser.get_by_role('button', name='保存设备', exact=True).is_disabled(), 'conflict_must_require_explicit_reload')
        await self.screenshot(loser, 'actual-version-conflict-draft')
        # Real explicit reload/discard, after the losing command was rejected.
        # This new read must never replace the original conflicting submission.
        await loser.get_by_role('button', name='重新读取', exact=True).click()
        async with loser.expect_response(lambda value: value.request.method == 'GET' and urlsplit(value.url).path == '/api/devices/' + str(self.device['id'])) as fresh:
            await loser.get_by_role('button', name='放弃修改并继续', exact=True).click()
        latest = unwrap(await (await fresh.value).json())
        await loser.wait_for_function('(value)=>document.querySelector("input[placeholder=填写实物型号或登记型号]")?.value===value', arg=latest['modelName'])
        require(str(latest['version']) == str(int(version1) + 1), 'explicit_reload_must_read_single_committed_version')
        winner = first if loser == second else second
        await self.device_list(winner)
        await self.device_list(loser)
        self.evidence.passed('same-version-ui-conflict', openedVersion=version1, statuses=[response.status for response, _at in responses], draftRetained=True, originalSubmissionDisabled=True, actualConfirmedReload=True)

    async def history(self):
        page = self.pages['supervisor'][0]
        query = urlencode({'resourceType': 'DEVICE', 'resourceId': str(self.device['id'])})
        await self.goto(page, '/operations/audit?' + query)
        timeline = page.get_by_role('list', name='修改时间线', exact=True)
        await timeline.wait_for()
        await timeline.get_by_role('button', name='查看字段对比', exact=True).first.click()
        dialog = page.get_by_role('dialog', name='操作时快照与字段对比', exact=True)
        await dialog.wait_for()
        await dialog.locator('.change-diff-list').wait_for()
        require(self.marker in await dialog.inner_text(), 'actual_field_diff_values_required')
        await self.screenshot(page, 'actual-history-diff')
        await dialog.get_by_role('button', name='关闭详情', exact=True).click()
        self.evidence.passed('real-history-diff', resourceId=str(self.device['id']), actualBeforeAfterVisible=True)

    async def replay(self):
        # Capture one successful *actual form* command and replay that exact
        # command over the authenticated browser context; do not synthesize data.
        page = self.pages['supervisor'][0]
        opened = await self.edit_device(page, self.marker + '-replay')
        response, _at = await self.save_device(page)
        require(response.status == 200, 'replay_original_ui_save_required')
        command = dict(self.command)
        headers = {'Origin': self.base, 'X-Account-Context': command['accountContext'],
                   'X-Request-ID': command['requestId'], 'X-Expected-Version': command['expectedVersion'] or opened}
        original = unwrap(await response.json())
        again = await page.context.request.put(self.base + '/api/devices/' + str(self.device['id']), data=command['body'], headers=headers)
        require(again.status == 200, 'exact_ui_command_replay_must_succeed')
        repeated = unwrap(await again.json())
        require(str(repeated.get('version')) == str(original.get('version')), 'replay_must_not_advance_version')
        changed = dict(command['body'], modelName=self.marker + '-different-content')
        conflict = await page.context.request.put(self.base + '/api/devices/' + str(self.device['id']), data=changed, headers=headers)
        require(conflict.status == 409, 'same_request_different_content_must_conflict')
        current = await self.api(page.context, 'GET', '/api/devices/' + str(self.device['id']), auth_key='supervisor')
        require(current['modelName'] == original['modelName'] and str(current['version']) == str(original['version']), 'conflicting_replay_must_not_mutate')
        audits = await self.api(page.context, 'GET', '/api/operations/audit/changes?' + urlencode({'resourceType': 'DEVICE', 'resourceId': self.device['id'], 'size': 100}), auth_key='supervisor')
        require(len([item for item in audits['items'] if item.get('requestId') == command['requestId']]) == 1, 'one_actual_success_audit_required')
        self.evidence.passed('request-replay', resourceId=str(self.device['id']), requestId=command['requestId'], openedVersion=opened, committedVersion=str(current['version']), exactReplayStatus=again.status, changedPayloadStatus=conflict.status, successfulAuditCount=1)

    async def inspector_report(self):
        page = self.pages['inspector'][0]
        await self.goto(page, '/quality/reports')
        await page.get_by_role('button', name='新建报告草稿', exact=True).click()
        dialog = page.get_by_role('dialog', name='新建报告草稿', exact=True)
        await dialog.get_by_label('输入已完成检测任务编号', exact=True).fill(self.descriptor['fixtures']['reportTaskId'])
        await dialog.get_by_label('报告标题', exact=True).fill(self.marker + '-inspector-report')
        await dialog.get_by_label('记录复核说明、风险和建议，检测数量以系统依据为准', exact=True).fill('本轮隔离浏览器核对实际检测任务和操作时账号')
        async with page.expect_response(lambda response: response.request.method == 'POST' and urlsplit(response.url).path == '/api/detection/reports') as pending:
            await dialog.get_by_role('button', name='保存草稿', exact=True).click()
        response = await pending.value
        require(response.status == 200, 'actual_inspector_report_creation_required')
        self.report = unwrap(await response.json())
        require(str(self.report.get('ownerUserId')) == str(self.accounts['inspector']['userId']), 'actual_inspector_actor_required')
        report_id = str(self.report['reportId'])
        self.evidence.data['ownedCreatedResources'].append({'resourceType': 'QUALITY_REPORT', 'resourceId': report_id})
        await self.api(self.contexts['peer'], 'GET', '/api/detection/reports/' + report_id, auth_key='peer', expected=(403, 404))
        peer = self.pages['peer'][0]
        async with peer.expect_response(lambda value: value.request.method == 'GET' and urlsplit(value.url).path == '/api/detection/reports/' + report_id) as denied:
            await self.goto(peer, '/quality/reports?reportId=' + report_id)
        require((await denied.value).status in (403, 404), 'actual_peer_page_private_request_must_be_denied')
        await peer.get_by_role('dialog', name='报告详情', exact=True).wait_for()
        await peer.get_by_role('dialog', name='报告详情', exact=True).locator('.el-loading-mask').wait_for(state='hidden')
        require(await peer.get_by_text(self.marker + '-inspector-report', exact=True).count() == 0, 'private_report_must_not_render_for_peer')
        history = await self.api(page.context, 'GET', '/api/operations/audit/changes?' + urlencode({'resourceType': 'QUALITY_REPORT', 'resourceId': report_id}), auth_key='inspector')
        create = next((item for item in history['items'] if item['actor']['role'] == 'INSPECTOR' and str(item['actor']['userId']) == str(self.accounts['inspector']['userId'])), None)
        require(create is not None and create.get('occurredAt') and create.get('eventId'), 'actual_inspector_history_required')
        await self.goto(page, '/operations/audit?' + urlencode({'resourceType': 'QUALITY_REPORT', 'resourceId': report_id}))
        await page.get_by_role('list', name='修改时间线', exact=True).wait_for()
        await self.screenshot(page, 'actual-inspector-report-history')
        self.evidence.passed('inspector-report-and-scope', reportId=report_id, actorUserId=str(create['actor']['userId']), actorRole=create['actor']['role'], auditId=str(create['id']), peerHttpDenied=True, peerBusinessTextAbsent=True)

    async def wait_until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate():
            require(time.monotonic() < deadline, 'bounded_wait_expired')
            await asyncio.sleep(.1)

    async def reconnect(self):
        page = self.pages['supervisor'][0]
        await self.device_list(page)
        await self.edit_device(page, self.marker + '-before-disconnect')
        response, _at = await self.save_device(page)
        require(response.status == 200, 'pre_disconnect_actual_commit_required')
        await self.wait_until(lambda: any(item.get('type') == 'resource-changed' and item.get('resourceId') == str(self.device['id']) and item.get('lastEventId') for item in self.events))
        before = len(self.requests)
        previous = {item['lastEventId'] for item in self.events if item.get('lastEventId')}
        began = time.time() * 1000
        self.proxy.disconnect_sse()
        await self.wait_until(lambda: any(item.get('lastEventId') in previous and item['at'] >= began for item in self.requests[before:]), timeout=40)
        await self.wait_until(lambda: any(item.get('type') == 'resync-required' and item['receivedAtMs'] >= began for item in self.events), timeout=40)
        retries = [item for item in self.requests[before:] if item.get('lastEventId') in previous and item['at'] >= began]
        await self.wait_until(lambda: any(item.get('firstNamedEvent') for item in retries), timeout=15)
        require(all(item.get('firstNamedEvent') == 'resync-required' for item in retries if item.get('firstNamedEvent')), 'native_reconnect_first_event_must_resync')
        names = {item.get('type') for item in self.events}
        await self.wait_until(lambda: any(item.get('type') == 'heartbeat' for item in self.events), timeout=35)
        require(all(item.get('locatorOnly') for item in self.events), 'actual_sse_payload_must_be_locator_only')
        require({'resource-changed', 'resync-required'} <= names, 'actual_named_sse_required')
        self.evidence.passed('native-sse-reconnect', nativeLastEventIdObserved=True, firstReconnectResyncRequired=True,
            namedEvents=['resource-changed', 'resync-required', 'heartbeat'], injectedFault='close-only-owned-proxy-sse-sockets', historicalReplayClaimed=False)

    async def notification_failure(self):
        watcher = self.pages['peer'][0]
        await self.device_list(watcher)
        self.proxy.disconnect_sse(block_seconds=36)
        actor = self.pages['supervisor'][0]
        marker = self.marker + '-notifications-blocked'
        await self.edit_device(actor, marker)
        response, _at = await self.save_device(actor)
        require(response.status == 200, 'notification_failure_must_not_reject_saved_business')
        row = watcher.locator('[aria-label="设备记录"] .el-table__body tr').filter(has_text=self.device['deviceCode'])
        await row.filter(has_text=marker).wait_for(timeout=45000)
        audits = await self.api(actor.context, 'GET', '/api/operations/audit/changes?' + urlencode({'resourceType': 'DEVICE', 'resourceId': self.device['id']}), auth_key='supervisor')
        require(any(item.get('requestId') == self.command['requestId'] for item in audits['items']), 'saved_change_history_must_survive_notification_fault')
        await self.screenshot(watcher, 'notification-failure-visible-recovery')
        self.evidence.passed('notification-failure-recovery', saveStatus=response.status, historyReadBack=True,
            fault='owned SSE transport closed/rejected for 36 seconds; real HTTP unchanged', periodicOrReconnectReadConverged=True)

    async def device_logout(self):
        _context, other = await self.new_context('inspector', key='inspector-device2')
        require(self.auth['inspector-device2']['accountContext'] != self.auth['inspector']['accountContext'], 'same_account_devices_must_have_distinct_server_context')
        page = self.pages['inspector'][0]
        await self.goto(page, '/home')
        await self.click_logout(page)
        await page.wait_for_url('**/#/login')
        actual = await self.api(other.context, 'GET', '/api/auth/check')
        require(actual['accountContext'] == self.auth['inspector-device2']['accountContext'], 'other_device_must_remain_authenticated')
        await self.device_list(other)
        await self.edit_device(self.pages['supervisor'][0], self.marker + '-device2-live')
        response, _at = await self.save_device(self.pages['supervisor'][0])
        require(response.status == 200, 'other_device_notification_actual_commit_required')
        await other.locator('[aria-label="设备记录"] .el-table__body tr').filter(has_text=self.marker + '-device2-live').wait_for()
        self.evidence.passed('same-account-device-logout', distinctServerContexts=True, otherDeviceAuthAndLiveUiRetained=True)
        await other.context.close()
        del self.contexts['inspector-device2'], self.pages['inspector-device2'], self.auth['inspector-device2']
        await self.login(page, 'inspector')

    async def late_switch(self):
        # Pause the real response before ANY browser-visible headers. route.fetch
        # could apply upstream cookies to the shared jar too early for this race.
        context, old = await self.new_context('supervisor', key='late-switch')
        await self.edit_device(old, self.marker + '-old-account-draft')
        switch = await context.new_page()
        await self.attach(switch, 'late-switch', 1)
        await self.goto(switch, '/home')
        gate = self.proxy.pause_next_response('POST', '/api/auth/logout')
        click = asyncio.create_task(self.click_logout(switch))
        require(await asyncio.to_thread(gate.arrived.wait, 20) and gate.status == 200, 'actual_logout_response_must_be_held_before_headers')
        # Preserve the same Vue store and its pending logout Promise throughout
        # B's login and draft. A full navigation here would destroy the race.
        await self.login(switch, 'peer', auth_key='late-switch', navigate=False)
        await switch.evaluate("location.hash='/quality/reports'")
        await switch.get_by_role('button', name='新建报告草稿', exact=True).click()
        await switch.get_by_label('报告标题', exact=True).fill(self.marker + '-new-account-draft')
        gate.release.set()
        await click
        await asyncio.sleep(1)
        require(await switch.get_by_label('报告标题', exact=True).input_value() == self.marker + '-new-account-draft', 'late_logout_must_not_clear_new_account_draft')
        actual = await self.api(context, 'GET', '/api/auth/check')
        require(str(actual['userId']) == str(self.accounts['peer']['userId']), 'late_logout_must_not_replace_new_selected_identity')
        await old.wait_for_function('(marker)=>!document.body.innerText.includes(marker)', arg=self.marker + '-old-account-draft')
        require(await old.get_by_placeholder('填写实物型号或登记型号').count() == 0, 'old_account_editor_must_be_unmounted')
        await self.screenshot(switch, 'late-logout-preserves-new-account-draft')
        await context.close()
        self.contexts.pop('late-switch'); self.pages.pop('late-switch'); self.auth.pop('late-switch')
        # Hold an actual private inspector report GET through a different tab's
        # real B login. The old A component must not commit its late JSON.
        context, old = await self.new_context('inspector', key='late-read')
        switch = await context.new_page()
        await self.attach(switch, 'late-read', 1)
        await self.goto(switch, '/home')
        gate = self.proxy.pause_next_response('GET', '/api/detection/reports/' + str(self.report['reportId']))
        await self.goto(old, '/quality/reports?reportId=' + str(self.report['reportId']))
        require(await asyncio.to_thread(gate.arrived.wait, 20) and gate.status == 200, 'actual_private_get_must_be_held_before_headers')
        await self.login(switch, 'peer', auth_key='late-read')
        gate.release.set()
        await asyncio.sleep(1)
        require(await old.get_by_text(self.marker + '-inspector-report', exact=True).count() == 0, 'late_private_a_read_must_not_render_in_b')
        actual = await self.api(context, 'GET', '/api/auth/check')
        require(str(actual['userId']) == str(self.accounts['peer']['userId']), 'late_private_response_must_not_restore_a')
        await context.close()
        self.contexts.pop('late-read'); self.pages.pop('late-read'); self.auth.pop('late-read')
        self.evidence.passed('late-account-switch', actualDelayedLogoutResponse=True,
            oldEditorRemoved=True, newAccountDraftPreserved=True, lateIdentitySignalNonDestructive=True,
            actualDelayedPrivateGetIsolated=True, delayedUploadAguiMcpNotAsserted=True)

    async def refresh_race(self):
        context, first = await self.new_context('inspector', key='late-refresh')
        second = await context.new_page()
        await self.attach(second, 'late-refresh', 1)
        await self.goto(second, '/home')
        original = self.auth['late-refresh']['accountContext']
        refresh = '''async context => {
          const response=await fetch('/api/auth/refresh',{method:'POST',credentials:'include',
            headers:{'X-Account-Context':context}});
          return {status:response.status};
        }'''
        statuses = await asyncio.gather(first.evaluate(refresh, original), second.evaluate(refresh, original))
        require(all(value['status'] == 200 for value in statuses), 'actual_parallel_refresh_must_agree')
        check = await self.api(context, 'GET', '/api/auth/check')
        require(check['accountContext'] == original and str(check['userId']) == str(self.accounts['inspector']['userId']), 'parallel_refresh_must_preserve_selected_session')
        gate = self.proxy.pause_next_response('POST', '/api/auth/refresh')
        late = asyncio.create_task(first.evaluate(refresh, original))
        require(await asyncio.to_thread(gate.arrived.wait, 20) and gate.status == 200, 'actual_refresh_response_must_be_held_before_cookie_headers')
        await self.click_logout(second)
        await second.wait_for_url('**/#/login')
        await self.login(second, 'peer', auth_key='late-refresh', navigate=False)
        await second.evaluate("location.hash='/quality/reports'")
        await second.get_by_role('button', name='新建报告草稿', exact=True).click()
        await second.get_by_label('报告标题', exact=True).fill(self.marker + '-refresh-race-b-draft')
        gate.release.set()
        require((await late)['status'] == 200, 'delayed_refresh_must_deliver_actual_original_response')
        actual = await self.api(context, 'GET', '/api/auth/check')
        require(str(actual['userId']) == str(self.accounts['peer']['userId']) and actual['accountContext'] == self.auth['late-refresh']['accountContext'], 'late_refresh_cookie_must_not_replace_b_selector')
        require(await second.get_by_label('报告标题', exact=True).input_value() == self.marker + '-refresh-race-b-draft', 'late_refresh_must_not_clear_b_draft')
        old = await context.request.post(self.base + '/api/auth/refresh', headers={'Origin': self.base, 'X-Account-Context': original})
        require(old.status in (401, 409), 'revoked_a_context_must_not_refresh_selected_b')
        after = await self.api(context, 'GET', '/api/auth/check')
        require(after['accountContext'] == actual['accountContext'], 'rejected_old_refresh_must_not_clear_selected_b')
        await self.screenshot(second, 'late-refresh-preserves-selected-b')
        self.evidence.passed('refresh-logout-race', parallelBrowserRefreshStatuses=[value['status'] for value in statuses],
            refreshResponseHeadersActuallyDelayed=True, logoutAndBLoginBeforeDelayedHeaders=True,
            selectedBIdentityAndDraftRetained=True, oldARefreshStatus=old.status)
        await context.close()
        self.contexts.pop('late-refresh'); self.pages.pop('late-refresh'); self.auth.pop('late-refresh')

    async def arm_dom(self, page, marker):
        return await page.evaluate('''marker => {
          window.__collaborationDomEvidence?.observer?.disconnect();
          const state={marker,armedAt:Date.now(),visible:document.visibilityState,foundAt:null};
          const inspect=()=>{const rows=[...document.querySelectorAll('[aria-label="设备记录"] .el-table__body tr')];
            if(rows.some(row=>{const rect=row.getBoundingClientRect();return row.innerText.includes(marker)&&rect.width>0&&rect.height>0&&rect.top<innerHeight&&rect.bottom>0&&getComputedStyle(row).visibility==='visible'})&&!state.foundAt){state.foundAt=Date.now();state.observer.disconnect()}};
          state.observer=new MutationObserver(inspect);state.observer.observe(document.body,{subtree:true,childList:true,characterData:true});
          window.__collaborationDomEvidence=state;inspect();
          return {visibility:state.visible,scrollY:window.scrollY,focusId:document.activeElement?.id,
            filter:document.querySelector('#device-code-query')?.value,
            page:document.querySelector('.el-pager .is-active')?.innerText||'1'};
        }''', marker)

    async def collect_dom(self, page, before, marker, response_at, request_id, committed_version, alias, tab):
        await page.wait_for_function('window.__collaborationDomEvidence?.foundAt!==null', timeout=12000)
        data = await page.evaluate('''() => ({foundAt:window.__collaborationDomEvidence.foundAt,
          visibility:document.visibilityState,scrollY:window.scrollY,focusId:document.activeElement?.id,
          filter:document.querySelector('#device-code-query')?.value,
          page:document.querySelector('.el-pager .is-active')?.innerText||'1'})''')
        require(data['filter'] == before['filter'] and data['page'] == before['page']
                and abs(data['scrollY'] - before['scrollY']) <= 2 and data['focusId'] == before['focusId'], 'local_update_must_preserve_view_state')
        await self.wait_until(lambda: any(item.get('account') == alias and item.get('requestId') == request_id
            and item.get('type') == 'resource-changed' for item in self.events), timeout=12)
        event = next(item for item in self.events if item.get('account') == alias and item.get('requestId') == request_id and item.get('type') == 'resource-changed')
        require(event.get('resourceId') == str(self.device['id']) and event.get('occurredAt'), 'dom_sample_must_match_real_committed_event')
        require(str(event.get('resourceVersion', event.get('afterVersion'))) == committed_version, 'dom_sample_event_must_match_committed_version')
        occurred = datetime.fromisoformat(event['occurredAt'].replace('Z', '+00:00'))
        require(occurred.tzinfo is not None, 'server_event_clock_must_have_offset')
        elapsed = data['foundAt'] - occurred.timestamp() * 1000
        require(0 <= elapsed < 60000, 'same_ecs_clock_latency_invalid')
        sample = {'account': alias, 'tab': tab, 'requestId': request_id,
                  'resourceVersion': str(event.get('resourceVersion', event.get('afterVersion'))),
                  'eventId': str(event['eventId']), 'eventOccurredAt': event['occurredAt'],
                  'domAtEpochMs': data['foundAt'], 'eventOccurredToDomMs': round(elapsed, 3),
                  'responseToDomMs': round(data['foundAt'] - response_at, 3),
                  'visibility': before['visibility'], 'filterPageScrollFocusPreserved': True}
        self.evidence.data['latencySamples'].append(sample)

    async def load(self):
        semaphore = asyncio.Semaphore(3)
        async def prepare(alias):
            async with semaphore:
                if alias not in self.contexts: await self.new_context(alias)
                page = self.pages[alias][0]
                await self.device_list(page)
                sibling = await self.contexts[alias].new_page()
                self.pages[alias].append(sibling)
                await self.attach(sibling, alias, 1)
                await self.device_list(sibling)
                await sibling.bring_to_front()
                await sibling.locator('#device-code-query').focus()
        await asyncio.gather(*(prepare(alias) for alias in self.accounts))
        require(len(self.contexts) == 20 and sum(len(value) for value in self.pages.values()) == 40, 'twenty_accounts_forty_actual_tabs_required')
        await self.wait_until(lambda: len({item['account'] for item in self.events if item.get('type') == 'heartbeat' and item['account'] in self.accounts}) == 20, timeout=40)
        load_start = time.time() * 1000
        self.peak_sse = len(self.active_sse)
        rounds = max(2, math.ceil(self.descriptor['budgets']['minimumLatencySamples'] / 19))
        covered = set()
        for index in range(rounds):
            writer = 'supervisor' if index % 2 == 0 else 'reviewer'
            actor = self.pages[writer][0]
            await actor.bring_to_front()
            marker = self.marker + '-load-' + str(index)
            opened = await self.edit_device(actor, marker)
            watchers = []
            for alias, pages in self.pages.items():
                if alias == writer: continue
                page = pages[1]
                before = await self.arm_dom(page, marker)
                require(before['visibility'] == 'visible', 'load_watcher_must_be_actually_visible')
                watchers.append((alias, page, before))
            response, response_at = await self.save_device(actor)
            require(response.status == 200 and str(self.command['expectedVersion'] or self.command['body'].get('version')) == opened, 'load_write_must_use_opened_version')
            request_id = self.command['requestId']
            committed_version = self.last_receipt['version']
            await asyncio.gather(*(self.collect_dom(page, before, marker, response_at, request_id, committed_version, alias, 1) for alias, page, before in watchers))
            covered.update(alias for alias, _page, _before in watchers)
            # Background tabs are tested by real focus. Their focus-recovery
            # latency is separate from the visible-tab server-event P95.
            for alias in ('inspector', 'peer'):
                background = self.pages[alias][0]
                await background.bring_to_front()
                await background.locator('[aria-label="设备记录"] .el-table__body tr').filter(has_text=marker).wait_for(timeout=12000)
                await self.pages[alias][1].bring_to_front()
            await self.pages[writer][1].bring_to_front()
        require(covered == set(self.accounts), 'all_twenty_accounts_must_have_real_dom_samples')
        samples = self.evidence.data['latencySamples']
        require(len(samples) >= self.descriptor['budgets']['minimumLatencySamples'], 'latency_sample_minimum_not_met')
        values = sorted(item['eventOccurredToDomMs'] for item in samples)
        p95 = values[math.ceil(.95 * len(values)) - 1]
        self.evidence.data['latency'] = {'definition': 'actual matched server SSE occurredAt to visible DOM marker; same ECS host wall clock',
            'serverTimestampIsPreCommitAuditTime': True, 'quantile': 'nearest-rank', 'samples': len(samples),
            'accountsWithSamples': len(covered), 'p95Ms': p95, 'limitMs': self.descriptor['budgets']['p95MaxMs'],
            'clockTopology': 'browser and backend containers share ECS kernel clock; negative or absent timestamps fail',
            'backgroundTabsIncludedInP95': False, 'backgroundFocusRecoveryAsserted': True}
        self.evidence.passed('twenty-accounts-forty-tabs', accounts=20, actualTabs=40, backgroundFocusRecovery=True,
            visibleWatcherAccountsPerRound=19, actualMutationRounds=rounds, allAccountsSampled=True)
        require(p95 <= self.descriptor['budgets']['p95MaxMs'], 'actual_p95_exceeds_two_seconds')
        self.evidence.passed('latency-p95', samples=len(samples), accounts=20, p95Ms=p95, limitMs=2000)
        current = [value for value in self.active_sse.values() if value[0] in self.accounts]
        counts = {alias: sum(value[0] == alias for value in current) for alias in self.accounts}
        require(all(value == 1 for value in counts.values()) and self.peak_sse <= 20, 'one_native_sse_per_same_account_tabs_required')
        requests = [item for item in self.requests if item['at'] >= load_start and item.get('status') == 200]
        protocols = {item.get('protocol') for item in self.requests if item.get('status') == 200}
        require(protocols == {'http/1.1'} and self.proxy.snapshot()['nginxProtocols'] == ['HTTP/1.1'], 'actual_http1_protocol_evidence_required')
        self.evidence.passed('http1-shared-connections', browserProtocols=sorted(protocols), nginxProtocols=['HTTP/1.1'],
            actualSsePerAccount=counts, loadPeakSse=self.peak_sse, newConnectionsDuringMeasuredLoad=len(requests), sameAccountTabs=2,
            backgroundVisibilityNotOverridden=True, publicHttp2Claimed=False)
        await self.screenshot(self.pages['inspector'][1], 'twenty-accounts-load-real-device')

    async def model_stream_save(self):
        spec = stream_probe_spec(self.descriptor)
        alias = 'supervisor'
        page, editor = self.pages[alias]
        independent = self.pages['reviewer'][0]
        await page.bring_to_front()
        # Provision both real persistent sessions before starting either delay.
        catalog = await self.api(page.context, 'GET', '/agui/catalog', auth_key=alias)
        sessions = []
        for marker in spec['markers']:
            session = await self.api(page.context, 'POST', '/api/chat-assistant/sessions', auth_key=alias)
            session_id = session['sessionId']
            require(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', session_id), 'actual_agent_session_id_required')
            path = '/api/agent/conversations/' + session_id + '/model-selection'
            selection = await self.api(page.context, 'GET', path, auth_key=alias)
            request_id = await page.evaluate('crypto.randomUUID()')
            await self.api(page.context, 'POST', path, {'modelId': spec['modelId'],
                'revision': selection['revision'], 'requestId': request_id}, auth_key=alias)
            sessions.append({'sessionId': session_id, 'marker': marker})
            self.evidence.data['ownedCreatedResources'].append({'resourceType': 'CHAT_SESSION', 'resourceId': session_id})
        initial_version = await self.edit_device(editor, self.marker + '-stream-same-context')
        before = self.proxy.snapshot()
        started_at = time.time() * 1000
        try:
            await page.evaluate(r'''({sessions, agent, context}) => {
                if (window.__ownedA21Streams) throw new Error('probe_already_started');
                window.__ownedA21Streams = sessions.map(({sessionId,marker}) => {
                    const controller = new AbortController();
                    const state = {sessionId,marker,firstContent:false,finishedEvent:false,done:false,
                        error:false,frames:0,bytes:0,runId:null,messageId:null,controller};
                    (async () => {
                        let reader;
                        try {
                            const response = await fetch('/agui/run', {method:'POST',credentials:'include',
                                headers:{'Content-Type':'application/json','Accept':'text/event-stream',
                                    'X-Agent-Id':agent,'X-Account-Context':context}, signal:controller.signal,
                                body:JSON.stringify({threadId:sessionId,runId:crypto.randomUUID(),
                                    messages:[{id:crypto.randomUUID(),role:'user',content:'查看本轮连通状态 '+marker}]})});
                            if (response.status!==200 || !response.headers.get('content-type')?.startsWith('text/event-stream'))
                                throw new Error('actual_stream_rejected');
                            reader=response.body.getReader();
                            const decoder=new TextDecoder(); let pending='',tail='';
                            const frame = block => {
                                const data=block.split(/\r?\n/).filter(line=>line.startsWith('data:'))
                                    .map(line=>line.slice(5).trimStart()).join('\n');
                                if (!data) return;
                                if (++state.frames>4096) throw new Error('frame_budget');
                                const value=JSON.parse(data);
                                if (value.type==='RUN_ERROR') throw new Error('actual_run_error');
                                if (value.type==='TEXT_MESSAGE_CONTENT' && typeof value.delta==='string') {
                                    tail=(tail+value.delta).slice(-4096);
                                    if (tail.includes(marker) && !state.firstContent) {
                                        state.firstContent=true; state.firstContentAt=Date.now();
                                    }
                                }
                                if (value.type==='CUSTOM' && value.name==='doorhandle.execution.v1') {
                                    if (state.runId) throw new Error('ambiguous_execution');
                                    state.runId=value.value?.runId;state.messageId=value.value?.messageId;
                                }
                                if (value.type==='RUN_FINISHED') {state.finishedEvent=true;state.finishedEventAt=Date.now();}
                            };
                            while (true) {
                                const part=await reader.read();
                                if (part.done) break;
                                state.bytes+=part.value.length;
                                if (state.bytes>2097152) throw new Error('byte_budget');
                                pending+=decoder.decode(part.value,{stream:true});
                                if (pending.length>65536) throw new Error('frame_size_budget');
                                const blocks=pending.split(/\r?\n\r?\n/);pending=blocks.pop();blocks.forEach(frame);
                            }
                            pending+=decoder.decode();if (pending.trim()) frame(pending);
                            if (!state.firstContent || !state.finishedEvent || !state.runId || !state.messageId)
                                throw new Error('incomplete_actual_execution');
                        } catch (_) { state.error=true; }
                        finally { if (reader) reader.releaseLock(); state.done=true;state.endedAt=Date.now(); }
                    })();
                    return state;
                });
            }''', {'sessions': sessions, 'agent': catalog['mainAgent'], 'context': self.auth[alias]['accountContext']})

            async def state():
                return await page.evaluate('''() => window.__ownedA21Streams.map(({sessionId,marker,firstContent,
                    firstContentAt,finishedEvent,finishedEventAt,done,error,frames,bytes,runId,messageId,endedAt}) =>
                    ({sessionId,marker,firstContent,firstContentAt,finishedEvent,finishedEventAt,done,error,
                        frames,bytes,runId,messageId,endedAt}))''')

            shared_sse_connection = [None]
            async def live():
                values = await state()
                require(len(values) == 2 and all(value['firstContent'] and not value['done']
                    and not value['finishedEvent'] and not value['error'] for value in values), 'two_actual_model_streams_must_still_be_live')
                models = [value for value in self.model_requests if value['at'] >= started_at and value['account'] == alias]
                require(len(models) == 2 and all(value.get('status') == 200 and value.get('protocol') == 'http/1.1'
                    and not value['finished'] for value in models), 'actual_two_unfinished_http1_model_connections_required')
                ids = {value.get('connectionId') for value in models}
                require(len(ids) == 2 and ids.isdisjoint({None, 'None', '0'}), 'distinct_actual_model_connection_ids_required')
                require(self.proxy.snapshot()['modelActive'] == 2, 'two_actual_upstream_model_streams_required')
                current = [value for value in self.active_sse.values() if value[0] == alias]
                require(len(current) == 1, 'shared_account_sse_must_remain_live_with_models')
                sse = [value for value in self.requests if value['account'] == alias and value.get('status') == 200
                    and value['id'] + ':' + alias + ':' + str(value['tab']) in self.active_sse]
                require(len(sse) == 1 and sse[0].get('protocol') == 'http/1.1'
                    and sse[0].get('connectionId') not in ids | {None, 'None', '0'},
                    'shared_sse_needs_its_distinct_actual_http1_connection')
                shared_sse_connection[0] = sse[0]['connectionId']
                return values, models

            await page.wait_for_function('''() => window.__ownedA21Streams?.length===2 &&
                window.__ownedA21Streams.every(value=>value.firstContent || value.error || value.done)''', timeout=10000)
            _values, models = await live()
            receipts = []
            opened = initial_version
            for writer, target in ((alias, editor), ('reviewer', independent)):
                if writer != alias:
                    await target.bring_to_front()
                    opened = await self.edit_device(target, self.marker + '-stream-other-device')
                    require(opened == receipts[-1]['version'], 'second_device_must_open_current_committed_version')
                await live()
                start = time.monotonic()
                response, _at = await self.save_device(target)
                elapsed = (time.monotonic() - start) * 1000
                require(response.status == 200 and elapsed <= spec['saveMaxMillis'], 'actual_save_with_models_must_complete_within_budget')
                require(str(self.command['expectedVersion'] or self.command['body'].get('version')) == opened
                    and int(self.last_receipt['version']) == int(opened) + 1, 'actual_stream_save_cas_version_required')
                values, models = await live()
                network = [value for value in self.save_requests if value['account'] == writer
                    and value['at'] >= started_at and value.get('status') == 200]
                require(network and network[-1].get('protocol') == 'http/1.1', 'actual_save_http1_response_required')
                if writer == alias:
                    occupied = {value['connectionId'] for value in models} | {value.get('connectionId')
                        for value in self.requests if value['account'] == alias and value['id'] + ':' + alias + ':' + str(value['tab']) in self.active_sse}
                    require(network[-1].get('connectionId') not in occupied
                        and network[-1].get('connectionId') not in (None, 'None', '0'), 'ordinary_save_needs_an_available_actual_http1_connection')
                current = await self.api(target.context, 'GET', '/api/devices/' + str(self.device['id']), auth_key=writer)
                require(str(current['version']) == self.last_receipt['version']
                    and current['modelName'] == self.command['body']['modelName'], 'stream_save_must_read_back_committed_resource')
                audits = await self.api(target.context, 'GET', '/api/operations/audit/changes?' + urlencode({
                    'resourceType': 'DEVICE', 'resourceId': self.device['id'], 'size': 100}), auth_key=writer)
                matched = [item for item in audits['items'] if item.get('requestId') == self.command['requestId']]
                require(len(matched) == 1 and str(matched[0]['id']) == self.last_receipt['auditId']
                    and matched[0]['eventId'] == self.last_receipt['eventId']
                    and str(matched[0]['afterVersion']) == self.last_receipt['version'], 'stream_save_needs_one_actual_audit_receipt')
                await live()
                receipts.append({'account': writer, 'tab': 1 if writer == alias else 0, 'httpStatus': response.status,
                    'saveMs': elapsed, 'openedVersion': opened, **self.last_receipt, 'requestId': self.command['requestId'],
                    'actualConnectionId': network[-1]['connectionId'], 'modelStreamsUnfinishedAtSaveResponse': 2,
                    'saveResponseAt': _at, 'resourceReadBack': True, 'successfulAuditCount': len(matched)})
            await page.wait_for_function('() => window.__ownedA21Streams.every(value=>value.done)',
                timeout=spec['completionTimeoutMillis'])
            final = await state()
            require(all(value['firstContent'] and value['finishedEvent'] and value['done'] and not value['error']
                and re.fullmatch(r'[a-f0-9-]{36}', str(value['runId'])) and value['messageId'] for value in final),
                'both_actual_agent_streams_must_finish_successfully')
            require(all(receipt['saveResponseAt'] < value['finishedEventAt'] <= value['endedAt']
                for receipt in receipts for value in final), 'both_save_responses_must_precede_both_real_stream_finishes')
            for value in final:
                deadline = time.monotonic() + 20
                while True:
                    run = await self.api(page.context, 'GET', '/api/agent/runs/' + value['runId'], auth_key=alias)
                    board = await self.api(page.context, 'GET', '/api/agent/conversations/' + value['sessionId'] + '/workbench', auth_key=alias)
                    executions = [item for item in board['items'] if item['kind'] == 'EXECUTION'
                        and item['data'].get('runId') == value['runId'] and item['status'] == 'COMPLETED']
                    require(run['sessionId'] == value['sessionId'] and run['status'] not in ('ERROR', 'CANCELLED'),
                        'actual_agent_journal_must_belong_to_the_session')
                    if run['status'] == 'COMPLETED' and len(executions) == 1:
                        break
                    require(time.monotonic() < deadline, 'model_stream_must_have_real_persisted_completed_execution')
                    await asyncio.sleep(.1)
            await self.wait_until(lambda: self.proxy.snapshot()['modelActive'] == 0, timeout=5)
            after = self.proxy.snapshot()
            require(after['modelOpened'] - before['modelOpened'] == 2 and after['modelCompleted'] - before['modelCompleted'] == 2
                and after['modelProtocols'] == ['HTTP/1.1'] and after['connectionAdmissionRejections'] == before['connectionAdmissionRejections'],
                'actual_upstream_streams_must_finish_without_connection_budget_rejection')
            self.evidence.passed('model-stream-save-connection-budget', modelId=spec['modelId'],
                actualAgentStreams=final, actualModelConnections=[{key: value[key] for key in
                    ('account', 'tab', 'connectionId', 'protocol', 'status')} for value in models],
                nativeSharedSsePerAccount=1, actualTabsInModelContext=2, ordinarySaves=receipts,
                actualSharedSseConnectionId=shared_sse_connection[0],
                actualHttp1ModelContextConnectionsAtSave=4,
                maximumProviderDelayMillis=spec['streamDelayMillis'], saveLimitMs=spec['saveMaxMillis'],
                providerFinalStateMustBeReReadByRuntime=True, publicHttp2Claimed=False,
                responseGatesUsed=False, proxyModelPeak=after['modelPeak'], proxyConnectionsPeak=after['connectionsPeak'])
        finally:
            await page.evaluate('''() => {for (const value of window.__ownedA21Streams || [])
                if (!value.done) value.controller.abort(); delete window.__ownedA21Streams;}''')

    async def revoke(self):
        target = 'load_16'
        page = self.pages['supervisor'][0]
        await self.goto(page, '/organization')
        await page.get_by_placeholder('查找登录账号').fill(self.accounts[target]['username'])
        await page.get_by_role('button', name='查询', exact=True).click()
        row = page.locator('.el-table__body tr').filter(has_text=self.accounts[target]['username'])
        await row.get_by_role('button', name='登录权限', exact=True).click()
        dialog = page.get_by_role('dialog', name='账号登录权限', exact=True)
        await dialog.locator('.access-form').wait_for()
        await dialog.get_by_role('switch').click()
        async with page.expect_response(lambda response: response.request.method == 'POST' and '/access' in urlsplit(response.url).path) as pending:
            await dialog.get_by_role('button', name='确认保存权限', exact=True).click()
        response = await pending.value
        require(response.status == 200, 'actual_account_disable_ui_required')
        context = self.contexts[target]
        # Preserve old selected credentials in this real browser context. Check
        # before page focus can trigger a new identity check/cleanup.
        result = await context.request.get(self.base + '/api/auth/check', headers={'Origin': self.base})
        require(result.status == 401, 'disabled_existing_session_must_be_unauthorized')
        for tab in self.pages[target]:
            await tab.bring_to_front()
            await tab.get_by_role('heading', name='登录工作空间', exact=True).wait_for(timeout=35000)
            require(await tab.locator('[aria-label="设备记录"]').count() == 0, 'revoked_page_business_data_must_be_cleared')
        await self.wait_until(lambda: all(value[0] != target for value in self.active_sse.values()), timeout=40)
        await self.screenshot(self.pages[target][1], 'disabled-account-cleared')
        self.evidence.passed('account-disable-revocation', userId=str(self.accounts[target]['userId']),
            actualUiDisable=True, existingCookieHttpStatus=401, bothTabsBusinessDataCleared=True, nativeSseClosed=True)

    async def run_check(self, name, callback):
        try:
            await callback()
            return True
        except Exception as error:
            self.evidence.failure(name, error)
            return False

    async def run(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            # No --ignore-certificate-errors, --unsafely-treat-insecure-origin-*
            # or visibility overrides. Owned UI only; container isolation is the
            # sandbox boundary, recorded explicitly instead of claiming otherwise.
            self.browser = await playwright.chromium.launch(headless=True, chromium_sandbox=False)
            self.evidence.data['tool']['actualChromium'] = self.browser.version
            self.evidence.data['tool']['chromiumSandbox'] = False
            require(self.browser.version == CHROMIUM_VERSION, 'pinned_chromium_required')
            stages = [('four-roles-real-ui', self.four_roles), ('react-real-workbench', self.react),
                ('real-device-created', self.create_device), ('same-version-ui-conflict', self.conflict),
                ('real-history-diff', self.history), ('request-replay', self.replay),
                ('inspector-report-and-scope', self.inspector_report), ('native-sse-reconnect', self.reconnect),
                ('notification-failure-recovery', self.notification_failure), ('same-account-device-logout', self.device_logout),
                ('late-account-switch', self.late_switch), ('refresh-logout-race', self.refresh_race), ('twenty-accounts-forty-tabs', self.load),
                ('model-stream-save-connection-budget', self.model_stream_save),
                ('account-disable-revocation', self.revoke)]
            try:
                for name, callback in stages:
                    if not await self.run_check(name, callback): break
            finally:
                await self.browser.close()
                self.evidence.data['sse'] = {'requests': [{key: value for key, value in item.items() if key != 'id'} for item in self.requests],
                    'namedEventCounts': {name: sum(item.get('type') == name for item in self.events) for name in ('heartbeat', 'resource-changed', 'resync-required')},
                    'allFramesLocatorOnly': bool(self.events) and all(item.get('locatorOnly') for item in self.events),
                    'initialAuthenticationFramesWithoutAcceptedContext': sum(not item.get('contextKnown') for item in self.events),
                    'stableAccountContextMismatchFrames': sum(item.get('contextKnown') and item.get('contextMatches') is False and not item.get('account', '').startswith('late-') for item in self.events),
                    'intentionalSwitchFramesAreCheckedByUiIsolation': True,
                    'proxy': self.proxy.snapshot()}
                if self.evidence.data['sse']['stableAccountContextMismatchFrames']:
                    self.evidence.failure('native-sse-reconnect', CheckError('stable_account_received_wrong_context_frame'))
                if self.evidence.data['pageErrors']:
                    self.evidence.data['failures'].append({'check': 'javascript-errors', 'count': len(self.evidence.data['pageErrors'])})
                    self.evidence.failure('four-roles-real-ui', CheckError('actual_javascript_errors'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', required=True)
    parser.add_argument('--accounts', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    evidence, proxy, sampler = None, None, None
    try:
        descriptor = json.loads(Path(args.descriptor).read_text(encoding='utf-8-sig'))
        accounts = json.loads(Path(args.accounts).read_text(encoding='utf-8-sig'))['accounts']
        limits = validate(descriptor, accounts, output)
        evidence = Evidence(descriptor, accounts, output)
        evidence.data['cgroupAdmission'] = limits
        evidence.data['cgroupNamespaceSha256'] = sha(Path('/proc/self/cgroup').read_text().strip())
        evidence.data['runnerSourceSha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), Path(__file__).with_name('collaboration-browser-proxy.py'),
                         Path(__file__).with_name('collaboration-browser-sources.json'))}
        evidence.data['runtimeIdentityVerification'] = 'External runtime must inspect ownership labels, image/container IDs, network, cgroup and mounts; finite limits verified inside.'
        evidence.save()
        proxy = load_module(Path(__file__).with_name('collaboration-browser-proxy.py')).LoopbackProxy()
        proxy.start()
        sampler = ResourceSampler(); sampler.start()
        runner = Runner(descriptor, accounts, output, evidence, proxy)
        asyncio.run(asyncio.wait_for(runner.run(), timeout=descriptor['budgets']['timeoutSeconds']))
        sampler.close()
        evidence.data['resourceSamples'] = sampler.samples
        require(len(sampler.samples) >= 20, 'actual_resource_sampling_insufficient')
        final = read_cgroup()
        events = dict(line.split() for line in (final.get('memory.events') or '').splitlines())
        initial = dict(line.split() for line in (limits.get('memory.events') or '').splitlines())
        require(all(int(events.get(key, 0)) == int(initial.get(key, 0)) for key in ('oom', 'oom_kill')), 'browser_cgroup_oom_observed')
        pid_events = dict(line.split() for line in (final.get('pids.events') or '').splitlines())
        initial_pid_events = dict(line.split() for line in (limits.get('pids.events') or '').splitlines())
        require(int(pid_events.get('max', 0)) == int(initial_pid_events.get('max', 0)), 'browser_cgroup_pids_budget_exhausted')
        require(proxy.snapshot()['connectionAdmissionRejections'] == 0 and proxy.snapshot()['transportErrors'] == 0,
                'owned_proxy_transport_budget_or_handler_failed')
        evidence.passed('resource-samples', samples=len(sampler.samples), intervalSeconds=1, cgroupV2=True,
            memoryOomDelta=0, pidsMaxEventsDelta=0, cpuAndPidsSamples=True, backendResourcesRequireExternalRuntimeEvidence=True)
        # Screenshot pixels never contain password field text (masked). Raw
        # login/cookie/token/HAR sources are never created or archived.
        require(not any(path.suffix.lower() in ('.har', '.zip', '.webm') for path in output.rglob('*')), 'sensitive_raw_artifacts_forbidden')
        evidence.passed('artifact-secret-boundary', passwordFieldsMasked=True, exactSecretScan=True,
            cookiesTokensStorageStateHarTraceVideoWritten=False, actualSseLocatorsOnly=bool(runner.events) and all(item.get('locatorOnly') for item in runner.events))
        evidence.finalize()
        print(json.dumps({'status': evidence.data['status'], 'artifact': 'browser-evidence.json', 'requiredChecks': len(REQUIRED)}, separators=(',', ':')))
        return 0 if evidence.data['status'] == 'PASS' else 1
    except Exception as error:
        if evidence:
            evidence.data['failures'].append({'check': 'runner', **controlled_error(error)})
            if sampler:
                sampler.close(); evidence.data['resourceSamples'] = sampler.samples
            evidence.finalize()
        elif output.resolve() == Path('/evidence') and output.is_dir() and not output.is_symlink() and not any(output.iterdir()):
            (output / 'browser-evidence.json').write_text(json.dumps({'schemaVersion': 1, 'status': 'FAIL',
                'admission': 'FAIL', **controlled_error(error), 'fullA01A28AcceptanceClaimed': False,
                'checks': {key: {'status': 'NOT_EXECUTED'} for key in REQUIRED}}), encoding='utf-8')
        # No exception detail is printed: network/library diagnostics may carry
        # credentials or full signed URLs. Inspect controlled evidence instead.
        print(json.dumps({'status': 'FAIL', **controlled_error(error), 'admission': isinstance(error, (AdmissionError, importlib.metadata.PackageNotFoundError))}, separators=(',', ':')))
        return 2 if isinstance(error, (AdmissionError, importlib.metadata.PackageNotFoundError)) else 1
    finally:
        if sampler: sampler.close()
        if proxy: proxy.close()


if __name__ == '__main__':
    raise SystemExit(main())
