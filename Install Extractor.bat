@echo off
rem Installs (or updates) Extractor for this Windows user, then opens it.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" -Launch %*
if errorlevel 1 (
  echo.
  echo Installation failed. See the message above.
  pause
  exit /b 1
)
timeout /t 3 >nul
