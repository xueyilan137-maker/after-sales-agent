# 安装与复现

## 环境与范围

主要维护环境：Windows PowerShell、Docker Desktop（Linux containers）、Git、Compose >= 2.24.4（overlay 使用 `!override`）。建议 Docker 可用内存至少 8 GiB，并为依赖镜像留足磁盘；这是一项环境建议，不是已测最低配置。首次依赖构建要联网，随后前端生产编译使用已有依赖镜像、无网络、3 GiB/2 CPU。

下面是**新机器、独立目录的准备流程**。本仓库发布整理阶段只做了离线固定源码/补丁/示例配置/脚本和文件检查，没有重新下载依赖并完成一次空机器安装；既有机器的生产构建与运行证据见验证索引。请区分这两个范围。

Compose 沿用固定容器名 `deer-flow-*`、项目名 `after-sales-agent` 和端口 2026。不要与已有同名环境同时启动；更换目录并不会自动隔离同名容器/卷。已有工作环境不要重复执行首次初始化，不要清理原卷。

## 1. 获取固定底座与示例配置

先获取独立项目，再从仓库根目录执行：

```powershell
git clone https://github.com/xueyilan137-maker/after-sales-agent.git
Set-Location after-sales-agent
```

```powershell
docker info --format '{{.ServerVersion}}'
docker compose version
& .\scripts\bootstrap-deerflow.ps1
& .\apps\after-sales-agent\scripts\local.ps1 -Action Setup
```

获取脚本只在不存在目标目录时 clone 并检出固定 commit；已有目录必须匹配 commit，冲突时停止，不 reset/覆盖。然后检查并应用维护的 CSRF patch。Setup 生成忽略的配置、空密钥 `.env` 与派生 Dockerfile，重复运行保留已有文件。

在 `vendor/deer-flow/.env` 本机填写 `DEEPSEEK_API_KEY`，不要提交或粘贴到日志。空密钥可准备基础设施，不能进行模型推理。模型名/端点以当前供应商账户实际支持为准；仓库示例记录的是已测配置，不保证供应商永久提供该名称。不要为复现而静默改用其他付费模型。

示例配置已经包含业务插件、MCP、身份 interceptor、工具约束与辅助模型功能关闭。依赖使用固定上游 lock，不运行依赖升级命令。

## 2. 首次构建依赖与生产前端

```powershell
# 仅构建依赖镜像，不启动开发前端或无界 Turbopack 编译。
& .\apps\after-sales-agent\scripts\local.ps1 -Action Build
& .\apps\after-sales-agent\scripts\build-production-frontend.ps1
```

第二步复用第一步构建的 `after-sales-agent-frontend`。顺序执行 next typegen → 完整 tsc --noEmit → Webpack 生产构建；仅省略第二次重复类型检查。构建失败时保留容器/日志供检查，不直接启动失败构建容器，不自动重试或替换上游版本。

前端运行标签仍为 `after-sales-agent-frontend:production-check-20261014`，这是脚本兼容标签，不表示新机器产物具有历史 BUILD_ID 或历史稳定性证据。新构建会记录自己的 BUILD_ID。

## 3. 拉取基础服务并启动

首次生产启动使用 `--pull never`，因此先显式准备 redis/nginx 镜像并启动 Redis：

```powershell
$env:DEER_FLOW_ROOT = (Resolve-Path .\vendor\deer-flow).Path.Replace('\','/')
$env:AFTER_SALES_APP_ROOT = (Resolve-Path .\apps\after-sales-agent).Path.Replace('\','/')
$composeFiles = @(
  '--project-name','after-sales-agent',
  '--env-file', '.\vendor\deer-flow\.env',
  '-f', '.\vendor\deer-flow\docker\docker-compose-dev.yaml',
  '-f', '.\apps\after-sales-agent\docker\compose.business.yaml',
  '-f', '.\apps\after-sales-agent\docker\compose.production-local.yaml'
)
docker compose @composeFiles pull redis nginx
docker compose @composeFiles up -d --no-deps redis
& .\apps\after-sales-agent\scripts\production-local.ps1 -Action Start
& .\apps\after-sales-agent\scripts\production-local.ps1 -Action Status
```

Start 不构建、不拉取、不初始化账户，先归档实际文件与 stdout 日志，再创建/重建 Gateway、前端、Nginx；Gateway 单 worker、无 reload，前端 pnpm start，Nginx 双 loopback 绑定。就绪等待约 50 秒，首次预热可能未在期限内完成；失败后先看日志和 health，不立即重建。

```powershell
docker logs --timestamps deer-flow-gateway --tail 100
docker logs --timestamps deer-flow-nginx --tail 100
Invoke-WebRequest -UseBasicParsing http://localhost:2026/health
Invoke-WebRequest -UseBasicParsing http://localhost:2026/login
```

首次打开 `http://localhost:2026/setup`，创建自己的管理员。没有内置管理员密码。工作台为 `/api/after-sales/workbench`，对话为 `/workspace/chats/new`。选择独立合成场景，不依赖旧订单日期。

## 非模型工程测试

在已准备的本机环境运行：

```powershell
& .\apps\after-sales-agent\scripts\local.ps1 -Action TestEngineering
```

该 Action 不切换运行方式。测试用临时业务/记忆根，阻断远程 socket；可能占用较多资源。历史完整 68 项与后续增量测试是不同批次，不能把新套件数量直接写成历史结果。工程测试不发模型请求，不证明真实模型质量。

`diagnose-tool-schema.py` 使用真实目录和本地固定响应，需将 tests（含 sitecustomize.py）放入 PYTHONPATH 才能运行。真实模型 eval 和审批不要由 CI 自动触发。

## 现有环境维护与恢复材料

日常使用 production-local Status/Start；原 local Start/RestartGateway/RestartFrontend 会切回开发方式。源码插件修改后重载前必须保存文件日志和 docker stdout。写现有业务数据前使用 local BackupBusiness；不会备份认证/checkpoint。

`recovery-snapshot.py`、`recovery-bootstrap.py`、`start-isolated-recovery.ps1`、`evaluate-restored-system.py`保留原工程演练实现，其中演练日期目录与账号夹具路径属于操作者输入，**不是随仓库提供的恢复包，也不是新安装的一键入口**。使用自己本机的隔离快照/账号夹具前应审阅脚本；不向公开仓库补入凭证或备份。历史恢复范围与失败见验证索引。
