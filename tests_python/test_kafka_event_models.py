import json
from io import BytesIO

from PIL import Image

from kafka_detection_worker import process_created_event
from kafka_event_models import DetectionTaskCreatedEvent
from kafka_settings import KafkaWorkerSettings
from oss_result_uploader import OssResultUploader


def test_created_event_parses_capture_info_and_original_keys():
    payload = {
        "eventId": "evt-created-001",
        "eventType": "DETECTION_TASK_CREATED",
        "eventTime": "2026-05-20T16:10:00+08:00",
        "taskId": "det_20260520_xxx",
        "dispatchId": "dispatch-001",
        "bucketName": "doorhandlecatch",
        "sourcePrefix": "detection/2026-05-20/上海/张三/设备A/批次A/Original/",
        "originalKeys": [
            "detection/2026-05-20/上海/张三/设备A/批次A/Original/车间A/img001.jpg",
            "detection/2026-05-20/上海/张三/设备A/批次A/Original/车间A/img002.jpg",
        ],
        "captureInfo": {
            "captureDate": "2026-05-20",
            "region": "上海",
            "collector": "张三",
            "deviceName": "设备A",
            "imageFolderName": "批次A",
        },
        "modelId": 7,
        "threshold": "0.50",
    }

    event = DetectionTaskCreatedEvent.from_dict(payload)

    assert event.task_id == "det_20260520_xxx"
    assert event.dispatch_id == "dispatch-001"
    assert event.capture_info.capture_date == "2026-05-20"
    assert event.capture_info.region == "上海"
    assert event.capture_info.image_folder_name == "批次A"
    assert len(event.original_keys) == 2
    assert event.threshold == "0.50"


def test_worker_settings_reads_kafka_and_oss_env(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.setenv("KAFKA_TASK_CREATED_TOPIC", "detection.task.created")
    monkeypatch.setenv("KAFKA_TASK_FINISHED_TOPIC", "detection.task.finished")
    monkeypatch.setenv("KAFKA_CONSUMER_GROUP", "doorhandlecatch-python")
    monkeypatch.setenv("ALIYUN_OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
    monkeypatch.setenv("ALIYUN_OSS_BUCKET", "doorhandlecatch")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "test-sk")

    settings = KafkaWorkerSettings.from_env()

    assert settings.kafka_bootstrap_servers == "localhost:9092"
    assert settings.task_created_topic == "detection.task.created"
    assert settings.task_finished_topic == "detection.task.finished"
    assert settings.consumer_group == "doorhandlecatch-python"
    assert settings.oss_bucket == "doorhandlecatch"


def test_oss_result_uploader_preserves_relative_paths_and_writes_json():
    class FakeBucket:
        def __init__(self):
            self.objects = {}

        def put_object(self, key, body):
            self.objects[key] = body

    bucket = FakeBucket()
    uploader = OssResultUploader(bucket)
    image = Image.new("RGB", (2, 2), color="red")

    result_prefix, result_json_key, preview_keys = uploader.upload_detection_results(
        "detection/2026-05-20/上海/张三/设备A/task/Result/",
        [
            (
                "车间A/img001.jpg",
                image,
                {
                    "fileName": "img001.jpg",
                    "detections": [{"label": "Normal", "score": 0.98, "box": [0, 0, 1, 1]}],
                },
            )
        ],
        {"bsgxx_count": 1, "no_detection_images": 0},
    )

    assert result_prefix.endswith("/Result/")
    assert result_json_key.endswith("/Result/detection_results.json")
    assert preview_keys == ["detection/2026-05-20/上海/张三/设备A/task/Result/车间A/img001.jpg"]

    payload = json.loads(bucket.objects[result_json_key].decode("utf-8"))
    assert payload["results"][0]["relativePath"] == "车间A/img001.jpg"
    assert payload["results"][0]["fileName"] == "img001.jpg"


def test_process_created_event_reads_originals_and_builds_finished_event():
    class FakeObject:
        def __init__(self, content):
            self._content = content

        def read(self):
            return self._content

    class FakeBucket:
        def __init__(self, objects):
            self.objects = dict(objects)

        def get_object(self, key):
            return FakeObject(self.objects[key])

        def put_object(self, key, body):
            self.objects[key] = body

    source_key = "detection/2026-05-20/上海/张三/设备A/批次A/Original/车间A/img001.jpg"
    image = Image.new("RGB", (2, 2), color="blue")
    image_buffer = BytesIO()
    image.save(image_buffer, format="JPEG")
    bucket = FakeBucket({source_key: image_buffer.getvalue()})

    event = DetectionTaskCreatedEvent.from_dict(
        {
            "eventId": "evt-created-001",
            "eventType": "DETECTION_TASK_CREATED",
            "eventTime": "2026-05-20T16:10:00+08:00",
            "taskId": "det_20260520_xxx",
            "dispatchId": "dispatch-process",
            "bucketName": "doorhandlecatch",
            "sourcePrefix": "detection/2026-05-20/上海/张三/设备A/批次A/Original/",
            "originalKeys": [source_key],
            "captureInfo": {
                "captureDate": "2026-05-20",
                "region": "上海",
                "collector": "张三",
                "deviceName": "设备A",
            },
            "modelId": 7,
            "threshold": "0.50",
        }
    )

    def fake_detector(image_bytes, threshold):
        assert threshold == 0.5
        assert image_bytes
        return Image.new("RGB", (2, 2), color="green"), [{"label": "Normal", "score": 0.88, "box": [0, 0, 1, 1]}]

    finished = process_created_event(event, bucket, fake_detector)

    assert finished.status == "COMPLETED"
    assert finished.dispatch_id == "dispatch-process"
    assert "dispatch-process" in finished.event_id
    assert finished.total_images == 1
    assert finished.successful_images == 1
    assert finished.failed_images == 0
    assert finished.result_json_key.endswith("/Result/detection_results.json")
    assert finished.preview_keys == ["detection/2026-05-20/上海/张三/设备A/批次A/Result/车间A/img001.jpg"]
    assert finished.statistics["classCounts"] == {
        "Normal": 1,
        "Bent": 0,
        "Deformed": 0,
        "Rusty": 0,
        "Missing": 0,
        "Compromised": 0,
    }


def test_process_created_event_uses_capitalized_compromised_class_name():
    class FakeObject:
        def __init__(self, content):
            self._content = content

        def read(self):
            return self._content

    class FakeBucket:
        def __init__(self, objects):
            self.objects = dict(objects)

        def get_object(self, key):
            return FakeObject(self.objects[key])

        def put_object(self, key, body):
            self.objects[key] = body

    source_key = "detection/2026-05-20/上海/张三/设备A/批次A/Original/车间A/img001.jpg"
    image = Image.new("RGB", (2, 2), color="blue")
    image_buffer = BytesIO()
    image.save(image_buffer, format="JPEG")
    bucket = FakeBucket({source_key: image_buffer.getvalue()})

    event = DetectionTaskCreatedEvent.from_dict(
        {
            "eventId": "evt-created-002",
            "eventType": "DETECTION_TASK_CREATED",
            "eventTime": "2026-05-20T16:10:00+08:00",
            "taskId": "det_20260520_yyy",
            "bucketName": "doorhandlecatch",
            "sourcePrefix": "detection/2026-05-20/上海/张三/设备A/批次A/Original/",
            "originalKeys": [source_key],
            "captureInfo": {
                "captureDate": "2026-05-20",
                "region": "上海",
                "collector": "张三",
                "deviceName": "设备A",
            },
            "modelId": 7,
            "threshold": "0.50",
        }
    )

    def fake_detector(image_bytes, threshold):
        assert threshold == 0.5
        assert image_bytes
        return Image.new("RGB", (2, 2), color="green"), [
            {"label": "Deformed", "score": 0.91, "box": [0, 0, 1, 1]},
            {"label": "compromised", "score": 0.73, "box": [0, 0, 1, 1]},
        ]

    finished = process_created_event(event, bucket, fake_detector)

    assert finished.statistics["classCounts"]["Deformed"] == 1
    assert finished.statistics["classCounts"]["Compromised"] == 1
    assert "compromised" not in finished.statistics["classCounts"]
