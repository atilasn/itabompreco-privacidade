# NeoVision AI - arranca a API na primeira porta livre (8080, 9080, ...)
# Uso: duplo clique em start-api-auto.bat ou: powershell -File start-api-auto.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-PortAvailable([int] $Port) {
    try {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $l.Start()
        $l.Stop()
        return $true
    } catch {
        return $false
    }
}

$candidates = @(8080, 9080, 9200, 9400, 8765, 5500)
$chosen = $null
foreach ($p in $candidates) {
    if (Test-PortAvailable $p) {
        $chosen = $p
        break
    }
}

if (-not $chosen) {
    Write-Host "Nenhuma porta da lista esta livre. Feche outros servidores ou edite start-api-auto.ps1" -ForegroundColor Red
    pause
    exit 1
}

$url = "http://127.0.0.1:$chosen/health"
Write-Host ""
Write-Host "  >>> MANTER ESTA JANELA ABERTA <<<" -ForegroundColor Yellow
Write-Host "  >>> Abra no browser: $url" -ForegroundColor Green
Write-Host ""
Write-Host "  (Se fechar o terminal, o site deixa de funcionar - conexao recusada)" -ForegroundColor DarkGray
Write-Host ""

python -m uvicorn app.main:app --host 127.0.0.1 --port $chosen --reload
