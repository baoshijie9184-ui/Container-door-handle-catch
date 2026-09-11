from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DetectionTaskEventCaptureInfo:
    capture_date: str
    region: str
    collector: str
    device_name: str
    image_folder_name: str

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "DetectionTaskEventCaptureInfo":
        data = payload or {}
        return cls(
            capture_date=str(data.get("captureDate", "")),
            region=str(data.get("region", "")),
            collector=str(data.get("collector", "")),
            device_name=str(data.get("deviceName", "")),
            image_folder_name=str(data.get("imageFolderName", "")),
        )


@dataclass
class DetectionTaskCreatedEvent:
    event_id: str
    event_type: str
    event_time: str
    task_id: str
    dispatch_id: str
    bucket_name: str
    source_prefix: str
    original_keys: List[str] = field(default_factory=list)
    capture_info: DetectionTaskEventCaptureInfo = field(
        default_factory=lambda: DetectionTaskEventCaptureInfo("", "", "", "", "")
    )
    model_id: Optional[int] = None
    threshold: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DetectionTaskCreatedEvent":
        return cls(
            event_id=str(payload.get("eventId", "")),
            event_type=str(payload.get("eventType", "")),
            event_time=str(payload.get("eventTime", "")),
            task_id=str(payload.get("taskId", "")),
            dispatch_id=str(payload.get("dispatchId", "")),
            bucket_name=str(payload.get("bucketName", "")),
            source_prefix=str(payload.get("sourcePrefix", "")),
            original_keys=[str(item) for item in payload.get("originalKeys", [])],
            capture_info=DetectionTaskEventCaptureInfo.from_dict(payload.get("captureInfo")),
            model_id=payload.get("modelId"),
            threshold=None if payload.get("threshold") is None else str(payload.get("threshold")),
        )


@dataclass
class DetectionTaskFinishedEvent:
    event_id: str
    event_type: str
    event_time: str
    task_id: str
    dispatch_id: str
    status: str
    result_oss_prefix: str
    result_json_key: str
    preview_keys: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    defect_evidence: List[Dict[str, Any]] = field(default_factory=list)
    total_images: int = 0
    successful_images: int = 0
    failed_images: int = 0
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "eventTime": self.event_time,
            "taskId": self.task_id,
            "dispatchId": self.dispatch_id,
            "status": self.status,
            "resultOssPrefix": self.result_oss_prefix,
            "resultJsonKey": self.result_json_key,
            "previewKeys": self.preview_keys,
            "statistics": self.statistics,
            "defectEvidence": self.defect_evidence,
            "totalImages": self.total_images,
            "successfulImages": self.successful_images,
            "failedImages": self.failed_images,
            "errorMessage": self.error_message,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }
