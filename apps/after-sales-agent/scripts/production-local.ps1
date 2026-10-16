[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'RestoreDevelopment')][string]$Action = 'Status',
    [switch]$EnableVerification
)

$ErrorActionPreference = 'Stop'
$applicationRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $applicationRoot '../..')).Path
$upstreamRoot = Join-Path $workspaceRoot 'vendor/deer-flow'
function Wait-ProductionReady {
    $deadline = (Get-Date).AddSeconds(50)
    do {
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:2026/health' -TimeoutSec 2
            $login = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:2026/login' -TimeoutSec 2
            if ($health.StatusCode -eq 200 -and $login.StatusCode -eq 200) {
                Write-Host 'Production Gateway and frontend ready: HTTP 200.'
                return
            }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'Production readiness timed out; containers/data preserved. Read logs and actual health before retrying; do not rebuild blindly.'
}
function Save-RuntimeLogs {
    & docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker daemon unavailable; no restart performed.' }
    $archive = Join-Path $applicationRoot ('.local/runtime-log-archive/' + (Get-Date -Format 'yyyyMMddTHHmmssfff'))
    New-Item -ItemType Directory -Path $archive -Force | Out-Null
    foreach ($name in @('gateway.log', 'frontend.log')) {
        $source = Join-Path $upstreamRoot "logs/$name"
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $archive }
    }
    # Production Gateway logs to stdout, while development logs to a file.
    # Preserve both sources before recreation instead of assuming one sink.
    foreach ($name in @('gateway', 'frontend', 'nginx')) {
        & docker container inspect "deer-flow-$name" --format '{{.Id}}' 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            # Fresh installation has no previous container logs to archive.
            Write-Host "No prior deer-flow-$name container; skipping its log archive."
            continue
        }
        & docker logs --timestamps "deer-flow-$name" 2>&1 | Out-File -Encoding utf8 (Join-Path $archive "$name-container.log")
        if ($LASTEXITCODE -ne 0) { throw "Cannot archive $name logs; no restart performed." }
    }
    Write-Host "Archived runtime logs: $archive"
}
$commit = & git -C $upstreamRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $commit.Trim() -ne '345f08be00c8a9495079b732a39b46aa9af1584e') {
    throw 'Unexpected pinned base; no services changed.'
}

if ($Action -eq 'RestoreDevelopment') {
    # Archive the actual file logs before either container is recreated.
    Save-RuntimeLogs
    & (Join-Path $PSScriptRoot 'local.ps1') -Action RestartGateway
    & (Join-Path $PSScriptRoot 'local.ps1') -Action RestartFrontend
    & (Join-Path $PSScriptRoot 'local.ps1') -Action Start
    exit 0
}

$savedRoot = $env:DEER_FLOW_ROOT
$savedApp = $env:AFTER_SALES_APP_ROOT
$savedVerification = $env:AFTER_SALES_ENABLE_VERIFICATION
try {
    $env:DEER_FLOW_ROOT = $upstreamRoot.Replace('\', '/')
    $env:AFTER_SALES_APP_ROOT = $applicationRoot.Replace('\', '/')
    $env:AFTER_SALES_ENABLE_VERIFICATION = if ($EnableVerification) { 'true' } else { 'false' }
    $compose = @('compose', '--project-name', 'after-sales-agent', '--env-file', (Join-Path $upstreamRoot '.env'),
        '--file', (Join-Path $upstreamRoot 'docker/docker-compose-dev.yaml'),
        '--file', (Join-Path $applicationRoot 'docker/compose.business.yaml'),
        '--file', (Join-Path $applicationRoot 'docker/compose.production-local.yaml'))
    if ($Action -eq 'Status') {
        & docker @compose ps
    } else {
        & docker image inspect 'after-sales-agent-frontend:production-check-20261014' --format '{{.Id}}'
        if ($LASTEXITCODE -ne 0) { throw 'Verified production image missing; no services changed.' }
        Save-RuntimeLogs
        # No build/pull or data initialization during the runtime switch.
        & docker @compose up -d --no-build --pull never --no-deps --force-recreate gateway frontend nginx
    }
    if ($LASTEXITCODE -ne 0) { throw "Production-local $Action failed; inspect logs before retrying." }
    if ($Action -eq 'Start') { Wait-ProductionReady }
} finally {
    $env:DEER_FLOW_ROOT = $savedRoot
    $env:AFTER_SALES_APP_ROOT = $savedApp
    $env:AFTER_SALES_ENABLE_VERIFICATION = $savedVerification
}
