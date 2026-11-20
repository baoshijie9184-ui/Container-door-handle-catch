import json
from io import BytesIO
from typing import Any, Dict, Iterable, List, Tuple


class OssResultUploader:
    def __init__(self, bucket: Any, write_prefix=None) -> None:
        self.bucket = bucket
        self.write_prefix = write_prefix

    def _put(self, key, content):
        if self.write_prefix and (not self.write_prefix.endswith("/") or not key.startswith(self.write_prefix)
                                  or any(part in (".", "..") for part in key.split("/"))):
            raise ValueError("结果超出已配置的 OSS 写入目录")
        self.bucket.put_object(key, content)

    def upload_preview_image(self, key: str, image: Any) -> str:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=92, subsampling=0)
        self._put(key, buffer.getvalue())
        return key

    def upload_json(self, key: str, payload: Dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._put(key, body)
        return key

    def upload_detection_results(
        self,
        result_prefix: str,
        per_image_results: Iterable[Tuple[str, Any, Dict[str, Any]]],
        summary: Dict[str, Any],
    ) -> Tuple[str, str, List[str]]:
        preview_keys: List[str] = []
        result_items: List[Dict[str, Any]] = []

        for relative_path, annotated_image, detection_payload in per_image_results:
            preview_key = f"{result_prefix}{relative_path}"
            preview_keys.append(self.upload_preview_image(preview_key, annotated_image))
            result_items.append(
                {
                    "relativePath": relative_path,
                    "previewKey": preview_key,
                    **detection_payload,
                }
            )

        result_json_key = f"{result_prefix}detection_results.json"
        self.upload_json(
            result_json_key,
            {
                "summary": summary,
                "results": result_items,
            },
        )
        return result_prefix, result_json_key, preview_keys
