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

"%PYTHON%" -c "from pathlib import Path; import sys; expected=Path(r'%VENV_DIR%').resolve(); actual=Path(sys.prefix).resolve(); raise SystemExit(0 if actual == expected else 1)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo The selected virtual environment was created under a different folder or is invalid.
  echo Recreate .venv313 in the current project folder before building.
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
echo Generating Sparkle.exe.sha256...
powershell -NoProfile -Command "$f = Join-Path 'dist' 'Sparkle.exe'; $h = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLowerInvariant(); Set-Content -LiteralPath (Join-Path 'dist' 'Sparkle.exe.sha256') -Value ('{0}  Sparkle.exe' -f $h) -Encoding ascii"
if errorlevel 1 (
  echo.
  echo SHA-256 generation failed.
  pause
  exit /b 1
)

echo.
echo Done: dist\Sparkle.exe (+ Sparkle.exe.sha256)
pause
