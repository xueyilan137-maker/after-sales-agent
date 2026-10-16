[CmdletBinding()]
param(
    [string]$DependencyImage = 'after-sales-agent-frontend',
    [string]$OutputImage = 'after-sales-agent-frontend:production-check-20261014'
)
$ErrorActionPreference = 'Stop'
$applicationRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $applicationRoot '../..')).Path
$upstreamRoot = Join-Path $workspaceRoot 'vendor/deer-flow'
$expectedCommit = '345f08be00c8a9495079b732a39b46aa9af1584e'
$commit = & git -C $upstreamRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $commit.Trim() -ne $expectedCommit) { throw 'Unexpected base; no build started.' }
& git -C $upstreamRoot apply --reverse --check -- (Join-Path $applicationRoot 'patches/deerflow-v2.1.0-csrf-recovery.patch')
if ($LASTEXITCODE -ne 0) { throw 'Maintained CSRF patch is not applied; existing checkout kept.' }
& docker image inspect $DependencyImage --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Installed dependency image missing. Build the existing frontend development target first.' }

$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$evidence = Join-Path $applicationRoot ".local/production-build-$stamp"
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$containerName = "after-sales-production-build-$stamp".ToLowerInvariant()
$sourceImage = "after-sales-agent-frontend:source-$stamp".ToLowerInvariant()
& docker build --pull=false --network none --build-arg "DEPENDENCY_IMAGE=$DependencyImage" `
    --file (Join-Path $applicationRoot 'docker/frontend.production-source.Dockerfile') `
    --tag $sourceImage $upstreamRoot *> (Join-Path $evidence 'source-build.log')
if ($LASTEXITCODE -ne 0) { throw "Source/dependency consistency check failed; see $evidence" }

$buildConfig = Join-Path $applicationRoot 'docker/production-build'
& docker run --name $containerName --memory 3g --memory-swap 3g --cpus 2 --network none `
    --mount "type=bind,source=$buildConfig,target=/build-config,readonly" `
    $sourceImage sh /build-config/build.sh *> (Join-Path $evidence 'build.log')
$buildExit = $LASTEXITCODE
& docker inspect $containerName --format '{{json .State}}' | Set-Content (Join-Path $evidence 'container-state.json')
if ($buildExit -ne 0) { throw "Production build failed ($buildExit); container and evidence preserved: $evidence" }
& docker cp "${containerName}:/app/frontend/.next/BUILD_ID" (Join-Path $evidence 'BUILD_ID')
if ($LASTEXITCODE -ne 0) { throw 'Production BUILD_ID missing; no runtime image created.' }
& docker commit --change 'WORKDIR /app/frontend' --change 'ENV NODE_ENV=production' `
    --change 'CMD ["pnpm", "start"]' $containerName $OutputImage | Set-Content (Join-Path $evidence 'image-id.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not save runtime image; build container preserved.' }
& docker image inspect $OutputImage --format '{{.Id}} {{.Size}}' | Set-Content (Join-Path $evidence 'image-size.txt')
Write-Host "Production frontend built: $OutputImage"
Write-Host "Private evidence: $evidence"
Write-Host 'Existing running containers, accounts and business volumes were not changed.'
