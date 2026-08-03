@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [HATA] Once windows\kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
)

if not exist "logs" mkdir logs

echo ============================================
echo   Crypto Intelligence baslatiliyor
echo ============================================
echo.
echo   1/3  Likidasyon toplayici...
start "Kripto - Likidasyon Toplayici" /min .venv\Scripts\python.exe run.py collect

echo   2/3  Zamanlayici ^(saatlik tarama + alarmlar^)...
start "Kripto - Zamanlayici" /min .venv\Scripts\python.exe run.py watch

timeout /t 3 /nobreak >nul
echo   3/3  Panel...
echo.
echo   Toplayici ve zamanlayici ayri pencerelerde ^(simge durumunda^) calisiyor.
echo   Kapatmak icin o pencereleri de kapatin.
echo.

.venv\Scripts\python.exe run.py serve --lan
pause
