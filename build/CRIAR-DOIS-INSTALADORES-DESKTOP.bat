@echo off
chcp 65001 >nul
title NeoVision — dois instaladores (completo + só rede)
cd /d "%~dp0.."

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Este script precisa de Python 3.10+ na PATH como "python" ou launcher "py".
    pause
    exit /b 1
  )
)

echo Gera:
echo   dist\installer\NeoVision-Sistema-Setup-0.2.0.exe  — painel completo
echo   dist\installer\NeoVision-Rede-Setup-0.2.0.exe    — só monitorização de rede
echo Requer: Inno Setup 6 ^(ISCC^). Opcional: winget install JRSoftware.InnoSetup
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0GERAR-DOIS-INSTALADORES-DESKTOP.ps1"
if errorlevel 1 goto :err

echo.
explorer "%cd%\dist\installer"
pause
exit /b 0

:err
echo.
echo Falhou um dos passos. Ver mensagens acima.
pause
exit /b 1
