[CmdletBinding()]
param(
    # Optional local Git source for an offline checkout verification.
    [string]$OfflineSource
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target = Join-Path $repoRoot 'vendor/deer-flow'
$expected = '345f08be00c8a9495079b732a39b46aa9af1584e'
$patchPath = Join-Path $repoRoot 'apps/after-sales-agent/patches/deerflow-v2.1.0-csrf-recovery.patch'
if (Test-Path -LiteralPath $target) {
    $head = & git -C $target rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne $expected) {
        throw 'Existing vendor checkout differs from the pinned commit. No reset or overwrite performed.'
    }
    Write-Host 'Kept existing pinned checkout. No checkout/reset performed.'
} else {
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    $source = if ($OfflineSource) { (Resolve-Path -LiteralPath $OfflineSource).Path } else { 'https://github.com/bytedance/deer-flow.git' }
    $cloneArgs = @('clone', '--no-checkout')
    if ($OfflineSource) { $cloneArgs += '--no-hardlinks' } else { $cloneArgs += '--filter=blob:none' }
    & git @cloneArgs -- $source $target
    if ($LASTEXITCODE -ne 0) { throw 'Clone failed. Partial checkout retained for inspection; no automatic retry.' }
    & git -C $target checkout --detach $expected
    if ($LASTEXITCODE -ne 0) { throw 'Pinned commit unavailable. Do not substitute latest.' }
}
$head = & git -C $target rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne $expected) { throw 'Pinned commit mismatch.' }
& git -C $target apply --reverse --check -- $patchPath 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Maintained CSRF patch already applied.'
} else {
    & git -C $target apply --check -- $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'Patch conflicts with local edits. Existing files preserved.' }
    & git -C $target apply -- $patchPath
    if ($LASTEXITCODE -ne 0) { throw 'Patch application failed; inspect before continuing.' }
}
Write-Host 'Pinned source and CSRF patch ready. No services started, secrets copied, dependencies installed or model calls made.'
