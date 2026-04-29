# Junta numa pasta para o pendrive: API + (Desktop se existir) + SQL + TXT de instrucoes.
# Uso na raiz do repo:
#   powershell -ExecutionPolicy Bypass -File .\build\pacote-para-outro-pc.ps1
#   powershell -ExecutionPolicy Bypass -File .\build\pacote-para-outro-pc.ps1 -Rebuild

param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PacoteNome = "NeoVision-Pacote-PC"
$DestRoot = Join-Path $Root ("dist\{0}" -f $PacoteNome)

if ($Rebuild) {
    Write-Host "-Rebuild: a compilar API + Desktop primeiro..." -ForegroundColor Cyan
    & (Join-Path $Root "build\empacotar-tudo-para-teste.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[AVISO] compilacao falhou ou incompleta (ex.: sem .NET SDK para Desktop). Continuo se existir API em dist\..." -ForegroundColor Yellow
    }
    Write-Host ""
}

$SrcApi = Join-Path $Root "dist\NeoVision-API"
$SrcDesk = Join-Path $Root "dist\NeoVision-Desktop-win-x64"
$Sql = Join-Path $Root "db\schema.sql"

if (-not (Test-Path $SrcApi)) {
    Write-Host "[ERRO] Nao existe API compilada: $SrcApi" -ForegroundColor Red
    Write-Host "       Execute: .\build\publish-api-windows.ps1" -ForegroundColor Yellow
    exit 1
}

$TemDesktop = Test-Path $SrcDesk
if (-not $TemDesktop) {
    Write-Host "[AVISO] Desktop nao encontrado: $SrcDesk" -ForegroundColor Yellow
    Write-Host "       O pacote vai ter so API + docs. No PC com .NET SDK: .\build\publish-windows.ps1" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== A criar pacote para outro PC ===" -ForegroundColor Cyan
Write-Host "Origem Api:       $SrcApi"
if ($TemDesktop) { Write-Host "Origem Desktop:   $SrcDesk" }
Write-Host "Destino:          $DestRoot"
Write-Host ""

if (Test-Path $DestRoot) {
    Remove-Item -LiteralPath $DestRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null

$DestApi = Join-Path $DestRoot "NeoVision-API"
Copy-Item -LiteralPath $SrcApi -Destination $DestApi -Recurse -Force

if ($TemDesktop) {
    $DestDesk = Join-Path $DestRoot "NeoVision-Desktop"
    Copy-Item -LiteralPath $SrcDesk -Destination $DestDesk -Recurse -Force
}
else {
    $Av = Join-Path $DestRoot "Desktop-nao-incluido-Leia.txt"
    @"
O programa de mesa NeoVision (WPF) NAO foi copiado porque nao existia a pasta compilada:
  dist\NeoVision-Desktop-win-x64

Para gerar no PC de desenvolvimento (com .NET 8 SDK instalado):
  powershell -ExecutionPolicy Bypass -File .\build\publish-windows.ps1

Depois volte a empacotar:
  .\build\pacote-para-outro-pc.ps1

So a API (NeoVision-API) segue funcional no pendrive.
"@ | Out-File -FilePath $Av -Encoding UTF8
}

if (-not (Test-Path $Sql)) {
    Write-Host "[AVISO] schema.sql nao encontrado." -ForegroundColor Yellow
}
else {
    $ddb = Join-Path $DestRoot "db"
    New-Item -ItemType Directory -Path $ddb -Force | Out-Null
    Copy-Item -LiteralPath $Sql -Destination (Join-Path $ddb "schema.sql") -Force
}

$GuiaUsuario = Join-Path $PSScriptRoot "INSTALACAO-NO-PC.txt"
if (-not (Test-Path $GuiaUsuario)) {
    throw "Ficheiro em falta: $GuiaUsuario"
}
Copy-Item -LiteralPath $GuiaUsuario -Destination (Join-Path $DestRoot "INSTALACAO-NO-PC.txt") -Force

$Leia = Join-Path $Root "src\NeoVision.AI\LEIA-INICIO.txt"
if (Test-Path $Leia) {
    Copy-Item -LiteralPath $Leia -Destination (Join-Path $DestRoot "Api-LEIA-INICIO.txt") -Force
}

$absDest = (Resolve-Path $DestRoot).Path
$absDist = (Resolve-Path (Join-Path $Root "dist")).Path
$caminhoTxt = Join-Path $DestRoot "CAMINHO-DO-PACOTE.txt"
@"
NEOVISION AI - Onde esta o pacote no seu PC
=============================================

COPIE PARA O PENDRIVE ESTA PASTA COMPLETA (arrastar a pasta inteira):

$absDest

Depois de copiar, no outro PC abra primeiro o ficheiro:

  INSTALACAO-NO-PC.txt

Pasta dist do projecto (pai deste pacote):

$absDist

Data/hora de empacote (deste PC): $(Get-Date -Format "yyyy-MM-dd HH:mm")
"@ | Out-File -FilePath $caminhoTxt -Encoding UTF8

Write-Host "Concluido." -ForegroundColor Green
Write-Host ""
Write-Host "Copie para o pendrive:" -ForegroundColor White
Write-Host "  $absDest" -ForegroundColor Gray
Write-Host ""
