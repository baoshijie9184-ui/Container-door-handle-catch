"""Private container readiness file. Contains no credentials or image content."""
import json
import os
import time
from pathlib import Path


def write_health(ready, model_id=None):
    target = Path(os.getenv("DETECTION_HEALTH_FILE", "/tmp/doorhandle-worker-health.json"))
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"ready":ready, "modelId":model_id, "checkedAt":time.time()}), encoding="utf-8")
    temporary.replace(target)


def healthy():
    try:
        value = json.loads(Path(os.getenv("DETECTION_HEALTH_FILE", "/tmp/doorhandle-worker-health.json")).read_text(encoding="utf-8"))
        age = time.time() - value["checkedAt"]
        return value["ready"] is True and 0 <= age < 45
    except (OSError, ValueError, KeyError, TypeError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
