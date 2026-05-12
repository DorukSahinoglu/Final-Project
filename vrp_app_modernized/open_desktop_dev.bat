@echo off
setlocal

cd /d "%~dp0desktop"

if not exist "node_modules" (
  echo Installing desktop dependencies...
  call npm install
  if errorlevel 1 (
    echo Desktop dependency install failed.
    pause
    exit /b 1
  )
)

echo Starting PulseRoute desktop development shell...
call npm run dev
