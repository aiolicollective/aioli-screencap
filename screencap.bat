@echo off
setlocal EnableExtensions
:: ============================================================
::  screencap.bat  --  aioli-screencap: launcher
::  Double-click: opens the interface without a console.
::  "screencap.bat debug": with a console, to see errors.
:: ============================================================
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo  [!] Environment missing: run setup.bat first.
    echo.
    pause
    exit /b 1
)

if /i "%~1"=="debug" (
    ".venv\Scripts\python.exe" "screencap.py"
    pause
    exit /b
)

start "" ".venv\Scripts\pythonw.exe" "screencap.py"
