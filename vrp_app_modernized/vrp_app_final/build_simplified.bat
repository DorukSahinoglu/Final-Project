@echo off
setlocal
cd /d "%~dp0.."
pyinstaller --noconfirm --onefile --windowed --name "VRP_App_Simplified" --paths "%cd%" --add-data "research\algorithms\Bloodhound_Optimizer_VRP;research\algorithms" vrp_app_final\main_simplified.py
endlocal
