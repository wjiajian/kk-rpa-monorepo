[CmdletBinding()]
param(
    [ValidateSet('Install', 'Status', 'Remove')]
    [string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Run this command as the Windows desktop user who configured the executor.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskName = 'KK-RPA-Executor-' + $identity.User.Value
$description = 'KK RPA desktop executor. Managed by packages/rpa-executor/autostart.ps1.'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) {
    throw 'A different task uses this name. Inspect it in Task Scheduler before continuing.'
}
if ($Action -eq 'Status') {
    if ($existing) {
        $existing | Select-Object TaskName, State
        Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime, LastTaskResult, NextRunTime
    } else { Write-Host 'Desktop autostart is not installed.' }
    return
}
if ($Action -eq 'Remove') {
    if ($existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    Write-Host 'Autostart registration removed. Existing executor processes are not stopped.'
    return
}
foreach ($name in @('config.local.toml', 'credentials.local.clixml', '.venv/Scripts/python.exe')) {
    if (-not (Test-Path (Join-Path $PSScriptRoot $name))) {
        throw 'Run start.ps1 interactively and confirm the robot connection before installing autostart.'
    }
}
$runner = Join-Path $PSScriptRoot 'startup-runner.ps1'
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '"'
$taskAction = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Principal $principal `
    -Settings $settings -Description $description -Force | Out-Null
Write-Host 'Autostart installed for this desktop user. It starts at the next login; no executor was launched now.'
