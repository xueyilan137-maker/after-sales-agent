[CmdletBinding()]
param(
    [ValidateSet('Setup', 'ConfigureBusiness', 'RestoreBusinessConfig', 'BackupBusiness', 'TestEngineering', 'Build', 'BuildFrontend', 'Start', 'Stop', 'Status', 'Logs', 'RestartGateway', 'RestartFrontend')]
    [string]$Action = 'Status',
    [string]$BackupSuffix,
    [switch]$EnableVerification
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$applicationRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$upstreamRoot = Join-Path $workspaceRoot 'vendor/deer-flow'
$expectedCommit = '345f08be00c8a9495079b732a39b46aa9af1584e'
$actualCommit = & git -C $upstreamRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualCommit.Trim() -ne $expectedCommit) {
    throw "Expected DeerFlow v2.1.0 commit $expectedCommit. See the progress record before changing the base."
}

if ($Action -in @('Setup', 'ConfigureBusiness', 'Build', 'BuildFrontend', 'Start', 'RestartGateway', 'RestartFrontend')) {
    $runtimePatchPath = Join-Path $applicationRoot 'patches/deerflow-v2.1.0-csrf-recovery.patch'
    if (-not (Test-Path -LiteralPath $runtimePatchPath)) {
        throw 'Missing maintained DeerFlow CSRF recovery patch.'
    }
    & git -C $upstreamRoot apply --reverse --check -- $runtimePatchPath 2>$null
    $patchAlreadyApplied = $LASTEXITCODE -eq 0
    if (-not $patchAlreadyApplied) {
        & git -C $upstreamRoot apply --check -- $runtimePatchPath
        if ($LASTEXITCODE -ne 0) {
            throw 'The maintained CSRF patch conflicts with this checkout. Existing edits were kept.'
        }
        & git -C $upstreamRoot apply -- $runtimePatchPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not apply the maintained CSRF patch.' }
        Write-Host 'Applied the after-sales CSRF recovery adaptation to the pinned base.'
    }
}

if ($Action -in @('Setup', 'Build')) {
    # Derive only the local build recipe. The original upstream Dockerfile stays
    # unchanged; dependency lockfiles still come from the pinned build context.
    $upstreamDockerfile = [System.IO.File]::ReadAllText((Join-Path $upstreamRoot 'backend/Dockerfile'))
    $originalAptPrefix = 'RUN apt-get update && apt-get install -y'
    if (-not $upstreamDockerfile.Contains($originalAptPrefix)) {
        throw 'The pinned Dockerfile no longer matches the local HTTPS adaptation.'
    }
    $localAptPrefix = @'
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y
'@
    $localDockerfile = $upstreamDockerfile.Replace($originalAptPrefix, $localAptPrefix)
    $localDockerfile = $localDockerfile.Replace('&& apt-get update', '&& apt-get -o Acquire::Retries=3 update')
    $localDockerfile = $localDockerfile.Replace('&& apt-get install -y nodejs', '&& apt-get -o Acquire::Retries=3 install -y nodejs')
    $localDockerfile = $localDockerfile.Replace('curl -fsSL https://deb.nodesource.com/', 'curl -fsSL --retry 3 --connect-timeout 20 --max-time 120 https://deb.nodesource.com/')
    $localBuildDir = Join-Path $applicationRoot '.local'
    New-Item -ItemType Directory -Path $localBuildDir -Force | Out-Null
    $provenance = "# Derived from bytedance/deer-flow $expectedCommit (MIT).`n# Local changes: HTTPS APT sources and bounded download retries.`n"
    [System.IO.File]::WriteAllText((Join-Path $localBuildDir 'backend.Dockerfile'), $provenance + $localDockerfile, [System.Text.UTF8Encoding]::new($false))
}

if ($Action -eq 'Setup') {
    # Existing operator configuration is kept on repeated Setup runs.
    $copies = @(
        @('config/deerflow.deepseek.example.yaml', 'config.yaml'),
        @('config/deepseek.env.example', '.env'),
        @('config/extensions.docker.example.json', 'extensions_config.json')
    )
    foreach ($pair in $copies) {
        $destination = Join-Path $upstreamRoot $pair[1]
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath (Join-Path $applicationRoot $pair[0]) -Destination $destination
            Write-Host "Created local $($pair[1])"
        } else {
            Write-Host "Kept existing local $($pair[1])"
        }
    }
    $frontendEnv = Join-Path $upstreamRoot 'frontend/.env'
    if (-not (Test-Path -LiteralPath $frontendEnv)) {
        Copy-Item -LiteralPath (Join-Path $upstreamRoot 'frontend/.env.example') -Destination $frontendEnv
    }
    New-Item -ItemType Directory -Path (Join-Path $upstreamRoot 'logs') -Force | Out-Null
    Write-Host "Edit DEEPSEEK_API_KEY in $upstreamRoot/.env before using chat."
    exit 0
}

foreach ($requiredFile in @('config.yaml', '.env', 'extensions_config.json', 'frontend/.env')) {
    if (-not (Test-Path -LiteralPath (Join-Path $upstreamRoot $requiredFile))) {
        throw "Missing local $requiredFile. Run this script with -Action Setup first."
    }
}

$savedUpstreamRoot = $env:DEER_FLOW_ROOT
$savedApplicationRoot = $env:AFTER_SALES_APP_ROOT
$savedVerification = $env:AFTER_SALES_ENABLE_VERIFICATION
$env:AFTER_SALES_ENABLE_VERIFICATION = if ($EnableVerification) { 'true' } else { 'false' }
try {
    $env:DEER_FLOW_ROOT = $upstreamRoot.Replace('\', '/')
    $env:AFTER_SALES_APP_ROOT = $applicationRoot.Replace('\', '/')
    $composeArgs = @(
        'compose', '--project-name', 'after-sales-agent',
        '--env-file', (Join-Path $upstreamRoot '.env'),
        '--file', (Join-Path $upstreamRoot 'docker/docker-compose-dev.yaml'),
        '--file', (Join-Path $applicationRoot 'docker/compose.business.yaml')
    )
    switch ($Action) {
        'ConfigureBusiness' { & docker exec deer-flow-gateway /app/backend/.venv/bin/python /app/business-mcp/configure_business.py }
        'RestoreBusinessConfig' {
            if ($BackupSuffix -notmatch '^\.before-business-[0-9]{8}T[0-9]{12}$') { throw 'Provide the exact saved .before-business timestamp suffix with -BackupSuffix.' }
            & docker exec deer-flow-gateway /app/backend/.venv/bin/python /app/business-mcp/configure_business.py --restore-suffix $BackupSuffix
        }
        'BackupBusiness' { & docker exec -e PYTHONPATH=/app/backend deer-flow-gateway /app/backend/.venv/bin/python /app/business-mcp/maintenance.py }
        'TestEngineering' {
            & docker cp (Join-Path $applicationRoot 'tests/.') 'deer-flow-gateway:/tmp/after-sales-verification'
            if ($LASTEXITCODE -ne 0) { throw 'Could not copy isolated verification scripts.' }
            & docker exec -e PYTHONPATH=/tmp/after-sales-verification:/app/backend deer-flow-gateway /app/backend/.venv/bin/python -m unittest discover -s /tmp/after-sales-verification -p 'test_*.py' -v
        }
        'Build' { & docker @composeArgs build gateway frontend }
        'BuildFrontend' { & docker @composeArgs build frontend }
        'Start' { & docker @composeArgs up -d redis gateway frontend nginx }
        'Stop' { & docker @composeArgs stop redis gateway frontend nginx }
        'Status' { & docker @composeArgs ps }
        'Logs' { & docker @composeArgs logs --tail 80 gateway frontend nginx }
        'RestartGateway' { & docker @composeArgs up -d --no-deps --force-recreate gateway }
        'RestartFrontend' { & docker @composeArgs up -d --no-deps --force-recreate frontend }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose $Action failed with exit code $LASTEXITCODE."
    }
    if ($Action -in @('Start', 'RestartGateway')) {
        Write-Host 'Waiting for Gateway health readiness (up to 50 seconds); this does not check business workflows or frontend compilation.'
        $gatewayReadinessProbe = @'
import sys,time,urllib.request
deadline=time.monotonic()+50
while time.monotonic()<deadline:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=2) as response:
            if response.status==200:
                print('Gateway health HTTP 200. Frontend and business workflow readiness are separate.')
                sys.exit(0)
    except OSError:
        pass
    time.sleep(1)
print('Gateway did not become healthy before the readiness deadline.',file=sys.stderr)
sys.exit(1)
'@
        & docker exec deer-flow-gateway /app/backend/.venv/bin/python -c $gatewayReadinessProbe
        if ($LASTEXITCODE -ne 0) { throw 'Gateway readiness was not confirmed. Read current logs; existing accounts and volumes were preserved.' }
    }
} finally {
    $env:DEER_FLOW_ROOT = $savedUpstreamRoot
    $env:AFTER_SALES_APP_ROOT = $savedApplicationRoot
    $env:AFTER_SALES_ENABLE_VERIFICATION = $savedVerification
}
