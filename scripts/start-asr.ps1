param(
    [int] $Port = 9001
)

$ErrorActionPreference = 'Stop'
throw 'Local runtime/test execution is retired. Use script/jenkins/verify-ecs.py on the admitted ECS; local machines edit/build only.'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $env:ASR_MODEL) {
    $env:ASR_MODEL = 'base'
}
if (-not $env:ASR_DEVICE) {
    $env:ASR_DEVICE = 'cpu'
}
if (-not $env:ASR_COMPUTE_TYPE) {
    $env:ASR_COMPUTE_TYPE = 'int8'
}

Write-Host "Starting local ASR on http://127.0.0.1:$Port ..."
Write-Host "ASR_MODEL=$env:ASR_MODEL ASR_DEVICE=$env:ASR_DEVICE ASR_COMPUTE_TYPE=$env:ASR_COMPUTE_TYPE"

& .\scripts\run-python.ps1 -m uvicorn asr_service:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
