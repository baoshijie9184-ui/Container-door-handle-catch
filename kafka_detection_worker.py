import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()

from kafka_event_models import DetectionTaskCreatedEvent, DetectionTaskFinishedEvent
from kafka_settings import KafkaWorkerSettings
from oss_result_uploader import OssResultUploader

DetectionFunction = Callable[[bytes, float], Tuple[Any, List[Dict[str, Any]]]]


def create_oss_bucket(settings: KafkaWorkerSettings) -> Any:
    import oss2

    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)


def default_detector(image_bytes: bytes, threshold: float) -> Tuple[Any, List[Dict[str, Any]]]:
    from detection_engine import run_detection_on_image_bytes

    return run_detection_on_image_bytes(image_bytes, threshold)


def build_result_prefix(source_prefix: str) -> str:
    if "/originals/" in source_prefix:
        return source_prefix.replace("/originals/", "/Result/")
    if "/Original/" in source_prefix:
        return source_prefix.replace("/Original/", "/Result/")
    if source_prefix.endswith("/"):
        return f"{source_prefix}Result/"
    return f"{source_prefix}/Result/"


def extract_relative_path(source_prefix: str, object_key: str) -> str:
    if object_key.startswith(source_prefix):
        return object_key[len(source_prefix):]
    return object_key.rsplit("/", 1)[-1]


def build_single_image_result(per_image_results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if len(per_image_results) != 1:
        return None
    detections = per_image_results[0].get("detections", [])
    if not detections:
        return None
    top_detection = max(
        detections,
        key=lambda item: float(item.get("confidence", item.get("score", 0.0)) or 0.0),
    )
    confidence = top_detection.get("confidence", top_detection.get("score"))
    category = str(
        top_detection.get("defectType")
        or top_detection.get("label")
        or top_detection.get("category")
        or ""
    ).strip()
    if not category or confidence is None:
        return None
    return {"category": category, "confidence": float(confidence)}


def build_statistics(per_image_results: List[Dict[str, Any]], failed_images: int) -> Dict[str, Any]:
    class_counts = {
        "Normal": 0,
        "Bent": 0,
        "Deformed": 0,
        "Rusty": 0,
        "Missing": 0,
        "Compromised": 0,
    }
    statistics = {
        "classCounts": class_counts,
        "noDetectionImages": 0,
        "missDetectionRate": 0.0,
    }
    for result in per_image_results:
        detections = result.get("detections", [])
        if not detections:
            statistics["noDetectionImages"] += 1
            continue
        for detection in detections:
            label = str(detection.get("label", "")).strip()
            normalized = label.lower()
            if normalized == "normal":
                class_counts["Normal"] += 1
            elif normalized == "bent":
                class_counts["Bent"] += 1
            elif normalized == "deformed":
                class_counts["Deformed"] += 1
            elif normalized == "rusty":
                class_counts["Rusty"] += 1
            elif normalized == "missing":
                class_counts["Missing"] += 1
            elif normalized == "compromised":
                class_counts["Compromised"] += 1

    total_images = len(per_image_results) + failed_images
    if total_images > 0:
        statistics["missDetectionRate"] = statistics["noDetectionImages"] / total_images
    single_image_result = build_single_image_result(per_image_results)
    if single_image_result is not None:
        statistics["singleImageResult"] = single_image_result
    return statistics


def build_defect_evidence(per_image_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for result in per_image_results:
        image_name = str(result.get("fileName", ""))
        source_key = str(result.get("sourceKey", ""))
        preview_key = str(result.get("previewKey", ""))
        for detection in result.get("detections", []):
            label = str(detection.get("defectType") or detection.get("label") or detection.get("category") or "").strip()
            if not label or label.lower() == "normal":
                continue
            bbox = detection.get("bbox") or detection.get("box") or {}
            confidence = detection.get("confidence", detection.get("score"))
            area = detection.get("area")
            if area is None and isinstance(bbox, dict):
                width = float(bbox.get("width") or bbox.get("w") or 0)
                height = float(bbox.get("height") or bbox.get("h") or 0)
                area = width * height
            elif area is None and isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                area = abs(float(bbox[2]) - float(bbox[0])) * abs(float(bbox[3]) - float(bbox[1]))
            evidence.append(
                {
                    "imageName": image_name,
                    "sourceKey": source_key,
                    "previewKey": preview_key,
                    "defectType": label,
                    "confidence": confidence,
                    "area": area,
                    "positionRegion": str(detection.get("positionRegion") or detection.get("region") or "UNKNOWN").upper(),
                    "severityLevel": str(detection.get("severityLevel") or detection.get("severity") or "MINOR").upper(),
                    "bbox": bbox,
                }
            )
    return evidence


def build_finished_event(
    task: DetectionTaskCreatedEvent,
    result_json_key: str,
    preview_keys: List[str],
    statistics: Dict[str, Any],
    defect_evidence: List[Dict[str, Any]],
    successful_images: int,
    failed_images: int,
    started_at: str,
    error_message: Optional[str] = None,
) -> DetectionTaskFinishedEvent:
    now = datetime.now(timezone.utc).astimezone().isoformat()
    status = "COMPLETED"
    if successful_images == 0 and failed_images > 0:
        status = "FAILED"
    elif failed_images > 0:
        status = "PARTIAL_FAILED"

    return DetectionTaskFinishedEvent(
        event_id=f"{task.task_id}-{task.dispatch_id}-finished",
        event_type="DETECTION_TASK_FINISHED",
        event_time=now,
        task_id=task.task_id,
        dispatch_id=task.dispatch_id,
        status=status,
        result_oss_prefix=result_json_key.rsplit("/", 1)[0] + "/",
        result_json_key=result_json_key,
        preview_keys=preview_keys,
        statistics=statistics,
        defect_evidence=defect_evidence,
        total_images=len(task.original_keys),
        successful_images=successful_images,
        failed_images=failed_images,
        error_message=error_message,
        started_at=started_at,
        finished_at=now,
    )


def serialize_finished_event(event: DetectionTaskFinishedEvent) -> str:
    return json.dumps(event.to_dict(), ensure_ascii=False)


def load_settings() -> KafkaWorkerSettings:
    return KafkaWorkerSettings.from_env()


def parse_created_event(message_value: str) -> DetectionTaskCreatedEvent:
    payload: Dict[str, Any] = json.loads(message_value)
    return DetectionTaskCreatedEvent.from_dict(payload)


def process_created_event(
    task: DetectionTaskCreatedEvent,
    bucket: Any,
    detect_image_bytes: DetectionFunction,
) -> DetectionTaskFinishedEvent:
    uploader = OssResultUploader(bucket)
    threshold = float(task.threshold) if task.threshold is not None else 0.5
    started_at = datetime.now(timezone.utc).astimezone().isoformat()
    per_image_upload_items = []
    per_image_results = []
    failures: List[str] = []

    for object_key in task.original_keys:
        relative_path = extract_relative_path(task.source_prefix, object_key)
        try:
            image_bytes = bucket.get_object(object_key).read()
            annotated_image, detections = detect_image_bytes(image_bytes, threshold)
            detection_payload = {
                "fileName": relative_path.rsplit("/", 1)[-1],
                "sourceKey": object_key,
                "detections": detections,
            }
            per_image_upload_items.append((relative_path, annotated_image, detection_payload))
            per_image_results.append(detection_payload)
        except Exception as exc:
            failures.append(f"{relative_path}: {exc}")

    statistics = build_statistics(per_image_results, len(failures))
    statistics["totalImages"] = len(task.original_keys)
    statistics["successfulImages"] = len(per_image_results)
    statistics["failedImages"] = len(failures)
    defect_evidence = build_defect_evidence(per_image_results)
    statistics["defectCount"] = len(defect_evidence)

    result_prefix = build_result_prefix(task.source_prefix)
    error_message = "; ".join(failures[:3]) if failures else None

    try:
        _, result_json_key, preview_keys = uploader.upload_detection_results(
            result_prefix,
            per_image_upload_items,
            {
                "taskId": task.task_id,
                "captureInfo": {
                    "captureDate": task.capture_info.capture_date,
                    "region": task.capture_info.region,
                    "collector": task.capture_info.collector,
                    "deviceName": task.capture_info.device_name,
                    "imageFolderName": task.capture_info.image_folder_name,
                },
                "statistics": statistics,
                "errors": failures,
            },
        )
        for index, preview_key in enumerate(preview_keys):
            if index < len(per_image_results):
                per_image_results[index]["previewKey"] = preview_key
        defect_evidence = build_defect_evidence(per_image_results)
        statistics["defectCount"] = len(defect_evidence)
    except Exception as upload_exc:
        # OSS 上传失败：标记任务为 FAILED，确保不会卡在 PROCESSING
        error_message = (error_message + "; " if error_message else "") + f"结果上传失败: {upload_exc}"
        return build_finished_event(
            task,
            "",       # result_json_key
            [],       # preview_keys
            statistics,
            defect_evidence,
            len(per_image_results),
            len(task.original_keys),  # 全部标记为失败
            started_at,
            error_message,
        )

    return build_finished_event(
        task,
        result_json_key,
        preview_keys,
        statistics,
        defect_evidence,
        len(per_image_results),
        len(failures),
        started_at,
        error_message,
    )


def process_task_message(
    message_value: str,
    bucket: Any,
    detect_image_bytes: DetectionFunction,
) -> str:
    task = parse_created_event(message_value)
    return serialize_finished_event(process_created_event(task, bucket, detect_image_bytes))


def publish_finished_and_commit(
    producer: Any,
    consumer: Any,
    source_message: Any,
    topic: str,
    key: bytes,
    payload: bytes,
    timeout_seconds: float,
) -> None:
    delivery = {"completed": False, "error": None}

    def on_delivery(error: Any, _message: Any) -> None:
        delivery["completed"] = True
        delivery["error"] = error

    producer.produce(topic, key=key, value=payload, callback=on_delivery)
    remaining = producer.flush(timeout_seconds)
    if remaining != 0 or not delivery["completed"] or delivery["error"] is not None:
        reason = delivery["error"] if delivery["error"] is not None else remaining
        raise RuntimeError(f"finished event delivery failed: {reason}")
    consumer.commit(message=source_message)


def run_worker() -> None:
    from confluent_kafka import Consumer, Producer

    settings = load_settings()
    settings.validate()
    bucket = create_oss_bucket(settings)
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": settings.consumer_group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})

    consumer.subscribe([settings.task_created_topic])

    try:
        while True:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise RuntimeError(str(message.error()))

            task = parse_created_event(message.value().decode("utf-8"))
            finished_payload = serialize_finished_event(
                process_created_event(task, bucket, default_detector)
            )
            publish_finished_and_commit(
                producer,
                consumer,
                source_message=message,
                topic=settings.task_finished_topic,
                key=message.key() or task.task_id.encode("utf-8"),
                payload=finished_payload.encode("utf-8"),
                timeout_seconds=settings.delivery_timeout_seconds,
            )
    finally:
        consumer.close()


if __name__ == "__main__":
    run_worker()
