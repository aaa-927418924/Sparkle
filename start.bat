@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0dist\AIClipSaveApp.exe" (
  start "" "%~dp0dist\AIClipSaveApp.exe"
  exit /b 0
)

set "VENV_DIR="
if exist "%~dp0.venv313\Scripts\python.exe" set "VENV_DIR=%~dp0.venv313"
if not defined VENV_DIR if exist "%~dp0.venv\Scripts\python.exe" set "VENV_DIR=%~dp0.venv"

if not defined VENV_DIR (
  echo No project virtual environment was found. Expected .venv313 or .venv.
  pause
  exit /b 1
)

start "" /b "%VENV_DIR%\Scripts\python.exe" "%~dp0app_entry.py"
