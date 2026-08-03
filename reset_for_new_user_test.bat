@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Sparkle - new user test reset

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
  echo Sparkle.exe is running.
  echo Close Sparkle, including its tray process, before continuing.
  choice /C YN /N /M "Press Y after closing Sparkle to recheck, or N to cancel. [Y/N] "
  if errorlevel 2 goto :cancel
  tasklist /FI "IMAGENAME eq Sparkle.exe" 2>NUL | find /I "Sparkle.exe" >NUL
  if not errorlevel 1 goto :failed_running
)

echo.
echo This will permanently delete these application data folders:
echo   %CURRENT_DATA%
echo   %CURRENT_EXPORT%
echo   %LEGACY_DATA% (if it exists)
echo   %LEGACY_EXPORT_ROOT% (if it exists)
echo.
echo No empty legacy folder will be created.
echo Backup ZIP and DB files outside these folders are not touched.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 goto :cancel
if not errorlevel 1 goto :cancel

if exist "%CURRENT_DATA%\" rmdir /s /q "%CURRENT_DATA%"
if exist "%CURRENT_DATA%\" goto :failed
if exist "%CURRENT_EXPORT%\" rmdir /s /q "%CURRENT_EXPORT%"
if exist "%CURRENT_EXPORT%\" goto :failed
if exist "%LEGACY_DATA%\" rmdir /s /q "%LEGACY_DATA%"
if exist "%LEGACY_DATA%\" goto :failed
if exist "%LEGACY_EXPORT_ROOT%\" rmdir /s /q "%LEGACY_EXPORT_ROOT%"
if exist "%LEGACY_EXPORT_ROOT%\" goto :failed

if exist "%CURRENT_EXPORT_ROOT%\" rmdir "%CURRENT_EXPORT_ROOT%" 2>NUL
echo.
echo New user test state is ready.
echo If a legacy backup or legacy executable remains outside these folders,
echo Sparkle may still show the migration screen by design.
pause
exit /b 0

:cancel
echo Cancelled. Nothing was deleted.
exit /b 1

:failed
echo A folder could not be removed. Check that no file is open and try again.
exit /b 4

:failed_running
echo Sparkle.exe is still running. No data was deleted.
exit /b 5
