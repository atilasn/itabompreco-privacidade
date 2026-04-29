@echo off
chcp 65001 >nul 2>&1
REM Arranca sempre a API a partir da pasta FONTES (codigo atual do Git/repo).
REM NAO use isto ao mesmo tempo que NeoVision-API.exe na mesma porta.
cd /d "%~dp0src\NeoVision.AI"
title NeoVision API - codigo em src (nao eh o exe da pasta dist)
echo.
echo  ================================================================
echo    Arranque pela pasta SRC (codigo mais recente)
echo    Pasta: %CD%
echo  ================================================================
echo    Se mesmo assim aparecer erro antigo na porta 8080:
echo      1) Feche JANELAS onde corre NeoVision ou python antigo.
echo      2) Ou execute DIAGNOSTICO-API.cmd na pasta src\NeoVision.AI.
echo  ================================================================
echo.
call INICIAR-API.cmd
