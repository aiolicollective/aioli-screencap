@echo off
setlocal EnableExtensions DisableDelayedExpansion
:: ============================================================
::  setup.bat  --  aioli-screencap : installation
::
::  Tout est installe dans ce dossier (.venv\). Rien n'est ecrit
::  ailleurs : pas de pip global, pas de cache pip, pas de
::  raccourci, pas de registre.
::  Supprimer le dossier = desinstaller.
:: ============================================================

:: Toujours travailler dans le dossier du script, meme si on est
:: lance depuis ailleurs (sinon le venv atterrit n'importe ou).
cd /d "%~dp0" || (
    echo  [ERREUR] Impossible d'ouvrir le dossier du script.
    pause
    exit /b 1
)
title aioli-screencap - installation

echo.
echo ============================================================
echo   aioli-screencap  ^|  Installation
echo ============================================================
echo   Dossier : "%CD%"
echo.

:: -- Refuse les droits administrateur ------------------------
::  Inutiles ici, et les fichiers crees en admin ne seraient plus
::  modifiables ensuite par ton compte normal.
net session >nul 2>&1
if not errorlevel 1 (
    echo  [ERREUR] Ce script tourne en administrateur.
    echo           Ferme cette fenetre et relance setup.bat par un simple double-clic.
    echo.
    pause
    exit /b 1
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    echo  [INFO] .venv deja present : mise a jour des dependances.
    echo.
    goto :install_deps
)

:: -- Recherche de Python -------------------------------------
::  On recupere le chemin reel de python.exe (sys.executable).
::  L'alias "python" du Microsoft Store ne renvoie rien : ignore.
set "PYEXE="
call :probe py -3.12
if not defined PYEXE call :probe py -3
if not defined PYEXE call :probe python
if defined PYEXE goto :check_python

echo  [!] Python introuvable automatiquement.
echo.
echo  Colle le chemin complet de python.exe
echo  Exemple : C:\Users\Toi\AppData\Local\Programs\Python\Python312\python.exe
echo.
set /p "PYEXE=  Chemin > "
if not defined PYEXE (
    echo  [ERREUR] Aucun chemin saisi.
    pause
    exit /b 1
)
set "PYEXE=%PYEXE:"=%"

:check_python
if not exist "%PYEXE%" (
    echo  [ERREUR] Fichier introuvable : "%PYEXE%"
    pause
    exit /b 1
)
"%PYEXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
    echo  [ERREUR] Python 3.9 minimum requis. Python 3.12 conseille.
    pause
    exit /b 1
)
"%PYEXE%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] tkinter manque dans ce Python : l'interface ne peut pas s'afficher.
    echo           Relance l'installateur de Python, "Modify", et coche "tcl/tk and IDLE".
    pause
    exit /b 1
)
for /f "delims=" %%V in ('call "%PYEXE%" --version 2^>^&1') do set "PYVER=%%V"
echo  [OK] Python  : "%PYEXE%"
echo       Version : %PYVER%
echo.

:: -- Creation du venv ----------------------------------------
echo  [1/3] Creation de .venv ...
"%PYEXE%" -m venv "%~dp0.venv"
if errorlevel 1 (
    echo  [ERREUR] Impossible de creer le venv.
    pause
    exit /b 1
)
echo  [OK] .venv cree.
echo.

:: -- Dependances ---------------------------------------------
::  On appelle directement le python du venv (pas de "activate") :
::  impossible d'installer par erreur dans le Python systeme.
::  --isolated            ignore la config pip et les variables d'env
::  --require-virtualenv  refuse de tourner hors d'un venv
::  --no-cache-dir        pas de cache dans %LOCALAPPDATA%
::  --only-binary=:all:   paquets precompiles uniquement : aucun code
::                        de compilation execute sur ta machine
:install_deps
set "PIPARGS=--isolated --require-virtualenv --disable-pip-version-check --no-cache-dir --only-binary=:all:"
echo  [2/3] Installation des dependances (mss, Pillow)...
"%VENV_PY%" -m pip install %PIPARGS% --upgrade pip
if errorlevel 1 echo  [!] Mise a jour de pip impossible, on continue avec la version fournie.
"%VENV_PY%" -m pip install %PIPARGS% -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo  [ERREUR] pip n'a pas pu installer les dependances.
    echo    1. Pas d'Internet, ou un proxy / pare-feu bloque pip.
    echo    2. Python trop recent : pas encore de paquet precompile.
    echo       Installe Python 3.12, supprime le dossier .venv, relance setup.bat.
    echo.
    pause
    exit /b 1
)
"%VENV_PY%" -c "import mss, PIL, tkinter"
if errorlevel 1 (
    echo  [ERREUR] Verification echouee : supprime .venv et relance setup.bat.
    pause
    exit /b 1
)
echo  [OK] Dependances installees et verifiees.
echo.

echo  [3/3] Installation terminee.
echo.
echo  Pour lancer l'outil : double-clic sur screencap.bat
echo  Pour desinstaller   : supprime ce dossier (tes captures restent la ou tu les as mises).
echo.
set "GO="
set /p "GO=  Lancer maintenant ? [Entree = oui / n] > "
if /i "%GO%"=="n" exit /b 0
call "%~dp0screencap.bat"
exit /b 0

:: ------------------------------------------------------------
::  :probe <commande...>  -> PYEXE = chemin reel de python.exe
:: ------------------------------------------------------------
:probe
for /f "usebackq delims=" %%I in (`%* -c "import sys; print(sys.executable)" 2^>nul`) do set "PYEXE=%%I"
exit /b 0
