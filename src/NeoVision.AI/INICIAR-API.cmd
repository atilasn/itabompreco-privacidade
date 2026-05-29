@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title NeoVision - API
REM Base: SQLite em NeoVisionData\neovision.sqlite (omitir NEOVISION_DB ou =sqlite). Para MySQL: set NEOVISION_DB=mysql
if not defined NEOVISION_DB set "NEOVISION_DB=sqlite"
if not defined NEOVISION_MYSQL_HOST set "NEOVISION_MYSQL_HOST=127.0.0.1"
if not defined NEOVISION_MYSQL_PORT set "NEOVISION_MYSQL_PORT=3306"
if not defined NEOVISION_MYSQL_USER set "NEOVISION_MYSQL_USER=neovision"
if not defined NEOVISION_MYSQL_PASSWORD set "NEOVISION_MYSQL_PASSWORD=changeme"
if not defined NEOVISION_MYSQL_DATABASE set "NEOVISION_MYSQL_DATABASE=neovision"
mode con: cols=90 lines=30 2>nul

echo.
echo  ============================================================
echo   NeoVision AI - servico de API
echo  ============================================================
echo   PASTA: %cd%
echo.
echo   NAO FECHE ESTA JANELA enquanto usa o site no browser.
echo   Se fechar a janela, o site deixa de responder.
echo  ============================================================
echo.

set "PY="
where python >nul 2>&1
if %errorlevel%==0 set "PY=python"
if not defined PY (
  where py >nul 2>&1
  if !errorlevel! equ 0 set "PY=py -3"
)
if not defined PY (
  echo [ERRO] Python nao encontrado.
  echo Instale em https://www.python.org/ e marque Add python.exe to PATH
  echo.
  goto :fim
)

echo A usar: %PY%
call %PY% --version
if errorlevel 1 (
  echo [ERRO] Nao foi possivel executar Python. Tente: py -3
  goto :fim
)
echo.

echo A verificar: uvicorn e fastapi
%PY% -c "import uvicorn, fastapi" 2>nul
if errorlevel 1 (
  echo A instalar dependencias - pode demorar 1-2 minutos
  %PY% -m pip install -q -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo [ERRO] pip install falhou.
    echo Comando: %PY% -m pip install -r requirements.txt
    goto :fim
  )
)

echo A carregar app.main ...
%PY% -c "import app.main" 2>nul
if errorlevel 1 (
  echo [ERRO] Falha ao importar app.main. Detalhe:
  %PY% -c "import app.main"
  goto :fim
)
echo   OK: app.main carregou.
echo.
echo Ficheiro Python que o servidor VAI USAR (confirme que e esta pasta do projeto^):
%PY% -c "import pathlib, app.main as m; print('  ', pathlib.Path(m.__file__).resolve())"
echo Se este caminho NAO for o da pasta NeoVision.AI correta, feche e abra o INICIAR-API.cmd
echo a partir da pasta certa (ou arraste o .cmd para o prompt ja na pasta src\NeoVision.AI).
echo.

set "PORT=8080"
%PY% -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',8080)); s.close()" 2>nul
if errorlevel 1 (
  set "PORT=9080"
  echo [AVISO] Porta 8080 ocupada. A usar 9080.
)

echo  ------------------------------------------------
echo   Quando aparecer: Uvicorn running on http://127.0.0.1:%PORT% ...
echo   pagina de botoes:  http://127.0.0.1:%PORT%/painel
echo   teste de vida:     http://127.0.0.1:%PORT%/health
echo  ------------------------------------------------
echo.

%PY% -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload
echo.
echo  Servidor encerrado. codigo saida: !errorlevel!

:fim
echo.
echo  Pressione qualquer tecla para fechar esta janela.
pause

endlocal
