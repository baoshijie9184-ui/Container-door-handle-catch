"""Create missing development topics without modifying existing topics or messages."""
from pathlib import Path

from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka import KafkaException, KafkaError
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
config = dotenv_values(root / ".env")
bootstrap = config.get("APP_KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
if bootstrap not in ("127.0.0.1:9092", "localhost:9092"):
    raise SystemExit("Local startup requires APP_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092; remote brokers are not modified.")
admin = AdminClient({"bootstrap.servers": bootstrap, "socket.timeout.ms": 5000})
required = {config.get("APP_KAFKA_TOPIC_TASK_" + kind.upper()) or "detection.task." + kind
            for kind in ("created", "finished", "progress")}
if config.get('APP_REPORT_EVENTS_ENABLED','false').lower()=='true':
    required.add(config.get('APP_REPORT_EVENTS_TOPIC') or 'detection.report.lifecycle.v1')
existing = admin.list_topics(timeout=10).topics
missing = [NewTopic(name, num_partitions=1, replication_factor=1) for name in sorted(required - existing.keys())]
if missing:
    for name, future in admin.create_topics(missing, request_timeout=10).items():
        try:
            future.result()
        except KafkaException as error:
            if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
print("Kafka project topics ready: " + ", ".join(sorted(required)))
