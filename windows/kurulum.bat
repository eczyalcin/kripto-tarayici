@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0.."

echo ============================================
echo   Crypto Intelligence - Windows Kurulumu
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi.
    echo.
    echo Once Python 3.11 veya uzerini kurun:
    echo   https://www.python.org/downloads/
    echo Kurulum sirasinda "Add python.exe to PATH" kutusunu MUTLAKA isaretleyin.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Bulunan Python surumu: %PYVER%
echo.

if exist ".venv\Scripts\python.exe" (
    echo Sanal ortam zaten var, paketler guncelleniyor...
) else (
    echo Sanal ortam olusturuluyor...
    python -m venv .venv
    if errorlevel 1 (
        echo [HATA] Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )
)

echo Paketler kuruluyor ^(birkac dakika surebilir^)...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [HATA] Paket kurulumu basarisiz.
    pause
    exit /b 1
)

echo.
echo Baglanti testi yapiliyor...
.venv\Scripts\python.exe run.py check

echo.
echo ============================================
echo   Kurulum tamamlandi
echo ============================================
echo.
echo   Tarama yapmak icin  : Tarama-Yap.bat
echo   Paneli acmak icin   : Panel-Ac.bat
echo   Tum sistemi baslat  : Sistemi-Baslat.bat
echo.
pause
