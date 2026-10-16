# Exercise archive decisions with a local command stub; never calls Docker.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '../../apps/after-sales-agent/scripts/production-local.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $scriptPath), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Cannot parse production script' }
$definition = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Save-RuntimeLogs'}, $true)
Invoke-Expression $definition.Extent.Text
$applicationRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('archive-check-' + [guid]::NewGuid())
$upstreamRoot = Join-Path $applicationRoot 'upstream'
$script:mode = 'fresh'
$script:logCalls = 0
function docker {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
    $global:LASTEXITCODE = 0
    switch ($CommandArgs[0]) {
        'info' { if ($script:mode -eq 'daemon-failed') { $global:LASTEXITCODE = 1 } else { 'local-stub' } }
        'container' { if ($script:mode -eq 'fresh') { $global:LASTEXITCODE = 1 } else { 'local-container' } }
        'logs' { $script:logCalls++; if ($script:mode -eq 'logs-failed') { $global:LASTEXITCODE = 1 } else { 'local log fixture' } }
        default { throw 'Unexpected Docker command in archive helper' }
    }
}
Save-RuntimeLogs
if ($script:logCalls -ne 0) { throw 'Fresh installation attempted missing container logs' }
$script:mode = 'existing'
Save-RuntimeLogs
if ($script:logCalls -ne 3) { throw 'Existing logs not all archived' }
foreach ($mode in @('daemon-failed','logs-failed')) {
    $script:mode = $mode
    $failed = $false
    try { Save-RuntimeLogs } catch { $failed = $true }
    if (-not $failed) { throw 'Failure must prevent runtime recreation' }
}
$global:LASTEXITCODE = 0
Write-Output 'Archive helper: 4 scenarios passed (local stub only).'
# Temporary test archives are retained; there is no recursive delete.
