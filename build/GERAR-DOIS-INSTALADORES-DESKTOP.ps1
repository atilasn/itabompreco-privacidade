# Gera os dois .exe de instalacao em dist\installer:
#   - NeoVision-Sistema-Setup-0.2.0.exe  (painel completo)
#   - NeoVision-Rede-Setup-0.2.0.exe   (só janela monitorização de rede)
#
# Requer: Python 3.10+, Inno Setup 6 (ISCC no PATH ou INNO_SETUP_ISCC).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\build\GERAR-DOIS-INSTALADORES-DESKTOP.ps1
# Opcional:
#   .\build\GERAR-DOIS-INSTALADORES-DESKTOP.ps1 -InstalarInnoSeAusente

param(
    [switch]$InstalarInnoSeAusente
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

& (Join-Path $here "publish-sistema-desktop-python.ps1")
& (Join-Path $here "criar-instalador-sistema.ps1") @PSBoundParameters

& (Join-Path $here "publish-rede-desktop-python.ps1")
& (Join-Path $here "criar-instalador-rede.ps1") @PSBoundParameters

Write-Host ""
Write-Host "Feito. Ver: dist\installer\" -ForegroundColor Green
