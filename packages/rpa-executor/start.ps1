[CmdletBinding()]
param(
    [string]$ServerUrl,
    [switch]$Configure
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Run this launcher in the Windows desktop user session.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: winget install --id astral-sh.uv -e; then reopen PowerShell.'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$configPath = Join-Path $PSScriptRoot 'config.local.toml'
$credentialsPath = Join-Path $PSScriptRoot 'credentials.local.clixml'

# Keep each application in its own environment, with the shared local rpa-core.
foreach ($project in @(
    $PSScriptRoot,
    (Join-Path $repoRoot 'apps/inventory_jushuitan_export_stock'),
    (Join-Path $repoRoot 'apps/report_jingmai_export_product_detail')
)) {
    & uv sync --project $project --locked --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed: $project" }
}

if (-not $ServerUrl -and (-not (Test-Path $configPath) -or $Configure)) {
    $ServerUrl = Read-Host 'Console HTTPS URL from the Mac'
}
if ($ServerUrl) {
    $address = [Uri]$ServerUrl.Trim()
    if (-not $address.IsAbsoluteUri -or $address.Scheme -ne 'https' -or
        $address.UserInfo -or $address.Query -or $address.Fragment -or
        $address.AbsolutePath -ne '/') {
        throw 'Use the HTTPS origin only, e.g. https://your-domain.ngrok-free.dev'
    }
    $source = if (Test-Path $configPath) { $configPath } else { Join-Path $PSScriptRoot 'config.example.toml' }
    $content = [IO.File]::ReadAllText($source)
    $connection = 'server_url = "wss://' + $address.Authority + '/api/robots/connect"'
    $content = [Regex]::Replace($content, '(?m)^server_url\s*=.*$', $connection)
    [IO.File]::WriteAllText($configPath, $content, [Text.UTF8Encoding]::new($false))
}

if (-not (Test-Path $credentialsPath) -or $Configure) {
    $saved = @{}
    foreach ($field in @(
        @('RPA_ROBOT_CREDENTIAL', 'Robot connection credential', $true),
        @('INVENTORY_USERNAME', 'Inventory login username', $false),
        @('INVENTORY_PASSWORD', 'Inventory login password', $true),
        @('INVENTORY_EXPECTED_IDENTITY', 'Inventory visible account identity', $false),
        @('REPORT_USERNAME', 'Report login username', $false),
        @('REPORT_PASSWORD', 'Report login password', $true),
        @('REPORT_EXPECTED_IDENTITY', 'Report visible account identity', $false)
    )) {
        do {
            if ($field[2]) {
                $secret = Read-Host $field[1] -AsSecureString
            } else {
                $plain = Read-Host $field[1]
                $secret = if ($plain) { ConvertTo-SecureString $plain -AsPlainText -Force } else { [Security.SecureString]::new() }
                $plain = $null
            }
        } while ($secret.Length -eq 0)
        $saved[$field[0]] = $secret
    }
    # Windows DPAPI binds these SecureStrings to this user on this computer.
    $saved | Export-Clixml -LiteralPath $credentialsPath
}

$saved = Import-Clixml -LiteralPath $credentialsPath
$previous = @{}
try {
    foreach ($name in $saved.Keys) {
        if ($saved[$name] -isnot [Security.SecureString]) {
            throw 'Invalid credential file. Run again with -Configure.'
        }
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        $value = [Net.NetworkCredential]::new('', $saved[$name]).Password
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        $value = $null
    }
    Write-Host 'Starting executor. Account alias for both applications: STORE_001'
    & uv run --project $PSScriptRoot rpa-executor --config $configPath
    if ($LASTEXITCODE -ne 0) { throw 'Executor exited with an error. Existing run state is retained.' }
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
