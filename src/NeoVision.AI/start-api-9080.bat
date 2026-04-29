@echo off
chcp 65001 >nul
cd /d "%~dp0"
title NeoVision API :9080
echo.
echo A usar porta 9080 (evita conflito se outro programa usar 8080).
echo Abrir: http://127.0.0.1:9080/
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 9080 --reload
pause
