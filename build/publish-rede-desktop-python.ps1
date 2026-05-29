# Gera dist\NeoVision-Rede com NeoVision-Rede.exe (API completa; UI só monitorização rede).
# Uso:  powershell -ExecutionPolicy Bypass -File .\build\publish-rede-desktop-python.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Api = Join-Path $Root "src\NeoVision.AI"
$OutDist = Join-Path $Root "dist\NeoVision-Rede"

function Test-PythonOk {
    param([string]$Exe, [string[]]$PrefixArgs)
    try {
        $null = & $Exe @PrefixArgs "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

[string[]]$invokeArgs = @()
$pythonExe = $null

if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-PythonOk "python" @())) {
    $pythonExe = "python"
} elseif ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-PythonOk "py" @("-3"))) {
    $pythonExe = "py"
    $invokeArgs = @("-3")
}

if (-not $pythonExe) {
    throw "Precisa Python 3.10+ na PATH como 'python' ou como 'py -3' (launcher). https://www.python.org/downloads/"
}

function Invoke-NeoVisionPython([string[]]$ChildArgs) {
    & $pythonExe @invokeArgs @ChildArgs
}

Write-Host "Raiz:              $Root"
Write-Host "Pasta NeoVision AI: $Api"
Write-Host "Saida:             $OutDist"
Write-Host "Python:            $pythonExe $(if ($invokeArgs.Count -gt 0) { $($invokeArgs -join ' ') } else { '' })"
Write-Host ""

Set-Location $Api

Invoke-NeoVisionPython @("-m", "pip", "install", "-q", "-r", (Join-Path $Api "requirements-desktop-sistema.txt"))
if ($LASTEXITCODE -ne 0) { throw "pip instalacao requirements falhou" }

Invoke-NeoVisionPython @("-m", "pip", "install", "-q", "pyinstaller")
if ($LASTEXITCODE -ne 0) { throw "pip pyinstaller falhou" }

Invoke-NeoVisionPython @("-m", "PyInstaller", "-y", (Join-Path $Api "NeoVision-Rede.spec"))
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

$Built = Join-Path $Api "dist\NeoVision-Rede"
if (-not (Test-Path $Built)) { throw "Pasta nao gerada: $Built" }
if (-not (Test-Path (Join-Path $Built "NeoVision-Rede.exe"))) {
    throw "NeoVision-Rede.exe nao encontrado"
}

$ParentDist = Split-Path $OutDist -Parent
if (-not (Test-Path $ParentDist)) { New-Item -ItemType Directory -Path $ParentDist -Force | Out-Null }
if (Test-Path $OutDist) { Remove-Item -Recurse -Force $OutDist }
Copy-Item -Recurse -Force $Built $OutDist

Write-Host ""
Write-Host "Concluido. Executavel: $OutDist\NeoVision-Rede.exe" -ForegroundColor Green
Write-Host "Inno Setup:  build\NeoVision-Rede-Setup.iss -> dist\installer\" -ForegroundColor Green
