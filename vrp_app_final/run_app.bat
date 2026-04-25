@echo off
setlocal
cd /d "%~dp0.."

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m vrp_app_final
    goto :eof
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -m vrp_app_final
    goto :eof
)

python -m vrp_app_final
endlocal
