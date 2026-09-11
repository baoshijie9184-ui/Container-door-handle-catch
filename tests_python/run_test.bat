@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%RUN_LIVE_AGENT_TESTS%"=="1" (
  conda run --no-capture-output -n leetcode python "%~dp0..\scripts\diagnostics\agent_live_smoke.py"
) else (
  conda run --no-capture-output -n leetcode python -m pytest "%~dp0test_asr_service.py" "%~dp0test_kafka_event_models.py" "%~dp0test_kafka_detection_worker.py" "%~dp0test_agent_auth_client.py" -q
)
exit /b %ERRORLEVEL%
