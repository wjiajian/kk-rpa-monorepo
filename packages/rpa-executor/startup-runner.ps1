[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$logDirectory = Join-Path $PSScriptRoot 'runtime/startup'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logPath = Join-Path $logDirectory ('executor-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
try {
    ('[{0}] Desktop executor starting.' -f (Get-Date -Format o)) | Out-File -LiteralPath $logPath -Append -Encoding utf8
    & (Join-Path $PSScriptRoot 'start.ps1') -Unattended -SkipSetup *>> $logPath
} catch {
    # Do not serialize invocation variables or DPAPI credential objects into logs.
    ('[{0}] Startup failed ({1}). Check saved configuration, uv, and the executor lock.' -f (Get-Date -Format o), $_.Exception.GetType().Name) |
        Out-File -LiteralPath $logPath -Append -Encoding utf8
    exit 1
}
