@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "DESKTOP=%ROOT%desktop"

if not exist "%BACKEND%" (
  echo Backend folder not found.
  pause
  exit /b 1
)

if not exist "%FRONTEND%" (
  echo Frontend folder not found.
  pause
  exit /b 1
)

if not exist "%DESKTOP%" (
  echo Desktop folder not found.
  pause
  exit /b 1
)

cd /d "%FRONTEND%"
if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 (
    echo Frontend dependency install failed.
    pause
    exit /b 1
  )
)

cd /d "%DESKTOP%"
if not exist "node_modules" (
  echo Installing desktop dependencies...
  call npm install
  if errorlevel 1 (
    echo Desktop dependency install failed.
    pause
    exit /b 1
  )
)

echo Starting PulseRoute backend...
start "PulseRoute Backend" cmd /k cd /d "%BACKEND%" ^&^& python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

echo Starting PulseRoute frontend...
start "PulseRoute Frontend" cmd /k cd /d "%FRONTEND%" ^&^& npm run dev

echo Waiting for frontend and backend to boot...
timeout /t 4 /nobreak >nul

echo Starting PulseRoute desktop shell...
start "PulseRoute Desktop" cmd /k cd /d "%DESKTOP%" ^&^& npm run dev

exit /b 0
