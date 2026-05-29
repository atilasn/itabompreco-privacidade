@echo off
chcp 65001 >nul
title NeoVision — build + Inno (winget se faltar Inno)
cd /d "%~dp0.."

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Precisa Python 3.10+ como "python" ou launcher "py" na PATH.
    pause
    exit /b 1
  )
)

echo Usa Inno Setup instalado OU tenta instalacao com winget se ISCC nao existir.
echo Mais ajuda: build\COMO-INSTALAR-NO-MEU-PC.txt
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gerar-instalador-tudo.ps1" -InstalarInnoSeAusente
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
echo Falhou. Ver mensagens acima.
pause
exit /b 1
