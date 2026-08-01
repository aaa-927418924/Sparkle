@echo off
setlocal
cd /d "%~dp0"

set "VENV_DIR="
if exist "%~dp0.venv313\Scripts\python.exe" set "VENV_DIR=%~dp0.venv313"
if not defined VENV_DIR if exist "%~dp0.venv\Scripts\python.exe" set "VENV_DIR=%~dp0.venv"

if not defined VENV_DIR (
  echo.
  echo No project virtual environment was found. Expected .venv313 or .venv.
  echo.
  pause
  exit /b 1
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"

if not exist "%PYTHON%" (
  echo.
  echo The selected virtual environment is missing its Python executable.
  echo.
  pause
  exit /b 1
)

if not exist "%PYINSTALLER%" (
  echo.
  echo PyInstaller was not found in the selected virtual environment.
  echo Install project dependencies and PyInstaller before building.
  pause
  exit /b 1
)

echo.
echo Building exe from a clean PyInstaller cache...
"%PYINSTALLER%" --clean --noconfirm Sparkle.spec

if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Done: dist\Sparkle.exe
pause
