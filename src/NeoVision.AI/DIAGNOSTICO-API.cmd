@echo off
chcp 65001 >nul 2>&1
setlocal
title NeoVision - diagnostico da API na porta 8080 ou 9080
echo.
echo ============================================================
echo   NEOVISION - diagnostico
echo ============================================================
echo.
echo --- Netstat porta 8080 (LISTEN ou estabelecidos) ---
netstat -ano | findstr ":8080 " 2>nul
echo.
echo --- Netstat porta 9080 ---
netstat -ano | findstr ":9080 " 2>nul
echo.

echo Abrindo GET / como JSON para ver quanto vale "neovision_api_build".
echo Esperado quando o CODIGO deste repo estiver ACTIVO: "root-json-v2-gravacoes-painel"
echo SE vir "root-json-v1": o servidor eh ANTIGO (outra pasta OU NeoVision-API.exe empacotado).
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try {" ^
   " $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -Headers @{Accept='application/json'} -UseBasicParsing -TimeoutSec 5;" ^
   " Write-Host ($r.Content)" ^
  "} catch { Write-Host '[ERRO] Nao houve JSON em http://127.0.0.1:8080/'; Write-Host $_ }"

echo.
echo --- Testar pagina gravacoes VIA STATIC (evita erro /painel/ antigo) ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try {" ^
   " $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/static/painel/gravacoes.html' -UseBasicParsing -TimeoutSec 5;" ^
   " if ($r.StatusCode -eq 200 -and $r.Content.Length -gt 500) {" ^
    " Write-Host '[OK] Ficheiro estatico gravacoes.html respondeu (HTML).' " ^
    " Write-Host '(Abra esta URL no browser se /painel/gravacoes der JSON antigo).' " ^
    " Write-Host '   http://127.0.0.1:8080/static/painel/gravacoes.html'" ^
   "} else { Write-Host '[ERRO] Resposta estranha' } " ^
  "} catch { Write-Host '[ERRO] static/gravacoes.html nao encontrado ou porta errada'; Write-Host $_ }"

echo.
echo ============================================================
echo Resumo rapido:
echo   - neo build v1 + erro "Secções... tempo-real" SEM gravacoes  = CODIGO VELHO a correr
echo   - Gravar pagina: usar fontes com INICIAR-NEOVISION-DESDE-SRC.cmd (raiz repo)
echo   - Ou recompilar NeoVision-API.exe DEPOIS de actualizar codigo Python
echo ============================================================
echo.
pause
endlocal
