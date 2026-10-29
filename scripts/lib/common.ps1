# Shared helpers for the scripts in scripts\ (dot-source: . "$PSScriptRoot\lib\common.ps1").
# Windows PowerShell 5.1 compatible.

# $PSScriptRoot is scripts\lib when this file is dot-sourced
$script:Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$script:Backend = Join-Path $Repo 'backend'
$script:Python = Join-Path $Backend '.venv\Scripts\python.exe'
$script:Logs = Join-Path $Repo 'logs'
$script:Processes = @('ingest', 'alerts', 'mailer', 'worker', 'api')   # start order, design/01 §1.7.4 step 5

function Read-DotEnv {
    param([string]$Path = (Join-Path $Repo '.env'))
    $values = @{}
    if (-not (Test-Path $Path)) { return $null }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    $values
}

function Get-DbPassword([hashtable]$EnvValues) {
    if ($EnvValues['DATABASE_URL'] -match '^postgresql://[^:]+:([^@]+)@') { return $Matches[1] }
    $null
}

function Test-LocalHost([string]$HostName) {
    @('localhost', '127.0.0.1', '::1') -contains $HostName
}

function Test-PortListening([int]$Port) {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-AliveProcess([string]$PidFile) {
    if (-not (Test-Path $PidFile)) { return $null }
    $id = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $id) { return $null }
    Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
}

function Stop-ProcessTree([int]$Id) {
    # backend\.venv\Scripts\python.exe is a launcher that starts the real interpreter as a child
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$Id" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessTree $_.ProcessId }
    Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
}

function Get-PostgresService {
    Get-Service | Where-Object { $_.Name -like 'postgresql*' } | Sort-Object Name -Descending | Select-Object -First 1
}

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

# psql: from PATH, else from the PostgreSQL install folder (PATH changes need a new terminal)
$script:Psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $Psql) {
    $script:Psql = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}

function Invoke-Psql([string]$Database, [string]$Sql, [hashtable]$EnvValues) {
    $env:PGPASSWORD = Get-DbPassword $EnvValues
    try { & $Psql -U ews -h localhost -d $Database -X -A -t -c $Sql 2>&1 }
    finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
}
