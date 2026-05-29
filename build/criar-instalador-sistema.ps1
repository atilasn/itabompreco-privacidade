# Cria NeoVision-Sistema-Setup-<vers>.exe (Inno Setup) a partir de dist\NeoVision-Sistema.
# Exige: pasta dist\NeoVision-Sistema (use antes: build\publish-sistema-desktop-python.ps1)
# e Inno Setup 6 (ISCC). Se ISCC nao estiver no PATH, define $env:INNO_SETUP_ISCC.
#
# Opcional: -InstalarInnoSeAusente tenta `winget install JRSoftware.InnoSetup` se ISCC faltar
# (pode pedir consentimento do utilizador / UAC no Windows).
param(
    [switch]$InstalarInnoSeAusente
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistSistema = Join-Path $Root "dist\NeoVision-Sistema"
$Iss = Join-Path $PSScriptRoot "NeoVision-Sistema-Setup.iss"

function Get-IsccCandidates {
    return @(
        $env:INNO_SETUP_ISCC,
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
}

if (-not (Test-Path (Join-Path $DistSistema "NeoVision-Sistema.exe"))) {
    throw "Falta a pasta dist\NeoVision-Sistema com NeoVision-Sistema.exe. Execute primeiro: .\build\publish-sistema-desktop-python.ps1"
}

$candidates = @(Get-IsccCandidates)

if ($candidates.Count -lt 1 -and $InstalarInnoSeAusente) {
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wg) {
        throw "ISCC.exe nao encontrado e 'winget' nao esta disponivel. Instale Inno Setup 6 (https://jrsoftware.org/isdl.php) ou defina INNO_SETUP_ISCC."
    }
    Write-Host "Inno Setup 6 nao encontrado. A instalar com winget (JRSoftware.InnoSetup)..." -ForegroundColor Yellow
    & winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget falhou ao instalar Inno Setup (codigo $LASTEXITCODE). Instale manualmente: https://jrsoftware.org/isdl.php"
    }
    Start-Sleep -Seconds 3
    $candidates = @(Get-IsccCandidates)
}

if ($candidates.Count -lt 1) {
    throw "ISCC.exe nao encontrado. Instale Inno Setup 6 (https://jrsoftware.org/isdl.php), ou: winget install -e --id JRSoftware.InnoSetup, ou corra este script com -InstalarInnoSeAusente se tiver winget."
}

$iscc = $candidates[0]
Write-Host "ISCC: $iscc"
Write-Host "Script: $Iss"
Write-Host ""

& $iscc $Iss
if ($LASTEXITCODE -ne 0) { throw "Compilacao Inno falhou com codigo $LASTEXITCODE" }

Write-Host ""
Write-Host "Instalador: $Root\dist\installer\" -ForegroundColor Green
