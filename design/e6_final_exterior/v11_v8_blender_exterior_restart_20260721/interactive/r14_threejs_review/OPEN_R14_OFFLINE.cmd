@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-offline.ps1"
if errorlevel 1 (
  echo.
  echo WorkCore R14 local preview could not be opened.
  pause
)
