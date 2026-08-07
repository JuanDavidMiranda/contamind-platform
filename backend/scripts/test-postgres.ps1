# Pruebas PostgreSQL opt-in (requieren el contenedor de contamind-db).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$env:RUN_POSTGRES_TESTS = "1"
if (-not $env:POSTGRES_TEST_DATABASE_URL) {
    $env:POSTGRES_TEST_DATABASE_URL = "postgresql+psycopg2://contamind:contamind@localhost:5433/contamind"
}
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pytest -m postgres $args
