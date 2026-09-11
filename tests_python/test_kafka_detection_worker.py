import pytest

from kafka_detection_worker import (
    build_defect_evidence,
    build_statistics,
    publish_finished_and_commit,
)


class FakeProducer:
    def __init__(self, delivery_error=None, remaining=0, invoke_callback=True):
        self.delivery_error = delivery_error
        self.remaining = remaining
        self.invoke_callback = invoke_callback

    def produce(self, topic, key, value, callback):
        if self.invoke_callback:
            callback(self.delivery_error, object())

    def flush(self, timeout):
        return self.remaining


class FakeConsumer:
    def __init__(self):
        self.committed = []

    def commit(self, message):
        self.committed.append(message)


def test_single_image_statistics_expose_remote_category_and_confidence():
    statistics = build_statistics(
        [{
            "fileName": "door.jpg",
            "detections": [
                {"label": "Bent", "score": 0.73, "box": [10, 20, 60, 80]},
                {"label": "Rusty", "score": 0.91, "box": [15, 25, 70, 95]},
            ],
        }],
        failed_images=0,
    )

    assert statistics["singleImageResult"] == {
        "category": "Rusty",
        "confidence": 0.91,
    }


def test_defect_evidence_accepts_worker_score_and_list_box():
    evidence = build_defect_evidence(
        [{
            "fileName": "door.jpg",
            "sourceKey": "source/door.jpg",
            "previewKey": "result/door.jpg",
            "detections": [
                {"label": "Bent", "score": 0.73, "box": [10, 20, 60, 80]},
            ],
        }]
    )

    assert evidence[0]["confidence"] == 0.73
    assert evidence[0]["area"] == 3000.0


def test_publish_success_commits_source_message():
    producer = FakeProducer()
    consumer = FakeConsumer()

    publish_finished_and_commit(
        producer, consumer, source_message="source", topic="finished",
        key=b"task-1", payload=b"{}", timeout_seconds=2.0,
    )

    assert consumer.committed == ["source"]


def test_delivery_failure_does_not_commit():
    producer = FakeProducer(delivery_error=RuntimeError("broker down"))
    consumer = FakeConsumer()

    with pytest.raises(RuntimeError, match="finished event delivery failed"):
        publish_finished_and_commit(
            producer, consumer, source_message="source", topic="finished",
            key=b"task-1", payload=b"{}", timeout_seconds=2.0,
        )

    assert consumer.committed == []


def test_flush_timeout_does_not_commit():
    producer = FakeProducer(remaining=1, invoke_callback=False)
    consumer = FakeConsumer()

    with pytest.raises(RuntimeError, match="finished event delivery failed"):
        publish_finished_and_commit(
            producer, consumer, source_message="source", topic="finished",
            key=b"task-1", payload=b"{}", timeout_seconds=2.0,
        )

    assert consumer.committed == []
