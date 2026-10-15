@echo off
where pwsh.exe >nul 2>nul
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-local.ps1" %*
) else (
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-local.ps1" %*
)
if errorlevel 1 (
  echo Local service stop failed. Read the output above.
  pause
  exit /b 1
)
