<#
.SYNOPSIS
  Test runner (design/12 §12.2): scripts\test.ps1 [-Unit] [-Integration] [-Api] [-E2E] [-Frontend] [-Perf] [-Slow]
.DESCRIPTION
  Without switches: every suite except -Perf and -Slow. Suites that have no tests yet are reported and skipped.
  Integration tests use ews_test (each test in its own schema; leftovers in public are removed first).
  The second Mosquitto on port 1884 for MQTT integration tests is added with the first such tests (M1).
#>
param([switch]$Unit, [switch]$Integration, [switch]$Api, [switch]$E2E, [switch]$Frontend, [switch]$Perf, [switch]$Slow)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\common.ps1"

$chosen = @()
foreach ($s in 'Unit', 'Integration', 'Api', 'E2E', 'Frontend', 'Perf', 'Slow') {
    if ((Get-Variable $s).Value) { $chosen += $s }
}
if (-not $chosen) { $chosen = @('Unit', 'Integration', 'Api', 'E2E', 'Frontend') }

$pytestDirs = @{ Unit = 'tests/unit'; Integration = 'tests/integration'; Api = 'tests/api'; E2E = 'tests/e2e'; Perf = 'tests/perf' }
$results = [ordered]@{}
Push-Location $Backend
try {
    foreach ($suite in $chosen) {
        Write-Step "$suite tests"
        if ($suite -eq 'Frontend') {
            $pkg = Get-Content (Join-Path $Repo 'frontend\package.json') -Raw | ConvertFrom-Json
            if (-not ($pkg.scripts.PSObject.Properties.Name -contains 'test')) { $results[$suite] = 'no tests yet'; continue }
            Push-Location (Join-Path $Repo 'frontend')
            try { npm test --silent; $code = $LASTEXITCODE } finally { Pop-Location }
        } elseif ($suite -eq 'Slow') {
            & $Python -m pytest -m slow -q; $code = $LASTEXITCODE
        } else {
            $dir = $pytestDirs[$suite]
            if (-not (Test-Path $dir)) { $results[$suite] = 'no tests yet'; continue }
            & $Python -m pytest $dir -q -m 'not slow'; $code = $LASTEXITCODE
        }
        # pytest exit code 5 = no tests collected
        if ($code -eq 5) { $results[$suite] = 'no tests yet' }
        elseif ($code -eq 0) { $results[$suite] = 'passed' }
        else { $results[$suite] = "FAILED (exit $code)" }
    }
} finally {
    Pop-Location
}

Write-Step 'Summary'
$failed = $false
foreach ($k in $results.Keys) {
    $colour = 'Green'
    if ($results[$k] -like 'FAILED*') { $colour = 'Red'; $failed = $true } elseif ($results[$k] -eq 'no tests yet') { $colour = 'DarkGray' }
    Write-Host ("  {0,-12} {1}" -f $k, $results[$k]) -ForegroundColor $colour
}
if ($failed) { exit 1 }
exit 0
