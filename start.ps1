# Starts everything for local use: dev database, migrations, web app build, API server.
# Run from PowerShell:  .\start.ps1     then open http://localhost:8000
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")

if (-not (Test-Path ".venv")) { uv sync }
if (-not (Test-Path ".devdb\data\PG_VERSION")) { python scripts\devdb.py init } else { python scripts\devdb.py start }
.\.venv\Scripts\python.exe -m alembic upgrade head

if (-not (Test-Path "..\frontend\dist\index.html")) {
    Push-Location "..\frontend"
    npm install
    npm run build
    Pop-Location
}

if (-not (Test-Path ".env")) { Write-Warning "No backend\.env yet: copy .env.example to .env and add GEMINI_API_KEY to enable AI." }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
