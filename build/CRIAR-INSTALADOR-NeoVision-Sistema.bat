@echo off
chcp 65001 >nul
title NeoVision — build + instalador Windows
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

echo Requisitos: Python 3.10+ (python ou py -3) ; Inno Setup 6 (ISCC^)
echo Mais ajuda:  build\COMO-INSTALAR-NO-MEU-PC.txt
echo.

echo Pacote PyInstaller + instalador Inno...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gerar-instalador-tudo.ps1"
if errorlevel 1 goto :err

echo.
echo Concluído:
echo   %cd%\dist\installer\NeoVision-Sistema-Setup-0.2.0.exe
echo.
explorer /select,"%cd%\dist\installer\NeoVision-Sistema-Setup-0.2.0.exe"
pause
exit /b 0

:err
echo.
echo Falhou um dos passos. Ver mensagens acima.
pause
exit /b 1
