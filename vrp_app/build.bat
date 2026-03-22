@echo off
echo ============================================
echo  VRP NSGA-II - .exe Olusturucu
echo ============================================
echo.

REM Python kurulu mu kontrol et
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi! Python 3.8+ yukleyin.
    pause
    exit /b 1
)

echo [1/3] PyInstaller kuruluyor...
pip install pyinstaller --quiet

echo [2/3] .exe olusturuluyor (bu birkaç dakika sürebilir)...
pyinstaller --onefile --windowed --name "VRP_Optimizer" ^
    --add-data "default_data.py;." ^
    --add-data "vrp_algorithm.py;." ^
    main.py

echo [3/3] Temizlik yapiliyor...
rmdir /s /q build >nul 2>&1
del VRP_Optimizer.spec >nul 2>&1

echo.
echo ============================================
echo  TAMAMLANDI!
echo  Dosya: dist\VRP_Optimizer.exe
echo ============================================
pause
