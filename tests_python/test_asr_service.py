import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

from asr_service import create_app, load_model


class FakeWhisperModel:
    def __init__(self, text="查询质检队列"):
        self.text = text
        self.calls = []
        self.audio_path = None

    def transcribe(self, audio_path, **kwargs):
        self.audio_path = Path(audio_path)
        self.calls.append(kwargs)
        return iter([SimpleNamespace(text=self.text)]), SimpleNamespace(language="zh")


def test_load_model_blocks_unused_torch_import(monkeypatch):
    observed_torch_modules = []
    fake_module = ModuleType("faster_whisper")

    def whisper_model(*args, **kwargs):
        observed_torch_modules.append(sys.modules.get("torch", "missing"))
        return SimpleNamespace(args=args, kwargs=kwargs)

    fake_module.WhisperModel = whisper_model
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    model = load_model()

    assert observed_torch_modules == [None]
    assert model.args == ("base",)
    assert model.kwargs == {"device": "cpu", "compute_type": "int8"}


def test_health_reports_loaded_model():
    model = FakeWhisperModel()
    load_calls = []

    def load_model():
        load_calls.append(True)
        return model

    with TestClient(create_app(model_loader=load_model)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "model": "base", "device": "cpu"}
    assert len(load_calls) == 1


def test_transcribe_uses_chinese_vad_and_removes_temporary_file():
    model = FakeWhisperModel(text=" 查询质检队列 ")

    with TestClient(create_app(model_loader=lambda: model)) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("voice.webm", b"browser-audio", "audio/webm;codecs=opus")},
            data={"language": "zh"},
        )

    assert response.status_code == 200
    assert response.json() == {"text": "查询质检队列"}
    assert model.calls[0]["language"] == "zh"
    assert model.calls[0]["vad_filter"] is True
    assert "工业缺陷检测" in model.calls[0]["initial_prompt"]
    assert "质检队列" in model.calls[0]["hotwords"]
    assert model.audio_path.suffix == ".webm"
    assert not model.audio_path.exists()


def test_transcribe_rejects_empty_upload():
    with TestClient(create_app(model_loader=FakeWhisperModel)) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("voice.wav", b"", "audio/wav")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "语音文件不能为空"


def test_transcribe_rejects_upload_larger_than_limit():
    with TestClient(
        create_app(model_loader=FakeWhisperModel, max_upload_bytes=4)
    ) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("voice.wav", b"12345", "audio/wav")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "语音文件过大"


def test_health_returns_unavailable_when_model_loading_fails():
    def fail_to_load():
        raise RuntimeError("model unavailable")

    with TestClient(create_app(model_loader=fail_to_load)) as client:
        response = client.get("/health")
        transcribe_response = client.post(
            "/transcribe",
            files={"file": ("voice.wav", b"audio", "audio/wav")},
        )

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert transcribe_response.status_code == 503
