@echo off
setlocal
cd /d "%~dp0.."
pyinstaller --noconfirm --onefile --windowed --name "VRP_App_Final" --paths "%cd%" vrp_app_final\main.py
endlocal
