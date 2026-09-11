param(
    [switch] $ContinueOnError
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$env:APP_BUSINESS_SEED_ENABLED = 'true'
if (-not $env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL) {
    $env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL = 'http://127.0.0.1:9001/transcribe'
}
if (-not $env:CHAT_ASSISTANT_VOICE_READ_TIMEOUT_MS) {
    $env:CHAT_ASSISTANT_VOICE_READ_TIMEOUT_MS = '30000'
}
if ($ContinueOnError) {
    $env:APP_BUSINESS_SEED_CONTINUE_ON_ERROR = 'true'
}

Write-Host 'Starting DoorHandleCatch backend with business seed data enabled...'
Write-Host 'APP_BUSINESS_SEED_ENABLED=true'
Write-Host "CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL=$env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL"
if ($ContinueOnError) {
    Write-Host 'APP_BUSINESS_SEED_CONTINUE_ON_ERROR=true'
}

& .\mvnw.cmd spring-boot:run
