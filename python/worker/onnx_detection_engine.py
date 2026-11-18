"""DEIM exported inference: named outputs, manifest-bound preprocessing and weights."""
import hashlib
import io
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps


class OnnxDetectionEngine:
    def __init__(self, manifest_path):
        import onnxruntime as ort

        manifest_path = Path(manifest_path).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != 1:
            raise ValueError("Unsupported detection manifest version")
        self.names = manifest["classNames"]
        if self.names != ["Normal", "Bent", "Deformed", "Rusty", "Missing", "Compromised"]:
            raise ValueError("Model classes do not match the six-class business contract")
        self.size = tuple(manifest["inputSize"])
        if self.size != (640, 640):
            raise ValueError("Expected validated 640x640 inference input")
        self.mean = np.asarray(manifest["mean"], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.asarray(manifest["std"], dtype=np.float32).reshape(1, 1, 3)
        if not np.isfinite(self.mean).all() or not np.isfinite(self.std).all() or (self.std <= 0).any():
            raise ValueError("Invalid normalization")
        model_path = (manifest_path.parent / manifest["modelFile"]).resolve()
        if not model_path.is_relative_to(manifest_path.parent):
            raise ValueError("Model must be inside the manifest directory")
        digest = hashlib.sha256()
        with model_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        self.sha256 = digest.hexdigest()
        if self.sha256 != manifest["onnxSha256"]:
            raise ValueError("Model SHA-256 does not match the manifest")
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.getenv("DETECTION_CPU_THREADS", "2"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        inputs = {item.name: item for item in self.session.get_inputs()}
        if set(inputs) != {"images", "orig_target_sizes"}:
            raise ValueError("Expected DEIM images and orig_target_sizes inputs")
        if inputs["images"].type != "tensor(float)" or inputs["orig_target_sizes"].type != "tensor(int64)":
            raise ValueError("Unexpected DEIM input types")
        if {item.name for item in self.session.get_outputs()} != {"labels", "boxes", "scores"}:
            raise ValueError("Expected named DEIM labels, boxes and scores outputs")
        # Validate an actual inference before the Kafka consumer is registered.
        self.predict(Image.new("RGB", self.size), 1.0)

    def prepare(self, image):
        resized = image.resize(self.size, Image.Resampling.BILINEAR)
        pixels = (np.asarray(resized, dtype=np.float32) / np.float32(255.0) - self.mean) / self.std
        return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])

    def predict(self, image, threshold):
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("Detection threshold must be between zero and one")
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        labels, boxes, scores = self.session.run(["labels", "boxes", "scores"], {
            "images": self.prepare(image),
            # Training PostProcessor scales xyxy by [width,height,width,height].
            "orig_target_sizes": np.asarray([[width, height]], dtype=np.int64),
        })
        if labels.ndim != 2 or labels.shape[0] != 1 or scores.shape != labels.shape or boxes.shape != (*labels.shape, 4):
            raise ValueError("Malformed DEIM output shapes")
        if not np.isfinite(boxes).all() or not np.isfinite(scores).all() or not np.isfinite(labels).all():
            raise ValueError("Non-finite detection output")
        if (labels < 0).any() or (labels >= len(self.names)).any() or (labels != labels.astype(np.int64)).any():
            raise ValueError("Detection class index outside the manifest")
        if (scores < 0).any() or (scores > 1).any():
            raise ValueError("Detection scores outside probability range")
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        colors = ["#1677ff", "#f59e0b", "#e85d04", "#a0522d", "#dc2626", "#7c3aed"]
        results = []
        for index in np.argsort(-scores[0], kind="stable"):
            score = float(scores[0, index])
            if score <= threshold:
                continue
            class_id = int(labels[0, index])
            x0, y0, x1, y1 = map(float, boxes[0, index])
            x0, x1 = sorted((max(0., min(width, x0)), max(0., min(width, x1))))
            y0, y1 = sorted((max(0., min(height, y0)), max(0., min(height, y1))))
            if x1 <= x0 or y1 <= y0:
                continue
            name = self.names[class_id]
            draw.rectangle((x0, y0, x1, y1), outline=colors[class_id], width=max(2, round((width+height)/600)))
            draw.text((x0, max(0, y0-13)), f"{name} {score:.2f}", fill=colors[class_id])
            results.append({"label": name, "score": score, "box": [x0, y0, x1, y1]})
        return annotated, results

    def detect_bytes(self, content, threshold):
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Image exceeds the inference pixel limit")
            return self.predict(image, threshold)


_engine = None


def ensure_model_loaded():
    global _engine
    if _engine is None:
        _engine = OnnxDetectionEngine(os.environ["DETECTION_MODEL_MANIFEST"])
    return _engine


def run_detection_on_image_bytes(content, threshold=0.5):
    return ensure_model_loaded().detect_bytes(content, threshold)
