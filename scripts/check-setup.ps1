<#
.SYNOPSIS
  Checks the installation without starting anything (design/14 §14.1.3, NFR-05). Every line must say OK.
#>
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\common.ps1"

$rows = New-Object System.Collections.ArrayList
function Add-Row([string]$Check, [bool]$Ok, [string]$Detail) {
    [void]$rows.Add([pscustomobject]@{ Result = $(if ($Ok) { 'OK' } else { 'FAIL' }); Check = $Check; Detail = $Detail })
}

# Python, Node versions (DD127, DD129)
$pyVersion = ''
if (Test-Path $Python) { $pyVersion = (& $Python --version 2>&1) -join '' }
Add-Row 'Python 3.13.x (backend\.venv)' ($pyVersion -match '^Python 3\.13\.') $pyVersion
$nodeVersion = ''
if (Get-Command node -ErrorAction SilentlyContinue) { $nodeVersion = (node --version) }
Add-Row 'Node 24.x' ($nodeVersion -match '^v24\.') $nodeVersion

# .env: present, every variable of .env.example set
$envValues = Read-DotEnv
$example = Read-DotEnv (Join-Path $Repo '.env.example')
if ($null -eq $envValues) {
    Add-Row '.env' $false 'missing: copy .env.example to .env'
    $envValues = @{}
} else {
    $optional = @('SMTP_USER', 'SMTP_PASSWORD', 'DEV_ORIGINS')
    $unset = @($example.Keys | Where-Object { -not $envValues.ContainsKey($_) -or (-not $envValues[$_] -and $optional -notcontains $_) } | Sort-Object)
    Add-Row '.env' ($unset.Count -eq 0) $(if ($unset) { "not set: $($unset -join ', ')" } else { "$($envValues.Count) variables" })
}

# PostgreSQL: service, login as ews to the three databases
$pg = Get-PostgresService
Add-Row 'PostgreSQL service' ($pg -and $pg.Status -eq 'Running') $(if ($pg) { "$($pg.Name): $($pg.Status)" } else { 'not installed' })
$databases = @('ews', 'ews_test', 'ews_demo')
foreach ($db in $databases) {
    $ext = @(Invoke-Psql $db "SELECT string_agg(extname || ' ' || extversion, ', ' ORDER BY extname) FROM pg_extension WHERE extname IN ('timescaledb', 'citext')" $envValues) -join ' '
    $loginOk = $LASTEXITCODE -eq 0
    Add-Row "Login as ews: $db" $loginOk $(if ($loginOk) { 'OK' } else { $ext })
    Add-Row "Extensions: $db" ($loginOk -and $ext -match 'citext' -and $ext -match 'timescaledb') $ext
}

# TimescaleDB features (DD113, week-1 check 1)
$out = @(Invoke-Psql 'ews_test' "\i '$((Join-Path $PSScriptRoot 'sql\timescale-check.sql') -replace '\\', '/')'" $envValues) -join ' '
Add-Row 'TimescaleDB features (ews_test)' ($out -match 'TIMESCALE CHECK OK') $(if ($out -match 'TIMESCALE CHECK OK') { ($out -split 'OK')[0] -replace '\s+', ' ' | ForEach-Object { $_.Substring(0, [Math]::Min(60, $_.Length)) } } else { $out.Substring(0, [Math]::Min(200, $out.Length)) })

# Demo policies (DD107) and demo marker (DD95)
$jobs = (@(Invoke-Psql 'ews_demo' "SELECT count(*) FROM timescaledb_information.jobs WHERE proc_name IN ('policy_retention', 'policy_compression')" $envValues) -join '').Trim()
Add-Row 'Demo policies: none in ews_demo' ($jobs -eq '0') "retention/compression jobs: $jobs"
$markers = @()
foreach ($db in $databases) {
    $value = (@(Invoke-Psql $db "SELECT coalesce(current_setting('ews.is_demo', true), 'off')" $envValues) -join '').Trim()
    $markers += "${db}=$value"
}
Add-Row 'Demo marker only in ews_demo' (($markers -join ' ') -eq 'ews=off ews_test=off ews_demo=on') ($markers -join ', ')

# Mosquitto: service, settings (DD109), logins (Python part below)
$mq = Get-Service mosquitto -ErrorAction SilentlyContinue
Add-Row 'Mosquitto service' ($mq -and $mq.Status -eq 'Running') $(if ($mq) { "$($mq.Status)" } else { 'not installed' })
$confD = Join-Path $Repo 'config\mosquitto\conf.d'
$serviceConf = 'C:\Program Files\mosquitto\mosquitto.conf'
$included = (Test-Path $serviceConf) -and (@(Get-Content $serviceConf) -contains "include_dir $confD")
$ewsConf = Join-Path $confD 'ews.conf'
$conf = @(); if (Test-Path $ewsConf) { $conf = Get-Content $ewsConf }
$settingsOk = $included -and ($conf -contains 'max_queued_messages 0') -and ($conf -contains 'persistence true') -and ($conf -contains 'allow_anonymous false')
Add-Row 'Mosquitto settings (include, persistence, max_queued_messages 0)' $settingsOk $(if ($included) { 'ews.conf included' } else { 'include_dir line missing in mosquitto.conf' })

# Mailpit or a real SMTP server
$mailpit = Test-Path (Join-Path $Repo 'tools\mailpit.exe')
$smtpLocal = Test-LocalHost $envValues['SMTP_HOST']
Add-Row 'Mailpit' ($mailpit -or -not $smtpLocal) $(if ($mailpit) { 'tools\mailpit.exe' } elseif (-not $smtpLocal) { "real SMTP: $($envValues['SMTP_HOST'])" } else { 'tools\mailpit.exe missing' })

# MQTT logins, Python packages, models
if (Test-Path $Python) {
    foreach ($line in & $Python (Join-Path $PSScriptRoot 'checks\setup_checks.py')) {
        $parts = $line -split "`t", 3
        if ($parts.Count -eq 3) { Add-Row $parts[1] ($parts[0] -eq 'OK') $parts[2] }
    }
} else {
    Add-Row 'Python packages' $false "missing $Python"
}

# Frontend build
Add-Row 'Frontend build' (Test-Path (Join-Path $Repo 'frontend\dist\index.html')) 'frontend\dist\index.html'

# Ports free (1883 and 5432 belong to the services); in use by our own running system counts as OK
$ours = @('python', 'mailpit')
foreach ($port in 8000, 1025, 8025) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { Add-Row "Port $port free" $true 'free'; continue }
    $owner = (Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Add-Row "Port $port free" ($ours -contains $owner) "in use by $owner$(if ($ours -contains $owner) { ' (this system)' })"
}

$rows | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Host
$failed = @($rows | Where-Object Result -eq 'FAIL').Count
if ($failed) { Write-Host "$failed check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host 'All checks OK.' -ForegroundColor Green
exit 0
