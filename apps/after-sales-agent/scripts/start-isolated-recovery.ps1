param([string]$Name='after-sales-recovery-eval-20261015-runtime')
$ErrorActionPreference='Stop'
$appPath=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workspacePath=(Resolve-Path (Join-Path $appPath '../..')).Path
$mounts=@(
  "type=bind,source=$appPath/.local/recovery-evaluation-20261015/snapshot,target=/recovery-snapshot,readonly",
  'type=volume,source=after-sales-agent_gateway-venv,target=/app/backend/.venv,readonly',
  "type=bind,source=$appPath/business/after_sales,target=/app/backend/after_sales,readonly",
  "type=bind,source=$appPath/mcp_server,target=/app/business-mcp,readonly",
  "type=bind,source=$appPath/scripts,target=/recovery-scripts,readonly",
  "type=bind,source=$appPath/skills,target=/app/after-sales-skills,readonly",
  "type=bind,source=$workspacePath/vendor/deer-flow/backend/app/gateway/csrf_middleware.py,target=/app/backend/app/gateway/csrf_middleware.py,readonly",
  "type=bind,source=$appPath/.local/production-stability-20261014/account-credentials.private.json,target=/recovery-credentials.json,readonly",
  "type=bind,source=$appPath/.local/production-stability-20261014/account-fixtures.json,target=/recovery-fixtures.json,readonly"
)
$argsList=@('run','-d','--name',$Name,'--network','none','--memory','2g','--cpus','2','--pids-limit','256')
foreach($item in @('DEER_FLOW_HOME=/app/backend/.deer-flow','DEER_FLOW_CONFIG_PATH=/app/project/config.yaml','DEER_FLOW_EXTENSIONS_CONFIG_PATH=/app/project/extensions_config.json','AFTER_SALES_DATA_DIR=/app/after-sales-data','AFTER_SALES_ENABLE_VERIFICATION=false','DEER_FLOW_DATE_TIMEZONE=Asia/Shanghai','DEEPSEEK_API_KEY=disabled-isolated-recovery')) { $argsList+=@('--env',$item) }
foreach($mount in $mounts) { $argsList+=@('--mount',$mount) }
$argsList+=@('--entrypoint','/app/backend/.venv/bin/python','after-sales-agent-gateway','/recovery-scripts/recovery-bootstrap.py')
& docker @argsList
if($LASTEXITCODE -ne 0){throw 'Isolated container creation failed; production untouched.'}
