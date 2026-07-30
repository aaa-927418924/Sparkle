@echo off
setlocal
cd /d "%~dp0"

rem Reuse the packaged app when it is already serving port 8000.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }"
if errorlevel 1 goto start_server
echo AIClipSaveApp is already running on http://127.0.0.1:8000
exit /b 0

:start_server
uvicorn main:app --reload --host 127.0.0.1 --port 8000
if errorlevel 1 pause