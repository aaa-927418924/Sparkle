@echo off
setlocal
cd /d "%~dp0"

echo Installing dependencies...
py -3.13 -m pip install -r requirements.txt
py -3.13 -m pip install pyinstaller
if errorlevel 1 (
  echo.
  echo Dependency installation failed.
  pause
  exit /b 1
)

echo.
echo Building exe from a clean PyInstaller cache...
py -3.13 -m PyInstaller --clean --noconfirm --onefile --noconsole --name AIClipSaveApp ^
  --add-data "frontend;frontend" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols ^
  --hidden-import uvicorn.protocols.http ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import pystray._win32 ^
  --collect-all tkinter ^
  app_entry.py

if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Done: dist\AIClipSaveApp.exe
pause