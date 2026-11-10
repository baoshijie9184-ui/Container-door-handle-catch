"""Actual PTH completion followed by an uncertain receipt and Kafka replay.

Only this runtime's disposable MySQL, worker, Kafka and proven-empty OSS prefix
are used. A temporary trigger rejects a real successful result; no successful
receipt, model result or finished Kafka event is manufactured by this harness.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private(ctx, path, value):
    ctx.migration.write_json(path, value)
    return sha(path.read_bytes())


def worker(ctx):
    row = ctx.row('detection-worker')
    environment = ctx.common.environment(row)
    require(row['Id'] not in (ctx.owner['mysqlContainerId'], ctx.settings['sourceMysqlContainerId'])
            and row['Image'] == ctx.images['detection-worker']
            and row['HostConfig']['RestartPolicy']['Name'] == 'no'
            and environment.get('DETECTION_ENGINE') == 'pth'
            and environment.get('DETECTION_WORKER_RECEIPTS_ENABLED') == 'true'
            and environment.get('DETECTION_RECEIPT_DB_DATABASE') == ctx.db.schema
            and environment.get('KAFKA_CONSUMER_GROUP') == 'runtime-' + ctx.token,
            'Fault injection requires this owned immutable worker with restart disabled')
    return row


def oneoff(ctx, code, value, *, network, environment, suffix, timeout=90):
    """Observe real Kafka/OSS even while the actual processing worker is stopped."""
    require(network in {'doorhandle-network', 'worker-egress'}, 'Unowned observer network')
    command = ['run', '--rm', '-i', '--name', ctx.project + '-fence-' + suffix, '--pull', 'never',
        '--read-only', '--label', 'io.doorhandle.rehearsal=' + ctx.project,
        '--network', ctx.config['networks'][network]['name'], '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--memory', '160m']
    for name in sorted(environment):
        command += ['--env', name]
    raw = ctx.ops.docker(*(command + ['--entrypoint', 'python', ctx.images['detection-worker'], '-B', '-c', code]),
        env=dict(os.environ, **environment), data=json.dumps(value).encode(), timeout=timeout)
    require(len(raw) <= 2 * 1024 * 1024, 'An actual worker observer exceeded its private bound')
    return json.loads(raw)


def kafka_observe(ctx, task, *, finished=False):
    code = """import os,sys,json,time,hashlib,secrets
from confluent_kafka import Consumer,TopicPartition,KafkaError
from kafka_event_models import DetectionTaskCreatedEvent
from detection_worker_receipts import task_digest,MysqlDetectionReceipts
v=json.load(sys.stdin); topic='detection.task.finished' if v['finished'] else 'detection.task.created'
c=Consumer({'bootstrap.servers':os.environ['KAFKA_BOOTSTRAP_SERVERS'],'group.id':'runtime-fence-'+secrets.token_hex(8),'enable.auto.commit':False,'enable.partition.eof':True})
try:
 info=c.list_topics(topic,timeout=10).topics[topic]; assert info.error is None
 ends={p:c.get_watermark_offsets(TopicPartition(topic,p),timeout=10)[1] for p in info.partitions}
 assert ends and sum(ends.values())<=4096
 c.assign([TopicPartition(topic,p,0) for p in ends]); done={p for p in ends if ends[p]==0}; rows=[]; deadline=time.monotonic()+25
 while len(done)<len(ends):
  assert time.monotonic()<deadline
  m=c.poll(1)
  if m is None: continue
  if m.error():
   assert m.error().code()==KafkaError._PARTITION_EOF
   if m.offset()>=ends[m.partition()]: done.add(m.partition())
   continue
  if m.offset()>=ends[m.partition()]: done.add(m.partition()); continue
  body=json.loads(m.value())
  if body.get('taskId')==v['task']:
   entry={'topic':topic,'partition':m.partition(),'offset':m.offset(),'keySha256':hashlib.sha256(m.key() or b'').hexdigest(),'valueSha256':hashlib.sha256(m.value()).hexdigest(),'payload':body}
   if not v['finished']:
    actual=DetectionTaskCreatedEvent.from_dict(body); entry.update(payloadSha256=task_digest(actual),workerWorkflowId=MysqlDetectionReceipts.workflow_id(actual))
   rows.append(entry)
  if m.offset()+1>=ends[m.partition()]: done.add(m.partition())
 print(json.dumps({'messages':rows,'endOffsets':{str(k):n for k,n in ends.items()}}))
finally: c.close()
"""
    environment = {'KAFKA_BOOTSTRAP_SERVERS': ctx.config['services']['detection-worker']['environment']['KAFKA_BOOTSTRAP_SERVERS']}
    return oneoff(ctx, code, {'task': task, 'finished': finished}, network='doorhandle-network',
                  environment=environment, suffix='kafka', timeout=45)


def objects(ctx, task, source_prefix, original_key):
    code = """import sys,os,json,hashlib,oss2
from kafka_detection_worker import build_result_prefix
v=json.load(sys.stdin); prefix=build_result_prefix(v['sourcePrefix'])
assert prefix.startswith(v['ownedPrefix']) and prefix!=v['sourcePrefix']
b=oss2.Bucket(oss2.Auth(os.environ['ALIYUN_OSS_ACCESS_KEY_ID'],os.environ['ALIYUN_OSS_ACCESS_KEY_SECRET']),os.environ['ALIYUN_OSS_ENDPOINT'],os.environ['ALIYUN_OSS_BUCKET'])
items=list(oss2.ObjectIterator(b,prefix=prefix)); assert 2<=len(items)<=8
manifest=[]; summary=None; requests=[]
for item in sorted(items,key=lambda x:x.key):
 assert item.key.startswith(prefix) and item.size<=26*1024*1024
 response=b.get_object(item.key); raw=response.read(); assert len(raw)==item.size
 assert response.request_id; requests.append(hashlib.sha256(response.request_id.encode()).hexdigest())
 manifest.append({'key':item.key,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'etag':item.etag,'lastModified':item.last_modified,'versionId':response.headers.get('x-oss-version-id')})
 if item.key==prefix+'detection_results.json': summary=json.loads(raw)
assert summary and summary['summary']['taskId']==v['task']
stats=summary['summary']['statistics']; assert stats['totalImages']==1 and stats['successfulImages']==1 and stats['failedImages']==0
assert len(summary['results'])==1 and summary['results'][0]['sourceKey']==v['originalKey']
assert summary['results'][0]['previewKey'] in [r['key'] for r in manifest] and not summary['summary']['errors']
print(json.dumps({'resultPrefix':prefix,'objects':manifest,'summarySha256':next(r['sha256'] for r in manifest if r['key']==prefix+'detection_results.json'),'readRequestIdSha256':requests,'successfulImages':stats['successfulImages'],'failedImages':stats['failedImages']}))
"""
    environment = {key: value for key, value in ctx.config['services']['detection-worker']['environment'].items()
                   if key.startswith('ALIYUN_OSS_')}
    return oneoff(ctx, code, {'task': task, 'sourcePrefix': source_prefix, 'originalKey': original_key,
        'ownedPrefix': 'runtime-acceptance/' + ctx.token + '/'}, network='worker-egress',
        environment=environment, suffix='oss')


def consumers(ctx):
    db = ctx.db
    settings = db.one("SELECT JSON_OBJECT('enabled',@@performance_schema,'size',@@performance_schema_events_statements_history_long_size);")
    require(settings['enabled'] == 1 and settings['size'] > 0, 'Owned MySQL statement history is unavailable for actual SIGNAL evidence')
    rows = db.query("SELECT JSON_OBJECT('name',NAME,'enabled',ENABLED) FROM performance_schema.setup_consumers WHERE NAME IN ('global_instrumentation','thread_instrumentation','events_statements_current','events_statements_history_long') ORDER BY NAME;")
    require(len(rows) == 4, 'Owned MySQL statement consumers are incomplete')
    instruments = db.query("SELECT JSON_OBJECT('name',NAME,'enabled',ENABLED,'timed',TIMED) FROM performance_schema.setup_instruments WHERE NAME LIKE 'statement/%' ORDER BY NAME;")
    require(instruments and all(row['enabled'] in ('YES', 'NO') and row['timed'] in ('YES', 'NO') for row in instruments),
            'Owned statement instrumentation has an unknown contract')
    return {'consumers': rows, 'instruments': instruments}


def enable_history(ctx):
    ctx.db.execute("UPDATE performance_schema.setup_consumers SET ENABLED='YES' WHERE NAME IN ('global_instrumentation','thread_instrumentation','events_statements_current','events_statements_history_long');\nUPDATE performance_schema.setup_instruments SET ENABLED='YES',TIMED='YES' WHERE NAME LIKE 'statement/%';")


def restore_history(ctx, original):
    statements = []
    for row in original['instruments']:
        statements.append('UPDATE performance_schema.setup_instruments SET ENABLED=' + ctx.db.literal(row['enabled'])
            + ',TIMED=' + ctx.db.literal(row['timed']) + ' WHERE NAME=' + ctx.db.literal(row['name']) + ';')
    for row in original['consumers']:
        statements.append('UPDATE performance_schema.setup_consumers SET ENABLED=' + ctx.db.literal(row['enabled'])
            + ' WHERE NAME=' + ctx.db.literal(row['name']) + ';')
    ctx.db.execute('\n'.join(statements))
    require(consumers(ctx) == original, 'Temporary statement observation settings were not restored exactly')


def receipt(ctx, task):
    columns = ctx.db.query("SELECT JSON_OBJECT('name',column_name) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='workflow_instance' ORDER BY ordinal_position;")
    require(columns, 'The actual worker receipt table disappeared')
    values = ','.join('IF(' + ctx.migration.quoted(row['name']) + ' IS NULL,NULL,HEX(CAST('
        + ctx.migration.quoted(row['name']) + ' AS BINARY)))' for row in columns)
    return ctx.db.query("SELECT JSON_OBJECT('id',workflow_id,'taskId',resource_id,'dispatchId',run_id,'eventId',request_id,"
        "'status',status,'requestSha256',request_sha256,'claimToken',claim_token,'revision',revision,"
        "'resultVersion',result_version,'result',result_json,'resultSha256',result_sha256,"
        "'rowSha256',SHA2(CAST(JSON_ARRAY(" + values + ") AS CHAR CHARACTER SET utf8mb4),256)) FROM workflow_instance WHERE kind='DETECTION_WORKER' AND resource_id="
        + ctx.db.literal(task) + ';')


def log(ctx, path, *, since=None):
    row = worker(ctx)
    command = [str(ctx.db.mysql.program), 'logs', '--tail', '350']
    if since:
        command += ['--since', since]
    raw = subprocess.run(command + [row['Id']], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=ctx.migration.Mysql.environment(), timeout=25, check=True).stdout
    require(len(raw) <= 4 * 1024 * 1024, 'Worker fault diagnostics exceed their private bound')
    with path.open('xb') as stream:
        path.chmod(0o600); stream.write(raw)
    return raw.decode('utf8', errors='replace'), sha(raw)


def group_offset(ctx, original, replayed):
    raw = ctx.ops.docker('exec', ctx.row('kafka')['Id'], '/opt/kafka/bin/kafka-consumer-groups.sh',
        '--bootstrap-server', 'kafka:9092', '--describe', '--group', 'runtime-' + ctx.token, timeout=25)
    rows = [line.split() for line in raw.decode().splitlines()]
    selected = [row for row in rows if len(row) >= 6 and row[1] == original['topic'] and row[2] == str(original['partition'])]
    require(len(selected) == 1, 'Actual worker consumer group partition is missing or ambiguous')
    row = selected[0]
    require(row[3] == '-' or row[3].isdigit(), 'Kafka returned an unknown committed offset')
    current = None if row[3] == '-' else int(row[3])
    require((current is None or current <= original['offset']) and row[4].isdigit() and row[5].isdigit()
            and int(row[4]) >= replayed['offset'] + 1 and int(row[5]) > 0,
            'The uncertain worker input or a later partition offset was acknowledged')
    return {'topic': row[1], 'partition': int(row[2]), 'committedOffset': current,
            'logEndOffset': int(row[4]), 'lag': int(row[5]), 'rawSha256': sha(raw)}


def run(ctx):
    require(ctx.guard.ecs_identity(ctx.identity) == ctx.identity
            and ctx.db.schema == ctx.owner['targetSchema']
            and re.fullmatch(r'doorhandle_compact_candidate_[a-f0-9]{10}', ctx.db.schema)
            and ctx.owner['mysqlContainerId'] != ctx.settings['sourceMysqlContainerId'],
            'Worker fault injection is limited to this ECS disposable migrated schema')
    require(ctx.owner.get('ossPrefixProvenEmpty') == 'runtime-acceptance/' + ctx.token + '/'
            and ctx.owner.get('detectionTaskId') == ctx.report_task_id
            and isinstance(ctx.worker_image_bytes, bytes) and ctx.worker_image_bytes.startswith(b'\x89PNG\r\n\x1a\n'),
            'Actual worker acceptance input and owned OSS prefix have not been established')
    server = ctx.db.mysql.admitted_server()
    _, original_metadata = ctx.migration.metadata_snapshot(ctx.db.mysql, ctx.db.schema)
    folder = ctx.directory / 'worker-unknown-result'; folder.mkdir(mode=0o700)
    instrumentation = consumers(ctx)
    instrumentation_sha = private(ctx, folder / 'statement-observation-before.json', instrumentation)
    name = 'rt_fence_' + ctx.token; marker = 'runtime_uncertain_completion_' + ctx.token
    require(re.fullmatch(r'rt_fence_[a-f0-9]{12}', name), 'Unowned fault trigger name')
    require(not ctx.db.query("SELECT JSON_OBJECT('name',trigger_name) FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name="
                             + ctx.db.literal(name) + ';'), 'Refuse to replace an existing fault trigger')
    owned = {'phase': 'PREPARING', 'schema': ctx.db.schema, 'serverUuid': server['serverUuid'],
             'trigger': name, 'marker': marker, 'workerContainerId': worker(ctx)['Id']}
    require('workerUnknownResult' not in ctx.owner, 'Unknown worker results must never be blindly replayed by the harness')
    ctx.owner['workerUnknownResult'] = owned; ctx.save()
    installed = False; history_changed = False; action = None; task = None
    try:
        row = worker(ctx)
        require(ctx.ops.healthy(row['Id']) and not row['State'].get('Paused'), 'Actual worker is not healthy before fault isolation')
        ctx.ops.docker('pause', row['Id'])
        require(worker(ctx)['State'].get('Paused') is True, 'Actual worker did not pause before dispatch')
        image = ctx.worker_image_bytes
        model = int(ctx.config['services']['detection-worker']['environment']['DETECTION_MODEL_ID'])
        require(model > 0, 'The actual PTH deployment is missing')
        created = ctx.request('inspector', 'POST', '/api/detection/tasks', {'taskType': 'BATCH',
            'files': [{'fileName': 'fence.png', 'contentType': 'image/png', 'relativePath': 'fence.png', 'fileSize': len(image)}],
            'captureInfo': {'captureDate': time.strftime('%Y-%m-%d'), 'region': '隔离验收',
                'collector': ctx.accounts['inspector']['username'], 'deviceName': 'runtime-fence-' + ctx.token,
                'imageFolderName': 'runtime-fence-' + ctx.token}, 'modelId': model, 'threshold': 0.5},
                headers={'X-Request-ID': 'runtime-fence-create-' + ctx.token})
        task = created['taskId']; upload = created['uploadUrls']
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task) and task != ctx.report_task_id and len(upload) == 1,
                'Actual unknown-result allocation is not a distinct one-image task')
        upload = upload[0]
        prefix = 'runtime-acceptance/' + ctx.token + '/'
        require(created['uploadPrefix'].startswith(prefix) and created['uploadPrefix'] != ctx.owner['detectionPrefix']
                and upload['objectKey'].startswith(created['uploadPrefix']), 'Fault input escaped its distinct owned OSS allocation')
        target = urllib.parse.urlsplit(upload['putUrl'])
        bucket = ctx.config['services']['detection-worker']['environment']['ALIYUN_OSS_BUCKET']
        require(target.scheme == 'http' and target.hostname in ('oss-proxy', bucket + '.oss-proxy') and target.port == 9000,
                'Fault input must use the restricted real OSS upload transport')
        owned.update(taskId=task, originalKey=upload['objectKey'], sourcePrefix=created['uploadPrefix'], phase='ALLOCATED')
        ctx.owner['objects'].append(upload['objectKey']); ctx.save()
        upload_code = """import sys,json,base64,urllib.request
v=json.load(sys.stdin); r=urllib.request.Request(v['url'],data=base64.b64decode(v['image']),method='PUT',headers={'Content-Type':'image/png'})
with urllib.request.urlopen(r,timeout=60) as s:
 assert s.status==200
 print(json.dumps({'etag':s.headers.get('ETag','').strip('"'),'requestId':s.headers.get('x-oss-request-id')}))
"""
        uploaded = json.loads(ctx.ops.docker('exec', '-i', ctx.row('model-fixture')['Id'], 'python', '-B', '-c', upload_code,
            data=json.dumps({'url': upload['putUrl'], 'image': base64.b64encode(image).decode()}).encode(), timeout=90))
        require(uploaded['etag'] and uploaded['requestId'], 'Real OSS fault input lacks its upload receipt')
        task_literal = ctx.db.literal(task)
        action = "BEGIN\nIF OLD.kind='DETECTION_WORKER' AND OLD.resource_id=" + task_literal + " AND OLD.status='RUNNING' " \
            "AND NEW.kind=OLD.kind AND NEW.resource_id=OLD.resource_id AND NEW.status='COMPLETED' " \
            "AND JSON_VALID(NEW.result_json) AND JSON_UNQUOTE(JSON_EXTRACT(NEW.result_json,'$.taskId'))=" + task_literal + \
            " AND JSON_UNQUOTE(JSON_EXTRACT(NEW.result_json,'$.status'))='COMPLETED' " \
            "AND JSON_EXTRACT(NEW.result_json,'$.successfulImages')=1 AND JSON_EXTRACT(NEW.result_json,'$.failedImages')=0 " \
            "AND NEW.result_sha256=SHA2(NEW.result_json,256) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT=" + ctx.db.literal(marker) + "; END IF;\nEND"
        history_changed = True; enable_history(ctx)
        # Journal precedes CREATE: an interrupted client result is not retried.
        owned['phase'] = 'INSTALLING_TRIGGER'; ctx.save()
        ctx.db.execute('DELIMITER $$\nCREATE TRIGGER ' + ctx.migration.quoted(name)
            + ' BEFORE UPDATE ON workflow_instance FOR EACH ROW ' + action + '$$\nDELIMITER ;\n')
        installed = True
        owned['phase'] = 'FAULT_ARMED'; ctx.save()
        allocated = ctx.request('inspector', 'GET', '/api/detection/tasks/' + task)
        ctx.request('inspector', 'POST', '/api/detection/tasks/' + task + '/uploaded', {'modelId': model, 'threshold': 0.5,
            'uploadedFiles': [{'fileName': upload['fileName'], 'objectKey': upload['objectKey'], 'etag': uploaded['etag'], 'sha256': sha(image)}]},
            headers=ctx.http.command_headers(allocated, 'runtime-fence-uploaded-' + ctx.token))
        original = kafka_observe(ctx, task)['messages']
        require(len(original) == 1, 'The backend did not publish exactly one actual created event before processing')
        original = original[0]; payload = original['payload']
        require(payload['taskId'] == task and payload['modelId'] == model and payload['originalKeys'] == [upload['objectKey']]
                and payload['sourcePrefix'] == created['uploadPrefix'], 'Actual created event differs from the uploaded worker task')
        private(ctx, folder / 'original-created-event.json', original)
        ctx.ops.docker('unpause', row['Id'])
        deadline = time.monotonic() + 420
        while True:
            values = receipt(ctx, task)
            if values and values[0]['status'] == 'NEEDS_REVIEW' and not worker(ctx)['State']['Running']:
                break
            require(not values or len(values) == 1 and values[0]['status'] in ('RUNNING', 'NEEDS_REVIEW'),
                    'Actual worker bypassed the armed successful-result failure')
            require(time.monotonic() < deadline, 'Actual PTH inference did not reach the uncertain receipt boundary')
            time.sleep(2)
        require(len(values) == 1, 'Unknown worker outcome has ambiguous durable receipts')
        unknown = values[0]
        require(unknown['id'] == original['workerWorkflowId'] and unknown['requestSha256'] == original['payloadSha256']
                and unknown['dispatchId'] == payload['dispatchId'] and unknown['eventId'] == payload['eventId']
                and unknown['result'] is None and unknown['resultSha256'] is None and unknown['resultVersion'] is None
                and unknown['claimToken'] and re.fullmatch(r'[a-f0-9]{64}', unknown['requestSha256'])
                and worker(ctx)['State']['ExitCode'] != 0, 'The actual failed completion did not retain its original uncertain fence')
        failures = ctx.db.query("SELECT JSON_OBJECT('threadId',THREAD_ID,'eventId',EVENT_ID,'error',MYSQL_ERRNO,'sqlState',RETURNED_SQLSTATE,"
            "'message',MESSAGE_TEXT,'statementSha256',SHA2(SQL_TEXT,256)) FROM performance_schema.events_statements_history_long "
            "WHERE MYSQL_ERRNO=1644 AND RETURNED_SQLSTATE='45000' AND MESSAGE_TEXT=" + ctx.db.literal(marker)
            + " AND SQL_TEXT LIKE 'UPDATE workflow_instance SET status=%' AND LOCATE(" + task_literal + ',SQL_TEXT)>0 ORDER BY THREAD_ID,EVENT_ID;')
        require(len(failures) == 1, 'No exact real completion UPDATE/SQL SIGNAL was observed in owned MySQL')
        failed_text, failed_sha = log(ctx, folder / 'worker-completion-failed.log')
        require('detection_worker_receipts.ReceiptUnavailable' in failed_text and 'execute_once' in failed_text
                and 'store.complete' in failed_text, 'The actual worker did not fail at its persisted completion boundary')
        results = objects(ctx, task, created['uploadPrefix'], upload['objectKey'])
        require(kafka_observe(ctx, task, finished=True)['messages'] == [], 'An uncertain receipt published a finished event')
        unknown_sha = private(ctx, folder / 'unknown-receipt.json', unknown)
        results_sha = private(ctx, folder / 'actual-oss-results.json', results)
        private(ctx, folder / 'actual-completion-signal.json', failures[0])
        # Remove only the exact owned trigger before testing the unmodified fence.
        drop_trigger(ctx, name, action)
        installed = False
        restore_history(ctx, instrumentation); history_changed = False
        require(ctx.migration.metadata_snapshot(ctx.db.mysql, ctx.db.schema)[1] == original_metadata,
                'The fault harness did not restore the complete compact schema metadata')
        owned.update(phase='REPLAYING_UNCERTAIN_INPUT', workerReceiptId=unknown['id'], resultSnapshotSha256=results_sha); ctx.save()
        restarted_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        ctx.dc('restart', 'detection-worker', timeout=150)
        deadline = time.monotonic() + 180
        while not ctx.ops.healthy(worker(ctx)['Id']):
            require(time.monotonic() < deadline, 'The actual worker did not restart for uncertain-input reconciliation')
            time.sleep(2)
        replayed = json.loads(ctx.ops.docker('exec', '-i', worker(ctx)['Id'], 'python', '-B', '-c', ctx.replay_script,
            data=json.dumps({'task': task}).encode(), timeout=45))
        require(replayed['topic'] == original['topic'] and replayed['partition'] == original['partition']
                and replayed['offset'] > original['offset'], 'The original actual created event was not redelivered to its partition')
        # Two real reconciliation periods must retain the fence and leave this
        # partition uncommitted. Other partitions are free to make progress.
        stable_after = time.monotonic() + 12
        while time.monotonic() < stable_after:
            require(receipt(ctx, task) == values and worker(ctx)['State']['Running'],
                    'The uncertain receipt or its processing worker changed during replay')
            time.sleep(2)
        offset = group_offset(ctx, original, replayed)
        paused_text, paused_sha = log(ctx, folder / 'worker-replay-paused.log', since=restarted_at)
        require('Detection partition paused for receipt reconciliation' in paused_text,
                'The actual restarted worker did not pause the uncertain partition')
        after = objects(ctx, task, created['uploadPrefix'], upload['objectKey'])
        require(after['resultPrefix'] == results['resultPrefix'] and after['objects'] == results['objects']
                and after['summarySha256'] == results['summarySha256'] and receipt(ctx, task) == values
                and kafka_observe(ctx, task, finished=True)['messages'] == [],
                'Redelivery rewrote actual inference objects, receipts or finished events')
        require(ctx.db.mysql.admitted_server() == server, 'The owned database identity changed during fault injection')
        observed = {'taskId': task, 'workerReceiptId': unknown['id'], 'status': unknown['status'],
            'unknownReceiptSha256': unknown_sha, 'unknownRowSha256': unknown['rowSha256'], 'inputSha256': sha(image),
            'uploadRequestIdSha256': sha(uploaded['requestId'].encode()), 'actualSuccessfulImages': results['successfulImages'],
            'actualFailedImages': results['failedImages'], 'actualResultsSha256': results_sha,
            'actualSummarySha256': results['summarySha256'], 'actualCompletionSignal': failures[0],
            'workerCompletionFailureLogSha256': failed_sha, 'workerReplayPausedLogSha256': paused_sha,
            'originalCreatedEvent': {key: value for key, value in original.items() if key != 'payload'},
            'actualRedelivery': replayed, 'actualUncommittedPartition': offset,
            'observationSettingsBeforeSha256': instrumentation_sha, 'compactMetadataSha256': original_metadata,
            'replayProof': 'NEEDS_REVIEW row unchanged; actual OSS bytes/etag/lastModified unchanged; no finished event; actual worker paused with input uncommitted',
            'workerCodeSha256': sha((ctx.source / 'kafka_detection_worker.py').read_bytes()),
            'receiptCodeSha256': sha((ctx.source / 'detection_worker_receipts.py').read_bytes())}
        evidence = {**ctx.context(), 'kind': 'doorhandle-runtime-worker-unknown-result', 'project': ctx.project,
            'status': 'VERIFIED', 'schema': ctx.db.schema, 'serverUuid': server['serverUuid'], 'observations': observed}
        evidence_sha = private(ctx, folder / 'evidence.json', evidence)
        owned.update(phase='VERIFIED', evidenceSha256=evidence_sha); ctx.save()
        return {**observed, 'evidenceSha256': evidence_sha}
    except BaseException:
        owned['phase'] = 'FAILED_OR_UNKNOWN_STOPPED'; ctx.save()
        raise
    finally:
        cleanup_failures = []
        if owned['phase'] != 'VERIFIED':
            try:
                actual = worker(ctx)
                if actual['State'].get('Paused'):
                    ctx.ops.docker('unpause', actual['Id'])
                ctx.ops.docker('stop', '--time', '30', actual['Id'], timeout=90)
                require(not worker(ctx)['State']['Running'] and worker(ctx)['State']['Pid'] == 0,
                        'Owned fault worker did not stop after a failed or unknown result')
            except Exception:
                cleanup_failures.append('owned-worker-stop')
        # CREATE can have an unknown client result: inspect once, never retry it.
        if installed or action is not None:
            try:
                drop_trigger(ctx, name, action)
            except Exception:
                cleanup_failures.append('owned-trigger-removal')
        if history_changed:
            try:
                restore_history(ctx, instrumentation)
            except Exception:
                cleanup_failures.append('owned-statement-observation-restore')
        if cleanup_failures:
            owned.update(phase='CLEANUP_NEEDS_REVIEW', cleanupFailures=cleanup_failures); ctx.save()
            raise ValueError('Worker fault cleanup has unverified owned resources: ' + ','.join(cleanup_failures))


def drop_trigger(ctx, name, action):
    rows = ctx.db.query("SELECT JSON_OBJECT('table',event_object_table,'event',event_manipulation,'timing',action_timing,'body',action_statement) "
        'FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name=' + ctx.db.literal(name) + ';')
    if rows:
        require(len(rows) == 1 and rows[0]['table'] == 'workflow_instance' and rows[0]['event'] == 'UPDATE'
                and rows[0]['timing'] == 'BEFORE' and rows[0]['body'].strip() == action.strip(),
                'Refuse to remove a trigger that differs from this exact owned fault')
        ctx.db.execute('DROP TRIGGER ' + ctx.migration.quoted(name) + ';')
    require(not ctx.db.query("SELECT JSON_OBJECT('name',trigger_name) FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name="
                             + ctx.db.literal(name) + ';'), 'Owned fault trigger cleanup was not observed')
