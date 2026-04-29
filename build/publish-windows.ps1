# Gera o instalável do NeoVision AI para Windows (x64), sem exigir .NET no PC do usuário.

# Requer: .NET 8 SDK (https://dotnet.microsoft.com/download)

# Uso:  .\build\publish-windows.ps1   ou   powershell -ExecutionPolicy Bypass -File .\build\publish-windows.ps1



param(

    [ValidateSet("Release", "Debug")]

    [string]$Configuration = "Release",



    [switch]$SingleFile

)



$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$OutDir = Join-Path $Root "dist\NeoVision-Desktop-win-x64"



Write-Host "Raiz: $Root"

Write-Host "Saida: $OutDir"

Write-Host ""



$proj = Join-Path $Root "src\NeoVision.Desktop\NeoVision.Desktop.csproj"



$args = @(

    "publish", $proj

    "-c", $Configuration

    "-r", "win-x64"

    "--self-contained", "true"

    "/p:DebugType=none"

    "/p:DebugSymbols=false"

    "-o", $OutDir

)



if ($SingleFile) {

    Write-Host "Modo: executavel unico (mais lento no primeiro start)" -ForegroundColor Cyan

    $args += @("/p:PublishSingleFile=true", "/p:IncludeNativeLibrariesForSelfExtract=true", "/p:EnableCompressionInSingleFile=true")

} else {

    Write-Host "Modo: pasta com DLLs (inicio rapido, recomendado para WPF)" -ForegroundColor Cyan

}



& dotnet @args

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }



Write-Host ""

Write-Host "Concluido. Execute: $OutDir\NeoVision.exe" -ForegroundColor Green

Write-Host "Para um Setup.exe, instale Inno Setup e compile build\NeoVision-Setup.iss" -ForegroundColor DarkGray


