# Gera a pasta `dist/NeoVision-API` com NeoVision-API.exe (Python empacotado, PyInstaller).
# Requer: Python 3.10+ e rede (na primeira vez: pip instala PyInstaller, etc.).
# Uso:  powershell -ExecutionPolicy Bypass -File .\build\publish-api-windows.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Api = Join-Path $Root "src\NeoVision.AI"
$OutDist = Join-Path $Root "dist\NeoVision-API"

Write-Host "Raiz:      $Root"
Write-Host "Python API: $Api"
Write-Host "Saida:     $OutDist"
Write-Host ""

Set-Location $Api
python -m pip install -q -r (Join-Path $Api "requirements.txt")
python -m pip install -q pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip falhou" }

python -m PyInstaller -y (Join-Path $Api "NeoVision-API.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

$Built = Join-Path $Api "dist\NeoVision-API"
if (-not (Test-Path $Built)) { throw "Pasta nao gerada: $Built" }
if (-not (Test-Path (Join-Path $Built "NeoVision-API.exe"))) { throw "NeoVision-API.exe nao encontrado" }

# Copia p/ dist do repo (raiz) para fica tudo com o publicador do WPF
$ParentDist = Split-Path $OutDist -Parent
if (-not (Test-Path $ParentDist)) { New-Item -ItemType Directory -Path $ParentDist -Force | Out-Null }
if (Test-Path $OutDist) { Remove-Item -Recurse -Force $OutDist }
Copy-Item -Recurse -Force $Built $OutDist
$Launcher = Join-Path $Api "INICIAR-API-DIST.cmd"
if (Test-Path $Launcher) { Copy-Item -Force $Launcher (Join-Path $OutDist "INICIAR-API-DIST.cmd") }
Write-Host ""
Write-Host "Concluido. Executavel: $OutDist\NeoVision-API.exe" -ForegroundColor Green
Write-Host "Lancador opcional:     $OutDist\INICIAR-API-DIST.cmd" -ForegroundColor Green
