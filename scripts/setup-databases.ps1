<#
.SYNOPSIS
  One-time database setup (design/14 §14.1.2 step 3, M0.2).
.DESCRIPTION
  Restarts PostgreSQL so TimescaleDB is loaded, then creates role ews and the databases
  ews, ews_test, ews_demo with the timescaledb and citext extensions.
  The ews password is generated once and kept in .env (DATABASE_URL, DEMO_DATABASE_URL); it is never printed.
  Run from an administrator PowerShell; psql asks for the postgres password.
#>
param(
    [string]$Service = 'postgresql-x64-17'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $repo '.env'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Run this script from an administrator PowerShell (it restarts the PostgreSQL service).' }
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) { throw 'psql not found on PATH; see docs/setup-guide.md step 1.3.' }

# Reuse the ews password from .env if it is already there, else generate one
$lines = @(if (Test-Path $envFile) { Get-Content $envFile })
$existing = $lines | Where-Object { $_ -match '^DATABASE_URL=postgresql://ews:([^@]+)@' } | Select-Object -First 1
if ($existing -and $existing -match '^DATABASE_URL=postgresql://ews:([^@]+)@') {
    $password = $Matches[1]
    Write-Host 'Using the ews password already in .env'
} else {
    $chars = [char[]]'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
    Write-Host 'Generated a new ews password (stored in .env)'
}

Write-Host "Restarting $Service so TimescaleDB is loaded ..."
Restart-Service $Service
(Get-Service $Service).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))

$env:EWS_DB_PASSWORD = $password
try {
    psql -U postgres -h localhost -d postgres -v ON_ERROR_STOP=1 -f (Join-Path $PSScriptRoot 'sql\create-databases.sql')
    if ($LASTEXITCODE -ne 0) { throw "psql failed (exit code $LASTEXITCODE)" }
} finally {
    Remove-Item Env:EWS_DB_PASSWORD -ErrorAction SilentlyContinue
}

# Write or replace the two database lines in .env (other lines are kept)
$wanted = [ordered]@{
    'DATABASE_URL'      = "postgresql://ews:$password@localhost:5432/ews"
    'DEMO_DATABASE_URL' = "postgresql://ews:$password@localhost:5432/ews_demo"
}
foreach ($key in $wanted.Keys) {
    $line = "$key=$($wanted[$key])"
    if ($lines | Where-Object { $_ -match "^$key=" }) {
        # @() keeps a one-line file an array, so += below adds a line instead of joining strings
        $lines = @($lines | ForEach-Object { if ($_ -match "^$key=") { $line } else { $_ } })
    } else {
        $lines += $line
    }
}
# UTF-8 without BOM (Windows PowerShell 5.1 would add one, which breaks the first key)
[IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
Write-Host 'Done: role ews, databases ews / ews_test / ews_demo, extensions timescaledb + citext. .env updated.'
