@echo off
chcp 65001 >nul
cd /d "%~dp0"
title NeoVision API :8080
echo.
echo [NeoVision] Pasta: %cd%
echo [NeoVision] MANTER ESTA JANELA ABERTA. Se fechar, o site deixa de responder.
echo [NeoVision] Testar: http://127.0.0.1:8080/health
echo [NeoVision] Se a porta 8080 estiver ocupada, use start-api-9080.bat
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
if errorlevel 1 (
  echo.
  echo --- ERRO acima. Se falar em porta/ bind, tente: start-api-9080.bat
  echo ---
)
pause
