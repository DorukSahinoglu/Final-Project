@echo off
setlocal

cd /d "%~dp0"

if not exist "package.json" (
  echo package.json not found.
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 (
    echo Dependency install failed.
    pause
    exit /b 1
  )
)

echo Opening PulseRoute OS...
start "" http://localhost:5173
call npm run dev
