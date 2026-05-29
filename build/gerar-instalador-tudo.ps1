# Gera o pacote NeoVision-Sistema (.exe PyInstaller + pasta dist) e opcionalmente
# o instalador Windows (.exe Inno Setup): dist\installer\NeoVision-Sistema-Setup-<vers>.exe
#
# Uso (na raiz do repositório):
#   powershell -ExecutionPolicy Bypass -File .\build\gerar-instalador-tudo.ps1
# Opcional — se não tiver Inno Setup instalado mas tiver winget:
#   powershell -ExecutionPolicy Bypass -File .\build\gerar-instalador-tudo.ps1 -InstalarInnoSeAusente
#
param(
    [switch]$InstalarInnoSeAusente
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$pub = Join-Path $PSScriptRoot "publish-sistema-desktop-python.ps1"
if (-not (Test-Path $pub)) { throw "Falta publish-sistema-desktop-python.ps1 em build\" }

Write-Host ""
Write-Host "=== [1/2] Pacote NeoVision-Sistema (PyInstaller) ===" -ForegroundColor Cyan
Write-Host ""

& $pub

Write-Host ""
Write-Host "=== [2/2] Instalador Inno Setup ===" -ForegroundColor Cyan
Write-Host ""

$criar = Join-Path $PSScriptRoot "criar-instalador-sistema.ps1"
if ($InstalarInnoSeAusente) {
    & $criar -InstalarInnoSeAusente
} else {
    & $criar
}

$setup = Join-Path $Root "dist\installer"
Write-Host ""
Write-Host "Feito." -ForegroundColor Green
Write-Host "  Pasta da app: $Root\dist\NeoVision-Sistema\"
Write-Host "  Setup:        $setup\"
Write-Host ""
