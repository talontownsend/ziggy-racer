# Register / remove the auto-resume watcher as a per-user Scheduled Task so it survives a reboot.
# TALONSPC bugchecks every few days; without this the watcher dies with the session and the
# queue never starts. The task only STARTS THE WATCHER -- the watcher itself still has to pass
# every start condition (no game running, 30 min idle, foreground identified and not a game,
# queue has pending work), so a reboot can never by itself arm anything.
#
#   .\tools\register_auto_resume.ps1            register (ONLOGON, per-user, no elevation)
#   .\tools\register_auto_resume.ps1 -Remove    remove it
#   .\tools\register_auto_resume.ps1 -Status    show it

param([switch]$Remove, [switch]$Status)

$TaskName = 'FH6-AutoResume'
$Root     = Split-Path -Parent $PSScriptRoot
$Py       = 'C:\Users\Talon\myenv\Scripts\python.exe'
$Script   = Join-Path $Root 'tools\auto_resume.py'

if ($Status) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) {
        $t | Select-Object TaskName, State | Format-Table -AutoSize | Out-String | Write-Host
        (Get-ScheduledTaskInfo -TaskName $TaskName) |
            Select-Object LastRunTime, LastTaskResult, NextRunTime |
            Format-Table -AutoSize | Out-String | Write-Host
    } else { Write-Host "  '$TaskName' is not registered" }
    exit 0
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  removed '$TaskName'"
    exit 0
}

if (-not (Test-Path $Py))     { Write-Host "  MISSING interpreter: $Py"; exit 1 }
if (-not (Test-Path $Script)) { Write-Host "  MISSING watcher: $Script";  exit 1 }

$action  = New-ScheduledTaskAction -Execute $Py -Argument "`"$Script`" --watch" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# RestartCount/Interval: if the watcher dies, bring it back -- but it re-evaluates every start
# condition from scratch, so a restart can never resume a window that was already running.
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $set `
    -Description 'FH6 farm: start the live queue only when the machine is genuinely free (fail-closed).' `
    -Force | Out-Null
Write-Host "  registered '$TaskName' (ONLOGON, user $env:USERNAME)"
Write-Host "  it starts the WATCHER only; every start condition is still evaluated at poll time."
