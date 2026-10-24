import copy
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from detection_worker_receipts import (
    Claim, MysqlDetectionReceipts, ReceiptPending, ReceiptUnavailable, execute_once,
)
from kafka_event_models import DetectionTaskCreatedEvent


@pytest.fixture
def task():
    return DetectionTaskCreatedEvent('event-' + uuid.uuid4().hex, 'DETECTION_TASK_CREATED', '',
                                    'task-' + uuid.uuid4().hex, 'dispatch-1', 'private', 'originals/',
                                    ['originals/门把手.jpg'], model_id=12, threshold='0.5')


def finished(task):
    return json.dumps(dict(taskId=task.task_id, dispatchId=task.dispatch_id,
                          eventId=f'{task.task_id}-{task.dispatch_id}-finished',
                          eventType='DETECTION_TASK_FINISHED', status='COMPLETED',
                          resultJsonKey='private/结果.json'), ensure_ascii=False)


@pytest.fixture(scope='module')
def mysql_connect():
    if os.getenv('DOORHANDLE_WORKER_MYSQL_TESTS') != '1':
        pytest.skip('Explicit isolated real MySQL verification is not enabled')
    import pymysql
    from dotenv import dotenv_values
    root = Path(__file__).resolve().parents[1]
    values = dotenv_values(root / '.env')
    credentials = dict(host='127.0.0.1', port=3306,
                       user=os.getenv('DB_USERNAME') or values.get('DB_USERNAME') or 'root',
                       password=os.getenv('DB_PASSWORD') or values.get('DB_PASSWORD') or '',
                       charset='utf8mb4', connect_timeout=5, autocommit=False,
                       cursorclass=pymysql.cursors.DictCursor,
                       init_command="SET time_zone = '+08:00'")
    name = 'doorhandle_worker_verify_' + uuid.uuid4().hex[:10]
    admin = pymysql.connect(**credentials)
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
        def connect():
            return pymysql.connect(database=name, **credentials)
        connection = connect()
        try:
            with connection.cursor() as cursor:
                for statement in (root / 'sql/mysql/migration-V42-detection-execution.sql').read_text('utf-8').split(';'):
                    if statement.strip():
                        cursor.execute(statement)
            connection.commit()
        finally:
            connection.close()
        yield connect
    finally:
        assert name.startswith('doorhandle_worker_verify_') and len(name) == 35
        with admin.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS `{name}`')
        admin.close()


@pytest.fixture
def store(mysql_connect):
    return MysqlDetectionReceipts(mysql_connect)


def test_completed_result_survives_new_process_and_no_second_detection(store, mysql_connect, task):
    calls = []
    result = execute_once(task, store, lambda: calls.append('inference') or finished(task))
    restored = MysqlDetectionReceipts(mysql_connect)
    assert execute_once(task, restored, lambda: pytest.fail('Completed inference must not replay')) == result
    assert calls == ['inference']
    restored.validate_schema()


def test_crashed_running_attempt_is_not_reclaimed(store, mysql_connect, task):
    store.claim(task)
    restored = MysqlDetectionReceipts(mysql_connect)
    with pytest.raises(ReceiptPending):
        execute_once(task, restored, lambda: pytest.fail('Unknown write must not replay'))


def test_waiting_reconciliation_never_creates_missing_receipt(store, task):
    store.claim(task)
    with store.transaction() as cursor:
        cursor.execute('DELETE FROM detection_worker_receipt WHERE task_id=%s', (task.task_id,))
    with pytest.raises(ReceiptUnavailable):
        store.completed(task)
    with store.transaction() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM detection_worker_receipt WHERE task_id=%s', (task.task_id,))
        assert cursor.fetchone()['total'] == 0


def test_changed_dispatch_payload_cannot_reuse_result(store, task):
    execute_once(task, store, lambda: finished(task))
    changed = copy.deepcopy(task)
    changed.original_keys.append('private/other.jpg')
    with pytest.raises(ReceiptUnavailable):
        execute_once(changed, store, lambda: pytest.fail('Conflicting payload must not run'))


def test_event_id_cannot_be_assigned_to_different_task(store, task):
    store.claim(task)
    changed = copy.deepcopy(task)
    changed.task_id = 'other-task'
    with pytest.raises(ReceiptUnavailable):
        store.claim(changed)


def test_inference_failure_is_durable_pending_review(store, task, mysql_connect):
    def broken():
        raise RuntimeError('injected interruption after OSS write')
    with pytest.raises(RuntimeError, match='injected interruption'):
        execute_once(task, store, broken)
    with MysqlDetectionReceipts(mysql_connect).transaction() as cursor:
        cursor.execute('SELECT status FROM detection_worker_receipt WHERE task_id=%s', (task.task_id,))
        assert cursor.fetchone()['status'] == 'NEEDS_REVIEW'
    with pytest.raises(ReceiptPending):
        execute_once(task, store, lambda: pytest.fail('Uncertain write must not replay'))


def test_wrong_execution_owner_cannot_complete_or_release_fence(store, task):
    claim = store.claim(task)
    wrong = Claim(owner='another-process')
    with pytest.raises(ReceiptUnavailable):
        store.complete(task, wrong, finished(task))
    store.mark_unknown(task, wrong)
    store.complete(task, claim, finished(task))
    assert store.claim(task).result == finished(task)


@pytest.mark.parametrize('clear_hash', [False, True])
def test_corrupted_stored_result_fails_closed(store, task, clear_hash):
    execute_once(task, store, lambda: finished(task))
    with store.transaction() as cursor:
        if clear_hash:
            cursor.execute('UPDATE detection_worker_receipt SET result_sha256=NULL WHERE task_id=%s', (task.task_id,))
        else:
            cursor.execute('UPDATE detection_worker_receipt SET result_json=%s WHERE task_id=%s',
                           (finished(task).replace('结果', '损坏'), task.task_id))
    with pytest.raises(ReceiptUnavailable):
        execute_once(task, store, lambda: pytest.fail('Corrupt receipt must not replay inference'))


def test_two_workers_execute_one_dispatch_once(store, mysql_connect, task):
    entered, finish = Event(), Event()
    calls = []
    def inference():
        calls.append('inference')
        entered.set()
        assert finish.wait(5)
        return finished(task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute_once, task, store, inference)
        try:
            assert entered.wait(5)
            second = pool.submit(execute_once, task, MysqlDetectionReceipts(mysql_connect),
                                 lambda: pytest.fail('A second worker must not infer'))
            with pytest.raises(ReceiptPending):
                second.result(timeout=5)
        finally:
            finish.set()
        assert first.result(timeout=5) == finished(task)
    assert calls == ['inference']


def test_commit_ack_lost_reuses_completed_receipt(store, mysql_connect, task):
    claim = store.claim(task)
    result = finished(task)
    class AckLostConnection:
        def __init__(self):
            self.connection = mysql_connect()
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            raise OSError('injected lost database acknowledgement')
    uncertain = MysqlDetectionReceipts(AckLostConnection)
    with pytest.raises(ReceiptUnavailable):
        uncertain.complete(task, claim, result)
    # The owner's fallback cannot overwrite the actual committed completion.
    store.mark_unknown(task, claim)
    assert execute_once(task, store, lambda: pytest.fail('Committed result must be reused')) == result


def test_kafka_delivery_failure_does_not_repeat_detection(store, task):
    from kafka_detection_worker import publish_finished_and_commit
    calls = []
    class Producer:
        def produce(self, *args, **kwargs):
            kwargs['callback'](RuntimeError('unavailable'), None)
        def flush(self, *args):
            return 0
    class Consumer:
        def commit(self, **kwargs):
            pytest.fail('Unacknowledged result must not commit its source offset')
    result = execute_once(task, store, lambda: calls.append(1) or finished(task))
    with pytest.raises(RuntimeError, match='delivery failed'):
        publish_finished_and_commit(Producer(), Consumer(), 'source', 'finished', b'task', result.encode(), 1)
    assert execute_once(task, store, lambda: pytest.fail('Kafka retry must reuse receipt')) == result
    assert calls == [1]


def test_receipt_database_unavailable_prevents_inference(task):
    def unavailable():
        raise OSError('private database connection details')
    store = MysqlDetectionReceipts(unavailable)
    with pytest.raises(ReceiptUnavailable) as error:
        execute_once(task, store, lambda: pytest.fail('No receipt, no inference'))
    assert 'private' not in str(error.value)


def test_explicit_new_dispatch_is_independent_of_previous_receipt(store, task):
    execute_once(task, store, lambda: finished(task))
    retry = copy.deepcopy(task)
    retry.dispatch_id, retry.event_id = 'new-dispatch', 'retry-' + task.event_id
    calls = []
    assert execute_once(retry, store, lambda: calls.append('confirmed retry') or finished(retry)) == finished(retry)
    assert calls == ['confirmed retry']


def test_receipt_setting_requires_credentials_without_exposing_password():
    from kafka_settings import KafkaWorkerSettings
    settings = KafkaWorkerSettings('broker', 'created', 'finished', 'group', 'oss', 'bucket', 'key', 'secret',
                                   receipts_enabled=True, receipt_db_password='private-receipt-password')
    with pytest.raises(ValueError, match='receipt_db_host'):
        settings.validate()
    assert 'private-receipt-password' not in repr(settings)


def test_result_bound_to_original_dispatch_before_persistence(task):
    invalid = json.loads(finished(task))
    invalid['dispatchId'] = 'other-dispatch'
    with pytest.raises(ReceiptUnavailable):
        MysqlDetectionReceipts.validate_result(task, json.dumps(invalid))


@pytest.mark.parametrize('resolve_pending', [False, True])
def test_worker_pauses_unknown_partition_without_blocking_other_tasks(store, task, monkeypatch, resolve_pending):
    import sys
    from types import SimpleNamespace
    import kafka_detection_worker as worker
    import worker_health
    from kafka_settings import KafkaWorkerSettings
    first_claim = store.claim(task)  # an interrupted or still running worker
    claimed = []
    original_claim = store.claim
    def counted_claim(current):
        claimed.append(current.task_id)
        return original_claim(current)
    monkeypatch.setattr(store, 'claim', counted_claim)
    other = copy.deepcopy(task)
    other.task_id, other.event_id, other.dispatch_id = 'other-' + task.task_id, 'other-' + task.event_id, 'other-dispatch'
    calls, offsets, paused, resumed = [], [], [], []
    tick = [0.0]
    def message(current, partition):
        value = json.dumps(dict(eventId=current.event_id, eventType=current.event_type,
                                taskId=current.task_id, dispatchId=current.dispatch_id,
                                bucketName=current.bucket_name, sourcePrefix=current.source_prefix,
                                originalKeys=current.original_keys, modelId=current.model_id,
                                threshold=current.threshold)).encode()
        return SimpleNamespace(value=lambda: value, key=lambda: current.task_id.encode(),
                               error=lambda: None, topic=lambda: 'created', partition=lambda: partition)
    inputs = [message(task, 0), message(other, 1)]
    class Consumer:
        def __init__(self, config):
            assert config['enable.auto.commit'] is False
            self.polls = 0
        def subscribe(self, topics, **callbacks):
            callbacks['on_assign'](self, [SimpleNamespace(topic='created', partition=0),
                                        SimpleNamespace(topic='created', partition=1)])
        def assign(self, partitions):
            pass
        def poll(self, timeout):
            self.polls += 1
            if self.polls <= 2:
                return inputs[self.polls - 1]
            if self.polls == 3:
                if resolve_pending:
                    store.complete(task, first_claim, finished(task))
                tick[0] = 6.0
                return None
            raise KeyboardInterrupt()
        def pause(self, partitions):
            paused.extend((p.topic, p.partition) for p in partitions)
        def resume(self, partitions):
            resumed.extend((p.topic, p.partition) for p in partitions)
        def commit(self, message, asynchronous):
            assert asynchronous is False
            offsets.append(message.partition())
        def close(self):
            pass
    class Producer:
        def __init__(self, config):
            pass
        def produce(self, topic, key, value, callback):
            callback(None, None)
        def flush(self, timeout):
            return 0
    settings = KafkaWorkerSettings('broker', 'created', 'finished', 'group', 'oss', 'private', 'key', 'secret',
                                   receipts_enabled=True, receipt_db_host='mysql', receipt_db_database='db',
                                   receipt_db_user='worker', receipt_db_password='secret')
    monkeypatch.setitem(sys.modules, 'confluent_kafka', SimpleNamespace(
        Consumer=Consumer, Producer=Producer, TopicPartition=lambda t, p: SimpleNamespace(topic=t, partition=p)))
    monkeypatch.setattr(worker, 'load_settings', lambda: settings)
    monkeypatch.setattr(worker.MysqlDetectionReceipts, 'from_settings', lambda settings: store)
    monkeypatch.setattr(worker, 'create_oss_bucket', lambda _: object())
    monkeypatch.setattr(worker.time, 'monotonic', lambda: tick[0])
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(worker_health, 'write_health', lambda *args: None)
    monkeypatch.setenv('DETECTION_ENGINE', 'deim')
    def infer(current, *args):
        calls.append(current.task_id)
        return SimpleNamespace(to_dict=lambda: json.loads(finished(current)))
    monkeypatch.setattr(worker, 'process_created_event', infer)
    with pytest.raises(KeyboardInterrupt):
        worker.run_worker()
    assert calls == [other.task_id]
    assert claimed == [task.task_id, other.task_id]  # retries only query the existing receipt
    assert paused == [('created', 0)]
    assert offsets == ([1, 0] if resolve_pending else [1])
    assert resumed == ([('created', 0)] if resolve_pending else [])
