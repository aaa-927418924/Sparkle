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

set "SPARKLE_EXE=%~dp0dist\Sparkle.exe"
set "SPARKLE_MCP_EXE=%~dp0dist\SparkleMCP.exe"
echo.
echo Closing the running Sparkle app from "%SPARKLE_EXE%" if necessary...
powershell -NoProfile -Command "$target = [System.IO.Path]::GetFullPath($env:SPARKLE_EXE); $matches = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'Sparkle.exe' -and $_.ExecutablePath -and ([System.IO.Path]::GetFullPath($_.ExecutablePath) -ieq $target) }); foreach ($match in $matches) { $process = Get-Process -Id $match.ProcessId -ErrorAction SilentlyContinue; if ($process) { $null = $process.CloseMainWindow(); if (-not $process.WaitForExit(5000)) { Stop-Process -Id $match.ProcessId -Force -ErrorAction Stop } } }"
if errorlevel 1 (
  echo.
  echo Could not close the running Sparkle app safely.
  pause
  exit /b 1
)

echo.
echo Closing the running SparkleMCP server from "%SPARKLE_MCP_EXE%" if necessary...
powershell -NoProfile -Command "$target = [System.IO.Path]::GetFullPath($env:SPARKLE_MCP_EXE); $matches = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'SparkleMCP.exe' -and $_.ExecutablePath -and ([System.IO.Path]::GetFullPath($_.ExecutablePath) -ieq $target) }); foreach ($match in $matches) { $process = Get-Process -Id $match.ProcessId -ErrorAction SilentlyContinue; if ($process) { Stop-Process -Id $process.Id -Force -ErrorAction Stop } }"
if errorlevel 1 (
  echo.
  echo Could not close the running SparkleMCP server safely.
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
echo Generating executable SHA-256 files...
"%PYTHON%" -c "from hashlib import sha256; from pathlib import Path; items=[(Path(r'dist\Sparkle.exe'),Path(r'dist\Sparkle.exe.sha256'),'Sparkle.exe'),(Path(r'dist\SparkleMCP.exe'),Path(r'dist\SparkleMCP.exe.sha256'),'SparkleMCP.exe')]; [out.write_text(sha256(src.read_bytes()).hexdigest()+'  '+name+chr(10),encoding='ascii') for src,out,name in items]"
if errorlevel 1 (
  echo.
  echo SHA-256 generation failed.
  pause
  exit /b 1
)

echo.
echo Creating Claude Desktop MCPB bundle...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_mcpb.ps1"
if errorlevel 1 (
  echo.
  echo MCPB bundle generation failed.
  pause
  exit /b 1
)

echo.
echo Generating MCPB SHA-256 file...
"%PYTHON%" -c "from hashlib import sha256; from pathlib import Path; src=Path(r'dist\Sparkle.mcpb'); out=Path(r'dist\Sparkle.mcpb.sha256'); out.write_text(sha256(src.read_bytes()).hexdigest()+'  Sparkle.mcpb'+chr(10),encoding='ascii')"
if errorlevel 1 (
  echo.
  echo MCPB SHA-256 generation failed.
  pause
  exit /b 1
)

echo.
echo Done: dist\Sparkle.exe, dist\SparkleMCP.exe, and dist\Sparkle.mcpb (+ SHA-256 files)
pause
