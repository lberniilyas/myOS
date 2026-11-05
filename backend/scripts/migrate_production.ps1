# Creates or updates the tables in your hosted database (Neon on Vercel, or any PostgreSQL).
# Run it once after creating the database, and again after any change to the schema.
#
#   cd backend
#   .\scripts\migrate_production.ps1
#
# When asked, paste the connection string; it isn't echoed and is never written to disk.
param([string]$Url)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $Url) {
    $secure = Read-Host "Paste the database connection string (Vercel: Storage > your database > DATABASE_URL_UNPOOLED)" -AsSecureString
    $Url = [System.Net.NetworkCredential]::new("", $secure).Password
}
$url = $Url.Trim()
if (-not $url) { throw "No connection string given." }

$env:DATABASE_URL = $url
try {
    .\.venv\Scripts\python.exe -m alembic upgrade head
    Write-Host "Database is up to date."
} finally {
    Remove-Item Env:DATABASE_URL
}
