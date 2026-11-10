@echo off
rem Runs Extractor from source. The project venv has pywebview for the native window;
rem plain Python falls back to an Edge app window.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
) else (
  start "" pythonw "%~dp0app.py"
)
