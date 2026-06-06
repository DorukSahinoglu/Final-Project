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

echo Starting PulseRoute desktop development stack...
echo This will start backend, frontend, and the Electron shell from one command.
start "PulseRoute Desktop" cmd /k cd /d "%DESKTOP%" ^&^& npm run dev

exit /b 0
