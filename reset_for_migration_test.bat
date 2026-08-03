@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Sparkle - migration test reset

if not defined APPDATA (
  echo APPDATA is not available. Nothing was deleted.
  exit /b 2
)
if not defined USERPROFILE (
  echo USERPROFILE is not available. Nothing was deleted.
  exit /b 2
)

set "CURRENT_DATA=%APPDATA%\Sparkle"
set "CURRENT_EXPORT=%USERPROFILE%\Documents\Sparkle\ai-export"
set "CURRENT_EXPORT_ROOT=%USERPROFILE%\Documents\Sparkle"
set "LEGACY_DATA=%APPDATA%\AIClipSaveApp"
set "LEGACY_EXPORT_ROOT=%USERPROFILE%\Documents\AIClipSaveApp"

tasklist /FI "IMAGENAME eq Sparkle.exe" 2>NUL | find /I "Sparkle.exe" >NUL
if not errorlevel 1 (
  echo Sparkle.exe is running. Close Sparkle and run this file again.
  exit /b 3
)

echo.
echo This will permanently delete these application data folders:
echo   %CURRENT_DATA%
echo   %CURRENT_EXPORT%
echo   %LEGACY_DATA% (if it already exists)
echo   %LEGACY_EXPORT_ROOT% (if it already exists)
echo.
echo After deletion, empty legacy test folders will be created at:
echo   %LEGACY_DATA%
echo   %LEGACY_EXPORT_ROOT%
echo.
echo Backup ZIP and DB files outside these folders are not touched.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 goto :cancel
if not errorlevel 1 goto :cancel

call :remove_tree "%CURRENT_DATA%"
if errorlevel 1 goto :failed
call :remove_tree "%CURRENT_EXPORT%"
if errorlevel 1 goto :failed
call :remove_tree "%LEGACY_DATA%"
if errorlevel 1 goto :failed
call :remove_tree "%LEGACY_EXPORT_ROOT%"
if errorlevel 1 goto :failed

if not exist "%LEGACY_DATA%\" md "%LEGACY_DATA%"
if not exist "%LEGACY_DATA%\" goto :failed
if not exist "%LEGACY_EXPORT_ROOT%\" md "%LEGACY_EXPORT_ROOT%"
if not exist "%LEGACY_EXPORT_ROOT%\" goto :failed

call :remove_empty_dir "%CURRENT_EXPORT_ROOT%"
echo.
echo Migration test state is ready.
echo The legacy folders are intentionally empty. An empty folder alone does not
echo trigger migration; add legacy data or place a legacy backup before launch.
pause
exit /b 0

:remove_tree
if not exist "%~1\" exit /b 0
rmdir /s /q "%~1"
if exist "%~1\" exit /b 1
exit /b 0

:remove_empty_dir
if not exist "%~1\" exit /b 0
rmdir "%~1" 2>NUL
exit /b 0

:cancel
echo Cancelled. Nothing was deleted.
exit /b 1

:failed
echo A folder could not be removed or recreated. Check that no file is open and try again.
exit /b 4
