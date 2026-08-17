@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 澜盾地面端启动器
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ground_dashboard.ps1"
if errorlevel 1 (
  echo.
  echo 地面端启动失败，请把本窗口截图发给我。
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:8080/"
