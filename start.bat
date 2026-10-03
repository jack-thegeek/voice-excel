@echo off
rem =============================================
rem  voice-excel one-click launcher (Windows)
rem  Double-click this file to start the service
rem =============================================
title voice-excel Launcher
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
    echo.
    echo Startup failed, see messages above.
    pause
)
