@echo off
where pwsh.exe >nul 2>nul
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" %*
) else (
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1" %*
)
if errorlevel 1 (
  echo Local service startup failed. Read the output and project work\middlewares logs.
  pause
  exit /b 1
)
