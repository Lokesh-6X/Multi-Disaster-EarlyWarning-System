<#
.SYNOPSIS
  Starts the whole system (design/01 §1.7.4, NFR-05).
.DESCRIPTION
  1 Load .env   2 services (PostgreSQL, Mosquitto, Mailpit)   3 database check, migrations, settings sync,
  -Seed import (only when no site exists)   4 frontend    5 the five processes through run-process.ps1   6 simulator   7 URLs
  The Windows services keep running after stop.ps1.
.EXAMPLE
  scripts\start.ps1
  scripts\start.ps1 -Dev
  scripts\start.ps1 -Seed config\example-site.yaml
  scripts\start.ps1 -Demo -Simulator squall
#>
param(
    [switch]$Dev,
    [string]$Simulator,
    [string]$Seed,
    [switch]$Demo,
    [switch]$Reset
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\common.ps1"
New-Item -ItemType Directory -Force $Logs | Out-Null

# --- 1 .env -----------------------------------------------------------------------------------
Write-Step 'Settings (.env)'
$envValues = Read-DotEnv
if ($null -eq $envValues) { throw ".env not found in $Repo. Copy .env.example to .env and fill in the passwords (docs\setup-guide.md)." }
if (-not (Test-Path $Python)) { throw "Python environment missing: $Python (docs\setup-guide.md §4)." }
if ($Demo) { $env:EWS_CLOCK = 'demo' } else { $env:EWS_CLOCK = 'real' }
if ($Dev) { $env:DEV_ORIGINS = 'http://localhost:5173' } else { $env:DEV_ORIGINS = '' }   # DD122
& $Python -c "from ews.common.settings import load_settings; load_settings()"
if ($LASTEXITCODE -ne 0) { throw 'Fix .env first (see the message above).' }
$smtpLocal = Test-LocalHost $envValues['SMTP_HOST']

# Guards that need no running system (requirements D39, DD125)
if ($Reset -and -not $Demo) { throw '-Reset only works with -Demo.' }
if ($Seed) {
    if (-not (Test-Path $Seed -PathType Leaf)) { throw "-Seed: file not found: $Seed" }
    $seedFile = (Resolve-Path $Seed).Path    # before the script moves into backend\
}
if ($Simulator) {
    $standIn = @('replay', 'normal') -contains $Simulator
    if (-not $Demo -and -not $standIn) { throw "Simulator scenario '$Simulator' needs -Demo: simulated hazards never run on the real installation (D39, DD125)." }
    if (-not $Demo -and -not $smtpLocal) { throw 'Without -Demo the stand-in kit runs only while SMTP_HOST is local (Mailpit), so no real person is emailed (DD125).' }
}

# --- 2 services -------------------------------------------------------------------------------
Write-Step 'Services'
foreach ($svc in @((Get-PostgresService), (Get-Service mosquitto -ErrorAction SilentlyContinue))) {
    if (-not $svc) { throw 'PostgreSQL or Mosquitto service not installed (docs\setup-guide.md §1).' }
    if ($svc.Status -ne 'Running') {
        Write-Host "  starting $($svc.Name) ..."
        try { Start-Service $svc.Name } catch { throw "$($svc.Name) is not running and could not be started; start it from an administrator PowerShell: Start-Service $($svc.Name)" }
    }
    Write-Host "  $($svc.Name): running"
}
if ($smtpLocal) {
    $mailpit = Join-Path $Repo 'tools\mailpit.exe'
    $mailpitPid = Join-Path $Logs 'mailpit.pid'
    if (Test-PortListening ([int]$envValues['SMTP_PORT'])) {
        Write-Host "  mailpit: already listening on $($envValues['SMTP_PORT'])"
    } elseif (Test-Path $mailpit) {
        $p = Start-Process -FilePath $mailpit -ArgumentList '--smtp', "127.0.0.1:$($envValues['SMTP_PORT'])", '--listen', '127.0.0.1:8025' `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Logs 'mailpit.stdout.log') -RedirectStandardError (Join-Path $Logs 'mailpit.stderr.log')
        Set-Content $mailpitPid $p.Id
        Write-Host "  mailpit: started (pid $($p.Id))"
    } else {
        Write-Warning "tools\mailpit.exe missing: emails cannot be sent (docs\setup-guide.md §1.6)"
    }
}

# --- 3 database -------------------------------------------------------------------------------
Write-Step 'Database'
Push-Location $Backend
try {
    & $Python -m ews.common.db check
    if ($LASTEXITCODE -ne 0) { throw 'Database check failed (see above).' }
    if ($Reset) { Write-Warning '-Reset: the demo snapshot (build-demo-snapshot.ps1) arrives in M9; continuing with the current demo database.' }
    & (Join-Path $Backend '.venv\Scripts\alembic.exe') upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head failed.' }
    & $Python -m ews.common.config sync    # DD110: before any process starts
    if ($LASTEXITCODE -ne 0) { throw 'Settings catalogue sync failed.' }
    if ($Seed) {
        # 04 §4.6, DD132: imports the site file only when no site exists yet (all or nothing)
        & $Python -m ews.common.config_import $seedFile --if-no-site --reason "start.ps1 -Seed $Seed"
        if ($LASTEXITCODE -ne 0) { throw "-Seed ${Seed}: nothing imported (see the problems above)." }
    }
} finally {
    Pop-Location
}

# --- 4 frontend -------------------------------------------------------------------------------
Write-Step 'Frontend'
$frontend = Join-Path $Repo 'frontend'
if ($Dev) {
    $vitePid = Join-Path $Logs 'vite.pid'
    if (Get-AliveProcess $vitePid) {
        Write-Host '  vite dev server: already running'
    } else {
        $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev' -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Logs 'vite.stdout.log') -RedirectStandardError (Join-Path $Logs 'vite.stderr.log')
        Set-Content $vitePid $p.Id
        Write-Host "  vite dev server: started (pid $($p.Id)) on http://localhost:5173"
    }
} else {
    $index = Join-Path $frontend 'dist\index.html'
    $newest = Get-ChildItem (Join-Path $frontend 'src'), (Join-Path $frontend 'index.html'), (Join-Path $frontend 'package.json') -Recurse -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not (Test-Path $index) -or (Get-Item $index).LastWriteTime -lt $newest.LastWriteTime) {
        Write-Host '  building frontend ...'
        Push-Location $frontend
        try {
            if (-not (Test-Path 'node_modules')) { npm ci --no-fund --no-audit | Out-Host }
            npm run build | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    } else {
        Write-Host '  frontend build is up to date'
    }
}

# --- 5 processes ------------------------------------------------------------------------------
Write-Step "Processes (clock: $env:EWS_CLOCK)"
foreach ($name in $Processes) {
    if (Get-AliveProcess (Join-Path $Logs "$name.wrapper.pid")) {
        Write-Host "  ${name}: already running"
        continue
    }
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\run-process.ps1`"", '-Name', $name | Out-Null
    Write-Host "  ${name}: started"
}

# --- 6 simulator ------------------------------------------------------------------------------
if ($Simulator -eq 'normal') {
    # stand-in kit on the real clock (design/11 §11.4.0, DD125); scenarios and the demo clock come in M2.8
    $simPid = Join-Path $Logs 'simulator.pid'
    if (Get-AliveProcess $simPid) {
        Write-Host '  simulator: already running'
    } else {
        $p = Start-Process -FilePath $Python -ArgumentList '-m', 'simulator', 'run' -WorkingDirectory (Join-Path $Repo 'simulator') `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Logs 'simulator.stdout.log') -RedirectStandardError (Join-Path $Logs 'simulator.stderr.log')
        Set-Content $simPid $p.Id
        Write-Host "  simulator: started (pid $($p.Id)), normal weather for the kits in simulator\config.yaml"
    }
} elseif ($Simulator) {
    Write-Warning "-Simulator $Simulator : only 'normal' is started for now (replay by hand: python -m simulator run --replay ...; scenarios arrive in M2.8)."
}

# Wait for the five heartbeats (DD12)
$database = 'ews'; if ($Demo) { $database = 'ews_demo' }
$deadline = (Get-Date).AddSeconds(45)
$beating = @()
while ((Get-Date) -lt $deadline) {
    $beating = @(Invoke-Psql $database "SELECT name FROM process_heartbeat WHERE last_beat_at > now() - interval '30 seconds' ORDER BY name" $envValues |
        Where-Object { $_ -is [string] -and $_ })
    if ($beating.Count -ge $Processes.Count) { break }
    Start-Sleep -Seconds 1
}
$missing = $Processes | Where-Object { $beating -notcontains $_ }
if ($missing) {
    Write-Warning "No heartbeat yet from: $($missing -join ', '). See logs\<name>.log and logs\<name>.stdout.log."
} else {
    Write-Host "  heartbeats: $($beating -join ', ')"
}

# --- 7 URLs -----------------------------------------------------------------------------------
Write-Step 'Running'
if ($Dev) { Write-Host '  Dashboard (dev):  http://localhost:5173' } else { Write-Host '  Dashboard:        http://localhost:8000' }
if ($smtpLocal) { Write-Host '  Mailpit inbox:    http://localhost:8025' }
Write-Host '  Logs:             logs\<process>.log   Stop: scripts\stop.ps1'
