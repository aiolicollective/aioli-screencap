@echo off
setlocal EnableExtensions
:: ============================================================
::  screencap.bat  --  aioli-screencap : lanceur
::  Double-clic : ouvre l'interface sans console.
::  "screencap.bat debug" : avec console, pour voir les erreurs.
:: ============================================================
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo  [!] Environnement absent : lance d'abord setup.bat.
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
