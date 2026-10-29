<#
.SYNOPSIS
  Stops everything start.ps1 started (design/01 §1.7.4), using the PID files in logs\.
  The PostgreSQL and Mosquitto Windows services keep running.
#>
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\common.ps1"

foreach ($name in $Processes) {
    $wrapper = Get-AliveProcess (Join-Path $Logs "$name.wrapper.pid")
    $child = Get-AliveProcess (Join-Path $Logs "$name.pid")
    if (-not $wrapper -and -not $child) { Write-Host "  ${name}: not running"; continue }
    Set-Content (Join-Path $Logs "$name.stop") 'stop'      # tells run-process.ps1 not to restart
    if ($child) { Stop-ProcessTree $child.Id }
    $launcher = Get-AliveProcess (Join-Path $Logs "$name.launcher.pid")
    if ($launcher) { Stop-ProcessTree $launcher.Id }
    if ($wrapper) {
        if (-not $wrapper.WaitForExit(10000)) { Stop-Process -Id $wrapper.Id -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item (Join-Path $Logs "$name.pid"), (Join-Path $Logs "$name.launcher.pid"), (Join-Path $Logs "$name.wrapper.pid"),
        (Join-Path $Logs "$name.stop") -ErrorAction SilentlyContinue
    Write-Host "  ${name}: stopped"
}

foreach ($helper in @('mailpit', 'vite')) {
    $pidFile = Join-Path $Logs "$helper.pid"
    $p = Get-AliveProcess $pidFile
    if ($p) {
        # vite runs under cmd.exe: stop its child processes too
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  ${helper}: stopped"
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
