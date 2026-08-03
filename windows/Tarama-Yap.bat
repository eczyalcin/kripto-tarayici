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

.venv\Scripts\python.exe run.py scan %*
echo.
pause
