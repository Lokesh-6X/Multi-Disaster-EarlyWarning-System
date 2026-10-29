<#
.SYNOPSIS
  Runs one backend process and restarts it 5 s after it exits (design/01 §1.7.4 step 5, design/14 §14.2.4).
.DESCRIPTION
  Started (hidden) by start.ps1 for each of ingest, alerts, mailer, worker, api.
  logs\<name>.pid          PID of the Python interpreter, written by the process itself (EWS_PID_FILE)
  logs\<name>.launcher.pid PID of backend\.venv\Scripts\python.exe (a launcher that starts the interpreter)
  logs\<name>.wrapper.pid  PID of this wrapper
  logs\<name>.stdout.log   stdout and stderr of each run, so a crash before logging starts is visible
  logs\<name>.stop         created by stop.ps1: do not restart
#>
param(
    [Parameter(Mandatory)][ValidateSet('ingest', 'alerts', 'mailer', 'worker', 'api')][string]$Name
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib\common.ps1"

New-Item -ItemType Directory -Force $Logs | Out-Null
$pidFile = Join-Path $Logs "$Name.pid"
$launcherPidFile = Join-Path $Logs "$Name.launcher.pid"
$wrapperPidFile = Join-Path $Logs "$Name.wrapper.pid"
$stopFlag = Join-Path $Logs "$Name.stop"
$stdoutLog = Join-Path $Logs "$Name.stdout.log"
Set-Content $wrapperPidFile $PID
Remove-Item $stopFlag -ErrorAction SilentlyContinue

function Add-Log([string]$Text) {
    Add-Content -Path $stdoutLog -Value "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss.fffK') [run-process] $Text" -Encoding UTF8
}

try {
    while ($true) {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Python
        $psi.Arguments = "-u -m ews.$Name"
        $psi.WorkingDirectory = $Backend
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.EnvironmentVariables['EWS_PID_FILE'] = $pidFile
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        $proc = [System.Diagnostics.Process]::Start($psi)
        Set-Content $launcherPidFile $proc.Id
        Add-Log "started ews.$Name (launcher pid $($proc.Id))"
        # Read both streams without blocking each other; written to the log when the process ends
        $out = $proc.StandardOutput.ReadToEndAsync()
        $err = $proc.StandardError.ReadToEndAsync()
        $proc.WaitForExit()
        $text = ($out.Result + $err.Result).TrimEnd()
        if ($text) { Add-Content -Path $stdoutLog -Value $text -Encoding UTF8 }
        Add-Log "ews.$Name exited with code $($proc.ExitCode)"
        if (Test-Path $stopFlag) { break }
        Add-Log 'restarting in 5 s'
        Start-Sleep -Seconds 5
        if (Test-Path $stopFlag) { break }
    }
} finally {
    Remove-Item $pidFile, $launcherPidFile, $wrapperPidFile, $stopFlag -ErrorAction SilentlyContinue
}
