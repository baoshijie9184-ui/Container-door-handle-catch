import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool


LOGGER = logging.getLogger("doorhandlecatch.asr")
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".webm", ".wav", ".mp3", ".mp4", ".ogg", ".m4a"}
CONTENT_TYPE_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
}
INDUSTRIAL_PROMPT = (
    "集装箱门把手，工业缺陷检测，质检队列，工单追溯，批次追溯，"
    "缺陷证据，模型管理，设备管理"
)
INDUSTRIAL_HOTWORDS = (
    "质检 质检队列 工业缺陷检测 集装箱门把手 工单追溯 批次追溯 "
    "缺陷证据 模型管理 设备管理"
)


def load_model():
    # faster-whisper does not need PyTorch; blocking that optional import avoids
    # duplicate Intel OpenMP runtimes in the shared leetcode Conda environment.
    sys.modules.setdefault("torch", None)
    from faster_whisper import WhisperModel

    return WhisperModel(
        os.getenv("ASR_MODEL", "base"),
        device=os.getenv("ASR_DEVICE", "cpu"),
        compute_type=os.getenv("ASR_COMPUTE_TYPE", "int8"),
    )


def _safe_suffix(file: UploadFile) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return suffix
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_SUFFIXES.get(content_type, ".bin")


def _transcribe_file(model, audio_path: str, language: str) -> str:
    segments, _ = model.transcribe(
        audio_path,
        language=language,
        vad_filter=True,
        initial_prompt=INDUSTRIAL_PROMPT,
        hotwords=INDUSTRIAL_HOTWORDS,
    )
    return "".join(segment.text for segment in segments).strip()


def create_app(
    model_loader: Callable = load_model,
    max_upload_bytes: int | None = None,
) -> FastAPI:
    upload_limit = max_upload_bytes or int(
        os.getenv("ASR_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    )
    model_name = os.getenv("ASR_MODEL", "base")
    device = os.getenv("ASR_DEVICE", "cpu")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model = None
        app.state.model_error = None
        try:
            app.state.model = await run_in_threadpool(model_loader)
            LOGGER.info("ASR model loaded: model=%s device=%s", model_name, device)
        except Exception as exc:
            app.state.model_error = str(exc)
            LOGGER.exception("ASR model initialization failed")
        yield

    application = FastAPI(title="DoorHandleCatch Local ASR", lifespan=lifespan)

    @application.get("/health")
    async def health():
        if application.state.model is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "model": model_name, "device": device},
            )
        return {"status": "ready", "model": model_name, "device": device}

    @application.post("/transcribe")
    async def transcribe(
        file: UploadFile = File(...),
        language: str = Form(default="zh"),
    ):
        if application.state.model is None:
            raise HTTPException(status_code=503, detail="语音识别模型尚未就绪")

        audio = await file.read(upload_limit + 1)
        if not audio:
            raise HTTPException(status_code=400, detail="语音文件不能为空")
        if len(audio) > upload_limit:
            raise HTTPException(status_code=400, detail="语音文件过大")

        descriptor, temp_path = tempfile.mkstemp(suffix=_safe_suffix(file))
        try:
            with os.fdopen(descriptor, "wb") as temp_file:
                temp_file.write(audio)
            text = await run_in_threadpool(
                _transcribe_file,
                application.state.model,
                temp_path,
                language if language == "zh" else "zh",
            )
            return {"text": text}
        finally:
            Path(temp_path).unlink(missing_ok=True)

    return application


app = create_app()
