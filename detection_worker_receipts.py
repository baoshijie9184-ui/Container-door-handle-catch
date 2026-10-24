"""MySQL execution fences: an uncertain detection is never automatically replayed.

Only short receipt transactions hold locks. CPU inference and OSS/Kafka I/O run
outside them. There is deliberately no lease that can reclaim a RUNNING write.
"""
import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass


class ReceiptPending(RuntimeError):
    def __init__(self):
        super().__init__('Detection execution requires receipt reconciliation')


class ReceiptUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Detection receipt store unavailable or inconsistent')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def task_digest(task):
    data = asdict(task)
    data.pop('event_id')
    data.pop('event_time')
    return digest(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False))


@dataclass(frozen=True)
class Claim:
    owner: str = ''
    result: str = None


class MysqlDetectionReceipts:
    def __init__(self, connect):
        self.connect = connect

    @classmethod
    def from_settings(cls, settings):
        import pymysql
        return cls(lambda: pymysql.connect(
            host=settings.receipt_db_host, port=settings.receipt_db_port,
            database=settings.receipt_db_database, user=settings.receipt_db_user,
            password=settings.receipt_db_password, charset='utf8mb4',
            connect_timeout=5, read_timeout=10, write_timeout=10, autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            init_command="SET time_zone = '+08:00'"))

    @contextmanager
    def transaction(self):
        connection = None
        try:
            connection = self.connect()
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except (ReceiptPending, ReceiptUnavailable):
            if connection is not None:
                connection.rollback()
            raise
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise ReceiptUnavailable() from None
        finally:
            if connection is not None:
                connection.close()

    def validate_schema(self):
        with self.transaction() as cursor:
            cursor.execute('SELECT task_id,dispatch_id,event_id,payload_sha256,owner_id,status,'
                           'result_json,result_sha256 FROM detection_worker_receipt LIMIT 0')

    def claim(self, task):
        for value, limit in ((task.task_id, 128), (task.dispatch_id, 64), (task.event_id, 128)):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,' + str(limit) + '}', value):
                raise ReceiptUnavailable()
        owner = uuid.uuid4().hex
        fingerprint = task_digest(task)
        with self.transaction() as cursor:
            # A duplicate event ID attached to a different task cannot acquire a fence.
            cursor.execute('INSERT INTO detection_worker_receipt '
                           '(task_id,dispatch_id,event_id,payload_sha256,owner_id,status,started_at,updated_at) '
                           "VALUES (%s,%s,%s,%s,%s,'RUNNING',CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6)) "
                           'ON DUPLICATE KEY UPDATE task_id=task_id',
                           (task.task_id, task.dispatch_id, task.event_id, fingerprint, owner))
            cursor.execute('SELECT * FROM detection_worker_receipt WHERE task_id=%s AND dispatch_id=%s FOR UPDATE',
                           (task.task_id, task.dispatch_id))
            row = cursor.fetchone()
            if row is None or row['payload_sha256'] != fingerprint or row['event_id'] != task.event_id:
                raise ReceiptUnavailable()
            if row['owner_id'] == owner and row['status'] == 'RUNNING':
                return Claim(owner=owner)
            return Claim(result=self.completed_result(task, row))

    def completed(self, task):
        """Waiting-message reconciliation must never create a new execution fence."""
        with self.transaction() as cursor:
            cursor.execute('SELECT * FROM detection_worker_receipt WHERE task_id=%s AND dispatch_id=%s',
                           (task.task_id, task.dispatch_id))
            return self.completed_result(task, cursor.fetchone())

    def completed_result(self, task, row):
        if row is None or row['payload_sha256'] != task_digest(task) or row['event_id'] != task.event_id:
            raise ReceiptUnavailable()
        if row['status'] != 'COMPLETED':
            raise ReceiptPending()
        if not re.fullmatch(r'[0-9a-f]{64}', row['result_sha256'] or ''):
            raise ReceiptUnavailable()
        self.validate_result(task, row['result_json'], row['result_sha256'])
        return row['result_json']

    @staticmethod
    def validate_result(task, result, expected_digest=None):
        if not isinstance(result, str) or len(result.encode('utf-8')) > 8 * 1024 * 1024:
            raise ReceiptUnavailable()
        try:
            data = json.loads(result)
        except (ValueError, TypeError):
            raise ReceiptUnavailable() from None
        if (not isinstance(data, dict) or data.get('taskId') != task.task_id
                or data.get('dispatchId') != task.dispatch_id
                or data.get('eventId') != f'{task.task_id}-{task.dispatch_id}-finished'
                or data.get('eventType') != 'DETECTION_TASK_FINISHED'
                or data.get('status') not in {'COMPLETED', 'PARTIAL_FAILED', 'FAILED'}
                or expected_digest is not None and digest(result) != expected_digest):
            raise ReceiptUnavailable()

    def complete(self, task, claim, result):
        self.validate_result(task, result)
        with self.transaction() as cursor:
            cursor.execute("UPDATE detection_worker_receipt SET status='COMPLETED',result_json=%s,result_sha256=%s,"
                           'updated_at=CURRENT_TIMESTAMP(6) WHERE task_id=%s AND dispatch_id=%s AND owner_id=%s '
                           "AND payload_sha256=%s AND status='RUNNING'",
                           (result, digest(result), task.task_id, task.dispatch_id, claim.owner, task_digest(task)))
            if cursor.rowcount != 1:
                raise ReceiptUnavailable()

    def mark_unknown(self, task, claim):
        with self.transaction() as cursor:
            cursor.execute("UPDATE detection_worker_receipt SET status='NEEDS_REVIEW',updated_at=CURRENT_TIMESTAMP(6) "
                           "WHERE task_id=%s AND dispatch_id=%s AND owner_id=%s AND status='RUNNING'",
                           (task.task_id, task.dispatch_id, claim.owner))


def execute_once(task, store, operation):
    """Persist the full finished event before it is published or its input committed."""
    claim = store.claim(task)
    if claim.result is not None:
        return claim.result
    try:
        result = operation()
        store.complete(task, claim, result)
        return result
    except BaseException:
        # A failed commit may already have succeeded. Never replace COMPLETED or
        # reacquire RUNNING, and never let a reconciliation failure rerun inference.
        try:
            store.mark_unknown(task, claim)
        except Exception:
            pass
        raise
