@echo off
setlocal
cd /d "%~dp0.."
pyinstaller --noconfirm --onefile --windowed --name "VRP_App_Simplified" --paths "%cd%" --add-data "app_algorithms\bloodhoundtest3_for_app.py;app_algorithms" --add-data "app_algorithms\NSGA_2_BETTER;app_algorithms" vrp_app_final\main_simplified.py
endlocal
