@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title NeoVision - API (instalavel)
if not defined NEOVISION_MYSQL_HOST set "NEOVISION_MYSQL_HOST=127.0.0.1"
if not defined NEOVISION_MYSQL_PORT set "NEOVISION_MYSQL_PORT=3306"
if not defined NEOVISION_MYSQL_USER set "NEOVISION_MYSQL_USER=neovision"
if not defined NEOVISION_MYSQL_PASSWORD set "NEOVISION_MYSQL_PASSWORD=changeme"
if not defined NEOVISION_MYSQL_DATABASE set "NEOVISION_MYSQL_DATABASE=neovision"
set "EX=%~dp0NeoVision-API.exe"
if not exist "%EX%" (
  echo [ERRO] NeoVision-API.exe nao encontrado nesta pasta: %~dp0
  goto :fim
)
echo A iniciar: %EX%
echo Abra: http://127.0.0.1:8080/health  (ou 9080 se 8080 estiver em uso; veja a janela)
echo.
"%EX%"
:fim
pause
endlocal
