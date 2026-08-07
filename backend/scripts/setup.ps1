# Configuración del ambiente de desarrollo de ContaMind AI (Windows/PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$venv = Join-Path $PSScriptRoot "..\.venv"
if (-not (Test-Path $venv)) {
    python -m venv $venv
}
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $PSScriptRoot "..\requirements-dev.txt")
