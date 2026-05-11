@echo off
setlocal

set "APP_DIR=%~dp0backend"

if not exist "%APP_DIR%\requirements.txt" (
  echo backend folder not found.
  pause
  exit /b 1
)

cd /d "%APP_DIR%"

echo Starting PulseRoute backend on http://127.0.0.1:8000 ...
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
