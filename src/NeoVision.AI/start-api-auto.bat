@echo off
chcp 65001 >nul
cd /d "%~dp0"
title NeoVision API (porta automatica)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-api-auto.ps1"
pause
