# Consume trabajos persistentes de sincronización externa.
# Usar --once desde un scheduler o dejarlo corriendo como proceso de worker.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m app.workers.provider_sync_worker $args
