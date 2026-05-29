# Cria NeoVision-Rede-Setup-<vers>.exe (Inno Setup) a partir de dist\NeoVision-Rede.
# Exige: pasta dist\NeoVision-Rede (use antes: build\publish-rede-desktop-python.ps1)
param(
    [switch]$InstalarInnoSeAusente
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRede = Join-Path $Root "dist\NeoVision-Rede"
$Iss = Join-Path $PSScriptRoot "NeoVision-Rede-Setup.iss"

function Get-IsccCandidates {
    return @(
        $env:INNO_SETUP_ISCC,
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
}

if (-not (Test-Path (Join-Path $DistRede "NeoVision-Rede.exe"))) {
    throw "Falta dist\NeoVision-Rede com NeoVision-Rede.exe. Execute primeiro: .\build\publish-rede-desktop-python.ps1"
}

$candidates = @(Get-IsccCandidates)

if ($candidates.Count -lt 1 -and $InstalarInnoSeAusente) {
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wg) {
        throw "ISCC.exe nao encontrado e 'winget' nao esta disponivel."
    }
    Write-Host "A instalar Inno Setup 6 com winget..." -ForegroundColor Yellow
    & winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget falhou (codigo $LASTEXITCODE)." }
    Start-Sleep -Seconds 3
    $candidates = @(Get-IsccCandidates)
}

if ($candidates.Count -lt 1) {
    throw "ISCC.exe nao encontrado. Instale Inno Setup 6 ou defina INNO_SETUP_ISCC."
}

$iscc = $candidates[0]
Write-Host "ISCC: $iscc"
Write-Host "Script: $Iss"
Write-Host ""

& $iscc $Iss
if ($LASTEXITCODE -ne 0) { throw "Compilacao Inno falhou com codigo $LASTEXITCODE" }

Write-Host ""
Write-Host "Instalador rede: $Root\dist\installer\NeoVision-Rede-Setup-*.exe" -ForegroundColor Green
