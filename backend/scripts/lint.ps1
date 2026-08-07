# Lint con Ruff: solo reglas E9,F (errores reales, sin reforma de estilo).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m ruff check . --select E9,F
