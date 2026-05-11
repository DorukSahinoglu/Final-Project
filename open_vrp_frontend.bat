@echo off
setlocal

set "APP_DIR=%~dp0vrp-frontend"

if not exist "%APP_DIR%\package.json" (
  echo vrp-frontend folder not found.
  pause
  exit /b 1
)

cd /d "%APP_DIR%"

if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 (
    echo Dependency install failed.
    pause
    exit /b 1
  )
)

echo Starting PulseRoute OS frontend...
start "" http://localhost:5173
call npm run dev
