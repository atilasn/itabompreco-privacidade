@echo off
chcp 65001 >nul
title NeoVision - gerar .exe para teste
cd /d "%~dp0.."

echo.
echo  Gera: dist\NeoVision-Sistema\NeoVision-Sistema.exe
echo  Precisa Python no PATH ^+ rede na primeira vez ^(pip^).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish-sistema-desktop-python.ps1"
if errorlevel 1 (
  echo.
  echo [ERRO] Ver mensagens acima.
  pause
  exit /b 1
)
echo.
echo Pronto. Pode copiar a pasta inteira:
echo   %cd%\dist\NeoVision-Sistema
pause

