@echo off
setlocal EnableExtensions DisableDelayedExpansion
:: ============================================================
::  setup.bat  --  aioli-screencap: installation
::
::  Everything is installed in this folder (.venv\). Nothing is
::  written anywhere else: no global pip, no pip cache, no
::  shortcut, no registry.
::  Deleting the folder = uninstalling.
:: ============================================================

:: Always work in the script folder, even when started from
:: somewhere else (otherwise the venv lands anywhere).
cd /d "%~dp0" || (
    echo  [ERROR] Cannot open the script folder.
    pause
    exit /b 1
)
title aioli-screencap - installation

echo.
echo ============================================================
echo   aioli-screencap  ^|  Installation
echo ============================================================
echo   Folder : "%CD%"
echo.

:: -- Refuse administrator rights ----------------------------
::  Not needed here, and files created as admin could not be
::  modified later by your normal account.
net session >nul 2>&1
if not errorlevel 1 (
    echo  [ERROR] This script is running as administrator.
    echo          Close this window and start setup.bat again with a plain double-click.
    echo.
    pause
    exit /b 1
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    echo  [INFO] .venv already present: updating the dependencies.
    echo.
    goto :install_deps
)

:: -- Looking for Python ---------------------------------------
::  We get the real path of python.exe (sys.executable).
::  The Microsoft Store "python" alias returns nothing: ignored.
set "PYEXE="
call :probe py -3.12
if not defined PYEXE call :probe py -3
if not defined PYEXE call :probe python
if defined PYEXE goto :check_python

echo  [!] Python could not be found automatically.
echo.
echo  Paste the full path of python.exe
echo  Example: C:\Users\You\AppData\Local\Programs\Python\Python312\python.exe
echo.
set /p "PYEXE=  Path > "
if not defined PYEXE (
    echo  [ERROR] No path entered.
    pause
    exit /b 1
)
set "PYEXE=%PYEXE:"=%"

:check_python
if not exist "%PYEXE%" (
    echo  [ERROR] File not found: "%PYEXE%"
    pause
    exit /b 1
)
"%PYEXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
    echo  [ERROR] Python 3.9 or newer is required. Python 3.12 is recommended.
    pause
    exit /b 1
)
"%PYEXE%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] tkinter is missing from this Python: the interface cannot open.
    echo          Run the Python installer again, choose "Modify" and tick "tcl/tk and IDLE".
    pause
    exit /b 1
)
for /f "delims=" %%V in ('call "%PYEXE%" --version 2^>^&1') do set "PYVER=%%V"
echo  [OK] Python  : "%PYEXE%"
echo       Version : %PYVER%
echo.

:: -- Creating the venv ----------------------------------------
echo  [1/3] Creating .venv ...
"%PYEXE%" -m venv "%~dp0.venv"
if errorlevel 1 (
    echo  [ERROR] Could not create the venv.
    pause
    exit /b 1
)
echo  [OK] .venv created.
echo.

:: -- Dependencies ---------------------------------------------
::  The venv python is called directly (no "activate"):
::  nothing can be installed into the system Python by mistake.
::  --isolated            ignores pip config and environment variables
::  --require-virtualenv  refuses to run outside a venv
::  --no-cache-dir        no cache in %LOCALAPPDATA%
::  --only-binary=:all:   prebuilt packages only: no build code
::                        runs on your machine
:install_deps
set "PIPARGS=--isolated --require-virtualenv --disable-pip-version-check --no-cache-dir --only-binary=:all:"
echo  [2/3] Installing the dependencies (mss, Pillow)...
"%VENV_PY%" -m pip install %PIPARGS% --upgrade pip
if errorlevel 1 echo  [!] Could not update pip, carrying on with the bundled version.
"%VENV_PY%" -m pip install %PIPARGS% -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo  [ERROR] pip could not install the dependencies.
    echo    1. No Internet, or a proxy / firewall blocks pip.
    echo    2. Python too recent: no prebuilt package yet.
    echo       Install Python 3.12, delete the .venv folder, run setup.bat again.
    echo.
    pause
    exit /b 1
)
"%VENV_PY%" -c "import mss, PIL, tkinter"
if errorlevel 1 (
    echo  [ERROR] Check failed: delete .venv and run setup.bat again.
    pause
    exit /b 1
)
echo  [OK] Dependencies installed and checked.
echo.

echo  [3/3] Installation complete.
echo.
echo  To start the tool : double-click screencap.bat
echo  To uninstall      : delete this folder (your captures stay where you saved them).
echo.
set "GO="
set /p "GO=  Start it now? [Enter = yes / n] > "
if /i "%GO%"=="n" exit /b 0
if /i "%GO%"=="no" exit /b 0
if /i "%GO%"=="non" exit /b 0
call "%~dp0screencap.bat"
exit /b 0

:: ------------------------------------------------------------
::  :probe <command...>  -> PYEXE = real path of python.exe
:: ------------------------------------------------------------
:probe
for /f "usebackq delims=" %%I in (`%* -c "import sys; print(sys.executable)" 2^>nul`) do set "PYEXE=%%I"
exit /b 0
