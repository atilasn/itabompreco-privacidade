# Empacota API (PyInstaller) + Desktop (dotnet publish) para copiar a outro PC Windows x64.
# Requer no PC de COMPILACAO:
#   - Python 3.10+ (pip, rede na 1.ª vez)
#   - .NET 8 SDK (https://dotnet.microsoft.com/download)
#
# Uso (na raiz do repositorio):
#   powershell -ExecutionPolicy Bypass -File .\build\empacotar-tudo-para-teste.ps1
#
# Saida:
#   dist\NeoVision-API\          (NeoVision-API.exe + _internal; inclui static/painel gravacoes etc.)
#   dist\NeoVision-Desktop-win-x64\  (NeoVision.exe WPF self-contained)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Write-Host ""
Write-Host "=== NeoVision - empacote para testar noutro PC ===" -ForegroundColor Cyan
Write-Host "Raiz: $Root"
Write-Host ""

# --- API Python ---
Write-Host "[1/2] API (PyInstaller)..." -ForegroundColor Yellow
& (Join-Path $Root "build\publish-api-windows.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""

# --- Desktop WPF ---
Write-Host "[2/2] Desktop WPF (.NET)..." -ForegroundColor Yellow
& (Join-Path $Root "build\publish-windows.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== Concluido ===" -ForegroundColor Green
Write-Host "Copie para o pen-drive / outro PC as pastas:" -ForegroundColor White
Write-Host "  $($Root.Path)\dist\NeoVision-API" -ForegroundColor Gray
Write-Host "  $($Root.Path)\dist\NeoVision-Desktop-win-x64" -ForegroundColor Gray
Write-Host ""
Write-Host "Instalador opcional (Inno Setup 6):" -ForegroundColor DarkGray
Write-Host "  Abra build\NeoVision-Setup.iss , compile F9 -> dist\installer\" -ForegroundColor DarkGray
Write-Host ""
