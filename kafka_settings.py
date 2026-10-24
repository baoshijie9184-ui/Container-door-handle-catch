import os
from dataclasses import dataclass, field


@dataclass
class KafkaWorkerSettings:
    kafka_bootstrap_servers: str
    task_created_topic: str
    task_finished_topic: str
    consumer_group: str
    oss_endpoint: str
    oss_bucket: str
    oss_access_key_id: str
    oss_access_key_secret: str
    delivery_timeout_seconds: float = 10.0
    receipts_enabled: bool = False
    receipt_db_host: str = ''
    receipt_db_port: int = 3306
    receipt_db_database: str = ''
    receipt_db_user: str = ''
    receipt_db_password: str = field(default='', repr=False)

    @classmethod
    def from_env(cls) -> "KafkaWorkerSettings":
        return cls(
            kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            task_created_topic=os.getenv("KAFKA_TASK_CREATED_TOPIC", "detection.task.created"),
            task_finished_topic=os.getenv("KAFKA_TASK_FINISHED_TOPIC", "detection.task.finished"),
            consumer_group=os.getenv("KAFKA_CONSUMER_GROUP", "doorhandlecatch-python"),
            oss_endpoint=os.getenv("ALIYUN_OSS_ENDPOINT", ""),
            oss_bucket=os.getenv("ALIYUN_OSS_BUCKET", ""),
            oss_access_key_id=os.getenv("ALIYUN_OSS_ACCESS_KEY_ID", ""),
            oss_access_key_secret=os.getenv("ALIYUN_OSS_ACCESS_KEY_SECRET", ""),
            delivery_timeout_seconds=float(os.getenv("KAFKA_DELIVERY_TIMEOUT_SECONDS", "10")),
            receipts_enabled=os.getenv('DETECTION_WORKER_RECEIPTS_ENABLED', 'false').lower() == 'true',
            receipt_db_host=os.getenv('DETECTION_RECEIPT_DB_HOST', ''),
            receipt_db_port=int(os.getenv('DETECTION_RECEIPT_DB_PORT', '3306')),
            receipt_db_database=os.getenv('DETECTION_RECEIPT_DB_DATABASE', ''),
            receipt_db_user=os.getenv('DETECTION_RECEIPT_DB_USER', ''),
            receipt_db_password=os.getenv('DETECTION_RECEIPT_DB_PASSWORD', ''),
        )

    def validate(self) -> None:
        missing = []
        for field_name in (
            "kafka_bootstrap_servers",
            "task_created_topic",
            "task_finished_topic",
            "consumer_group",
            "oss_endpoint",
            "oss_bucket",
            "oss_access_key_id",
            "oss_access_key_secret",
        ):
            if not getattr(self, field_name):
                missing.append(field_name)
        if missing:
            raise ValueError(f"Missing required worker settings: {', '.join(missing)}")
        if self.delivery_timeout_seconds <= 0:
            raise ValueError("KAFKA_DELIVERY_TIMEOUT_SECONDS must be positive")
        if self.receipts_enabled:
            for name in ('receipt_db_host', 'receipt_db_database', 'receipt_db_user', 'receipt_db_password'):
                if not getattr(self, name):
                    raise ValueError('Missing required worker setting: ' + name)
            if not 1 <= self.receipt_db_port <= 65535:
                raise ValueError('Invalid receipt database port')
