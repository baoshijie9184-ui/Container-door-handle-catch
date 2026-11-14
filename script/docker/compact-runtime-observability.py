"""Prometheus/Alertmanager inside the existing owned candidate runtime.

No host ports, provider credentials, collector or Langfuse stack. Monitoring
volumes remain live across business-data recovery; they are not business clones.
"""
import json
from datetime import datetime
import math
from pathlib import Path
import re
import secrets
import time
import urllib.parse

COMPONENTS = ('prometheus', 'alertmanager')
APPLICATIONS = ('backend', 'detection-worker', 'mem0')
JOBS = {'monolith': ('backend:8080', '/actuator/prometheus'),
        'detection-worker': ('detection-worker:9464', '/metrics'), 'mem0': ('mem0:9465', '/metrics')}
PHASES = ('after-start', 'after-restart', 'after-volume-restore', 'after-business')
TOKEN_FILE = '/run/observability-secrets/metrics-token'
CONFIG_VOLUME = 'runtime-observability-config'
SECRET_VOLUME = 'runtime-observability-private'
FILES = {'prometheus.yml': 'prometheus.yml', 'alerts.yml': 'alerts.yml', 'alertmanager.yml': 'alertmanager.yml'}
RULES = {'DoorhandleMonolithUnavailable', 'DoorhandleTelemetryDropped', 'DoorhandleTelemetryExportFailed',
         'DoorhandleWorkerNotReady', 'DoorhandleJvmMemoryPressure', 'DoorhandleFilesystemLow'}


def require(value, message):
    if not value:
        raise ValueError(message)


def prepare_images(ctx):
    context = {key: value for key, value in ctx.context().items()
               if key in ('release', 'commit', 'sourceSha256', 'identity')}
    images, references = {}, {}
    for name in COMPONENTS:
        # The same-build source acceptance already prepared these pinned images.
        # Re-admit its original proof, as for Qdrant; do not import/pull again.
        directory = ctx.checkout / 'work/observability-fixture' / (name + '-image')
        proof, image_sha = ctx.guard.read_private(directory / 'image.json')
        pin = ctx.build_resources.component_pin(name)
        summary, summary_sha = ctx.guard.read_private(directory / 'resource-summary.json')
        require(all(proof.get(key) == value == summary.get(key) for key, value in context.items())
                and proof.get('status') == 'PREPARED' and proof.get('kind') == 'doorhandle-' + name + '-image'
                and proof.get('reference') == pin['reference'] and proof.get('engineIdentity', {}).get('configDigest') == pin['config']
                and proof.get('resourceEvidence') == {'file': str(directory / 'resource-summary.json'), 'sha256': summary_sha}
                and summary.get('status') == 'PASS'
                and all(summary.get('cleanup', {}).get(key) is True for key in
                    ('creatorStopped', 'builderStopped', 'daemonImportTerminated')),
                'Monitoring image lacks the same-build completed pinned preparation')
        images[name] = proof['engineIdentity']['engineImageId']
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', images[name]), 'Unbound monitoring image')
        row = json.loads(ctx.ops.docker('image', 'inspect', images[name]))[0]
        ctx.build_resources.validate_engine_identity(row, proof['engineIdentity'])
        retained = ctx.directory / (name + '-image'); retained.mkdir(mode=0o700)
        for filename in ('image.json', 'resource-summary.json'):
            with (retained / filename).open('xb') as stream:
                (retained / filename).chmod(0o600); stream.write((directory / filename).read_bytes())
        references[name] = {'file': (directory / 'image.json').relative_to(ctx.attempt).as_posix(),
                            'sha256': image_sha, 'image': images[name], 'resourceSummarySha256': summary_sha}
    ctx.owner['observabilityImages'] = references
    ctx.save()
    return images


def select_overlay(config, images):
    """Normalize only our optional overlay before the existing isolation gate."""
    require(set(images) == set(COMPONENTS), 'Both pinned monitoring images are required')
    for name in list(config['services']):
        if name.startswith('langfuse-') or name == 'langfuse':
            del config['services'][name]
    for name in list(config.get('volumes', {})):
        if 'langfuse' in name:
            del config['volumes'][name]
    config['volumes'][CONFIG_VOLUME] = {}
    config['volumes'][SECRET_VOLUME] = {}
    for name in COMPONENTS:
        service = config['services'][name]
        service.pop('profiles', None)
        service['image'] = images[name]
        service['user'] = '10001:10001'
        service['volumes'] = [mount for mount in service['volumes'] if mount['type'] == 'volume']
        service['volumes'].append({'type': 'volume', 'source': CONFIG_VOLUME,
            'target': '/etc/' + name, 'read_only': True})
        if name == 'prometheus':
            # Retention is not a physical peak estimate; all runtime phases
            # separately reserve writable growth for head/WAL/compaction too.
            service['command'] = [arg.replace('retention.time=7d', 'retention.time=2h')
                .replace('retention.size=512MB', 'retention.size=64MB') for arg in service['command']]
            service['volumes'].append({'type': 'volume', 'source': SECRET_VOLUME,
                'target': '/run/observability-secrets', 'read_only': True})
    return config


def enable(config):
    for name, service in config['services'].items():
        env = service.setdefault('environment', {})
        for key in list(env):
            if key.startswith(('LANGFUSE_', 'LF_', 'OTEL_EXPORTER_')):
                env.pop(key)
        env.update(OTEL_ENABLED='false', DOORHANDLE_OBSERVABILITY_TRACING_ENABLED='false')
        env['TELEMETRY_METRICS_ENABLED'] = 'true' if name in APPLICATIONS else 'false'
        if name not in APPLICATIONS:
            continue
        env['DOORHANDLE_OBSERVABILITY_METRICS_TOKEN_FILE' if name == 'backend'
            else 'TELEMETRY_METRICS_TOKEN_FILE'] = TOKEN_FILE
        if name != 'backend':
            env.update(TELEMETRY_METRICS_HOST='0.0.0.0',
                TELEMETRY_METRICS_PORT='9464' if name == 'detection-worker' else '9465')
        service.setdefault('volumes', []).append({'type': 'volume', 'source': SECRET_VOLUME,
            'target': '/run/observability-secrets', 'read_only': True})
    validate(config)


def validate(config):
    require(all(name in config['services'] for name in (*COMPONENTS, *APPLICATIONS))
            and not any('langfuse' in name for name in config['services']), 'Runtime monitoring services differ')
    for name in (*COMPONENTS, *APPLICATIONS):
        service = config['services'][name]
        if name in COMPONENTS:
            require(not service.get('ports') and service.get('user') == '10001:10001'
                    and re.fullmatch(r'sha256:[a-f0-9]{64}', service['image']),
                    'Monitoring may not expose host ports or use a mutable image')
        if name in (*APPLICATIONS, 'prometheus'):
            mounts = [mount for mount in service.get('volumes', []) if mount['target'] == '/run/observability-secrets']
            require(len(mounts) == 1 and mounts[0]['type'] == 'volume'
                    and mounts[0]['source'] == SECRET_VOLUME and mounts[0].get('read_only') is True,
                    'Metrics token must use the owned read-only volume')
        if name in APPLICATIONS:
            env = service['environment']
            key = 'DOORHANDLE_OBSERVABILITY_METRICS_TOKEN_FILE' if name == 'backend' else 'TELEMETRY_METRICS_TOKEN_FILE'
            require(env.get(key) == TOKEN_FILE and env.get('TELEMETRY_METRICS_ENABLED') == 'true'
                    and env.get('OTEL_ENABLED') == env.get('DOORHANDLE_OBSERVABILITY_TRACING_ENABLED') == 'false'
                    and not any(key.startswith(('LANGFUSE_', 'LF_', 'OTEL_EXPORTER_')) for key in env),
                    'Candidate metrics must be enabled without trace-export credentials')


def install(ctx):
    """Seed owned volumes through stdin; never copy a production secret or bind."""
    files = {name: (ctx.source / 'deploy/observability' / source).read_text(encoding='utf8')
             for name, source in FILES.items()}
    volumes = {name: ctx.config['volumes'][name]['name'] for name in
               (CONFIG_VOLUME, SECRET_VOLUME, 'doorhandle-prometheus', 'doorhandle-alertmanager')}
    for name in volumes.values():
        ctx.ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal=' + ctx.project, name)
        row = json.loads(ctx.ops.docker('volume', 'inspect', name))[0]
        require(row.get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project, 'Monitoring volume ownership changed')
    command = ['run', '--rm', '-i', '--pull', 'never', '--network', 'none', '--read-only', '--user', '0:0',
        '--memory', '128m', '--memory-swap', '128m', '--label', 'io.doorhandle.rehearsal=' + ctx.project]
    for index, name in enumerate(volumes.values()):
        command += ['--mount', 'type=volume,src=' + name + ',dst=/v' + str(index)]
    code = """import json,os,sys
data=json.load(sys.stdin)
for index in range(4):
 p='/v'+str(index);os.chown(p,10001,10001);os.chmod(p,0o750 if index>1 else 0o550)
for name,body in data['files'].items():
 p='/v0/'+name;f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o440);os.write(f,body.encode());os.close(f);os.chown(p,10001,10001)
p='/v1/metrics-token';f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o440);os.write(f,data['token'].encode());os.close(f);os.chown(p,10001,10001)
"""
    ctx.ops.docker(*command, '--entrypoint', 'python', ctx.images['mem0'], '-B', '-c', code,
        data=json.dumps({'files': files, 'token': secrets.token_hex(32)}).encode(), timeout=30)
    ctx.owner['observabilityVolumes'] = volumes
    ctx.save()


def request(ctx, service, path):
    require(service in COMPONENTS and path.startswith('/') and '\n' not in path, 'Invalid monitoring readback')
    url = 'http://' + service + (':9090' if service == 'prometheus' else ':9093') + path
    code = """import sys,urllib.request
with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(sys.argv[1],timeout=5) as response:
 raw=response.read(2097153)
 if response.status!=200 or len(raw)>2097152:raise ValueError('Invalid bounded monitoring response')
 sys.stdout.buffer.write(raw)
"""
    raw = ctx.ops.docker('exec', ctx.row('mem0')['Id'], 'python', '-B', '-c', code, url, timeout=10)
    require(len(raw) <= 2 * 1024 * 1024, 'Oversized monitoring evidence')
    return json.loads(raw)


def require_targets(value, since=0):
    require(value.get('status') == 'success', 'Prometheus target API failed')
    targets = value.get('data', {}).get('activeTargets', [])
    require(len(targets) == len(JOBS), 'Candidate scrape target count differs')
    for job, (address, path) in JOBS.items():
        rows = [row for row in targets if row.get('labels', {}).get('job') == job]
        require(len(rows) == 1 and rows[0].get('health') == 'up' and not rows[0].get('lastError')
                and rows[0].get('scrapeUrl') == 'http://' + address + path,
                'A real candidate metrics endpoint is not being scraped')
        stamp = datetime.fromisoformat(rows[0]['lastScrape'].replace('Z', '+00:00')).timestamp()
        require(stamp >= since, 'Candidate scrape evidence predates this recovery/start phase')


def require_sample(value, *, positive=False, exact=None):
    rows = value.get('data', {}).get('result', [])
    require(value.get('status') == 'success' and value.get('data', {}).get('resultType') == 'vector'
            and rows, 'A required application metric has no actual samples')
    numbers = [float(row['value'][1]) for row in rows]
    require(all(math.isfinite(number) and number >= 0 and (not positive or number > 0) and (exact is None or number == exact)
                for number in numbers), 'An actual application metric does not meet its readiness contract')


def verify(ctx, phase):
    require(phase in PHASES and phase not in ctx.owner.get('observabilityReadbacks', {}), 'Repeated monitoring phase')
    validate(ctx.config)
    containers = {}
    for name in (*COMPONENTS, *APPLICATIONS):
        row = ctx.row(name)
        require(row['State']['Running'] and not row['State'].get('OOMKilled'), 'Actual monitored service is not running')
        if name in COMPONENTS:
            require(row['Image'] == ctx.owner['observabilityImages'][name]['image']
                    and not row['HostConfig'].get('PortBindings'), 'Actual monitoring image or host exposure changed')
        containers[name] = {'containerId': row['Id'], 'image': row['Image']}
        for spec in ctx.config['services'][name].get('volumes', []):
            if spec.get('source') not in ctx.owner['observabilityVolumes']:
                continue
            mounts = [mount for mount in row.get('Mounts', []) if mount.get('Destination') == spec['target']]
            require(len(mounts) == 1 and mounts[0].get('Type') == 'volume'
                    and mounts[0].get('Name') == ctx.owner['observabilityVolumes'][spec['source']]
                    and mounts[0].get('RW') is (not spec.get('read_only', False)),
                    'Actual monitoring configuration, secret or data mount changed')
    evidence = {}
    queries = ['up{job="' + job + '"}' for job in JOBS]
    queries += ['sum(jvm_memory_used_bytes{job="monolith",area="heap"})',
                'doorhandle_runtime_ready{job="detection-worker"}', 'doorhandle_runtime_ready{job="mem0"}']
    since, deadline = time.time(), time.monotonic() + 90
    while True:
        try:
            evidence['targets'] = request(ctx, 'prometheus', '/api/v1/targets')
            require_targets(evidence['targets'], since)
            evidence['queries'] = {}
            for query in queries:
                value = request(ctx, 'prometheus', '/api/v1/query?' + urllib.parse.urlencode({'query': query}))
                require_sample(value, positive=query.startswith('sum(jvm_'), exact=None if query.startswith('sum(jvm_') else 1)
                evidence['queries'][query] = value
            break
        except (ValueError, RuntimeError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
    evidence['rules'] = request(ctx, 'prometheus', '/api/v1/rules')
    groups = evidence['rules'].get('data', {}).get('groups', [])
    rules = [rule for group in groups for rule in group.get('rules', [])]
    require(evidence['rules'].get('status') == 'success' and {rule.get('name') for rule in rules} == RULES
            and all(rule.get('health') == 'ok' and not rule.get('lastError') for rule in rules),
            'The existing production alert rules did not load and evaluate')
    evidence['alertmanagers'] = request(ctx, 'prometheus', '/api/v1/alertmanagers')
    require(evidence['alertmanagers'].get('status') == 'success'
            and evidence['alertmanagers'].get('data', {}).get('activeAlertmanagers') == [{'url': 'http://alertmanager:9093/api/v2/alerts'}],
            'The actual rule engine has no candidate Alertmanager destination')
    evidence['alertmanagerStatus'] = request(ctx, 'alertmanager', '/api/v2/status')
    actual = evidence['alertmanagerStatus'].get('config', {}).get('original', '')
    # AM returns normalized YAML; inspect its reviewed route values, not byte formatting.
    require('receiver: local-console' in actual and 'alertname' in actual and 'job' in actual
            and 'group_wait: 30s' in actual and 'group_interval: 5m' in actual
            and 'repeat_interval: 4h' in actual,
            'Actual Alertmanager grouping/receiver configuration differs')
    evidence['alertmanagerGroups'] = request(ctx, 'alertmanager', '/api/v2/alerts/groups')
    require(isinstance(evidence['alertmanagerGroups'], list), 'Alertmanager groups endpoint failed')
    value = {**ctx.context(), 'kind': 'doorhandle-runtime-observability', 'project': ctx.project,
        'phase': phase, 'status': 'PASS', 'containers': containers, 'volumes': ctx.owner['observabilityVolumes'],
        'scrapedAfterUnix': since,
        'storageRecovery': 'RETAINED_MONITORING_VOLUMES_ACROSS_BUSINESS_RESTORE',
        'tracingEnabled': False, 'langfuseEnabled': False, 'externalNotificationVerified': False, 'evidence': evidence}
    file = ctx.directory / ('observability-' + phase + '.json')
    ctx.common.write_json(file, value)
    reference = {'file': file.relative_to(ctx.attempt).as_posix(), 'sha256': ctx.cutover.sha_file(file)}
    ctx.owner.setdefault('observabilityReadbacks', {})[phase] = reference
    ctx.save()
    return reference


def finish(ctx):
    require(set(ctx.owner.get('observabilityReadbacks', {})) == set(PHASES), 'Missing actual runtime monitoring phases')
    return {'status': 'PASS', 'readbacks': ctx.owner['observabilityReadbacks'],
        'images': ctx.owner['observabilityImages'], 'tracingEnabled': False, 'langfuseEnabled': False,
        'externalNotificationVerified': False, 'storageRecovery': 'RETAINED_MONITORING_VOLUMES_ACROSS_BUSINESS_RESTORE'}


def validate_files(proof, directory, read_json):
    """Recheck original collected observations; no subprocesses or network calls."""
    monitoring = proof.get('observability', {})
    require(monitoring.get('status') == 'PASS' and monitoring.get('tracingEnabled') is False
            and monitoring.get('langfuseEnabled') is False and monitoring.get('externalNotificationVerified') is False
            and set(monitoring.get('readbacks', {})) == set(PHASES)
            and set(monitoring.get('images', {})) == set(COMPONENTS), 'Complete actual monitoring evidence is required')
    volumes = None
    for phase, reference in monitoring['readbacks'].items():
        name = 'observability-' + phase + '.json'
        require(reference.get('file') == 'checkout/work/runtime-acceptance/' + name,
                'Monitoring readback escaped its owned directory')
        value, checksum = read_json(Path(directory) / name)
        require(checksum == reference.get('sha256') and value.get('status') == 'PASS'
                and value.get('phase') == phase and value.get('kind') == 'doorhandle-runtime-observability'
                and all(value.get(key) == proof.get(key) for key in ('release', 'commit', 'sourceSha256', 'identity',
                    'project', 'acceptanceProfileSha256', 'candidateBuildSha256'))
                and value.get('tracingEnabled') is False and value.get('langfuseEnabled') is False
                and value.get('storageRecovery') == monitoring.get('storageRecovery'),
                'Actual monitoring readback identity or bytes changed')
        current = value.get('volumes', {})
        require(set(current) == {CONFIG_VOLUME, SECRET_VOLUME, 'doorhandle-prometheus', 'doorhandle-alertmanager'}
                and all(name == proof['project'] + '_' + key for key, name in current.items())
                and (volumes is None or current == volumes), 'Monitoring volumes changed across business recovery')
        volumes = current
        rows = value.get('containers', {})
        require(set(rows) == set((*COMPONENTS, *APPLICATIONS)), 'Missing actual monitoring/application containers')
        for name, row in rows.items():
            expected = monitoring['images'][name]['image'] if name in COMPONENTS else proof['images'][name]
            require(row.get('image') == expected and re.fullmatch(r'[a-f0-9]{64}', row.get('containerId', '')),
                    'Monitoring readback used a different candidate process')
        evidence = value['evidence']
        require_targets(evidence['targets'], value['scrapedAfterUnix'])
        queries = {'up{job="' + job + '"}' for job in JOBS} | {
            'sum(jvm_memory_used_bytes{job="monolith",area="heap"})',
            'doorhandle_runtime_ready{job="detection-worker"}', 'doorhandle_runtime_ready{job="mem0"}'}
        require(set(evidence.get('queries', {})) == queries, 'Missing actual candidate metric queries')
        for query, sample in evidence['queries'].items():
            require_sample(sample, positive=query.startswith('sum(jvm_'), exact=None if query.startswith('sum(jvm_') else 1)
        rules = [rule for group in evidence['rules'].get('data', {}).get('groups', []) for rule in group.get('rules', [])]
        require(evidence['rules'].get('status') == 'success' and {rule.get('name') for rule in rules} == RULES
                and all(rule.get('health') == 'ok' and not rule.get('lastError') for rule in rules),
                'Archived runtime rule evaluation is incomplete')
        require(evidence['alertmanagers'].get('status') == 'success'
                and evidence['alertmanagers'].get('data', {}).get('activeAlertmanagers') == [{'url': 'http://alertmanager:9093/api/v2/alerts'}],
                'Archived actual Alertmanager destination is missing')
        actual = evidence['alertmanagerStatus'].get('config', {}).get('original', '')
        require(all(text in actual for text in ('receiver: local-console', 'alertname', 'job', 'group_wait: 30s',
                    'group_interval: 5m', 'repeat_interval: 4h')) and isinstance(evidence['alertmanagerGroups'], list),
                'Archived actual Alertmanager route/grouping is missing')
    for component, reference in monitoring['images'].items():
        require(reference.get('file') == 'checkout/work/observability-fixture/' + component + '-image/image.json',
                'Monitoring image proof escaped the same-build fixture')
        image, checksum = read_json(Path(directory) / (component + '-image') / 'image.json')
        summary, summary_sha = read_json(Path(directory) / (component + '-image') / 'resource-summary.json')
        require(checksum == reference.get('sha256') and summary_sha == reference.get('resourceSummarySha256')
                and image.get('kind') == 'doorhandle-' + component + '-image' and image.get('status') == 'PREPARED'
                and image.get('engineIdentity', {}).get('engineImageId') == reference['image']
                and image.get('resourceEvidence', {}).get('sha256') == summary_sha
                and all(image.get(key) == proof.get(key) == summary.get(key) for key in
                    ('release', 'commit', 'sourceSha256', 'identity'))
                and summary.get('status') == 'PASS'
                and all(summary.get('cleanup', {}).get(key) is True for key in
                    ('creatorStopped', 'builderStopped', 'daemonImportTerminated')),
                'Archived monitoring image/preparation proof changed')
    return {'status': 'VERIFIED', 'phases': list(PHASES), 'applicationJobs': sorted(JOBS),
            'tracingEnabled': False, 'langfuseEnabled': False}
