# 2026-10-14 生产构建、服务共存与真实账号权限

本阶段业务源码仍为v0.3.7/schema v2，固定DeerFlow v2.1.0/345f08be00c8a9495079b732a39b46aa9af1584e。没有新增模型请求、视觉或付费服务，也没有部署或发布。本文的“生产”指本机生产运行方式；“全负载”限定为四个服务同时运行并叠加下述有界工作量，不代表最大容量、24小时稳定性或生产SLA。

## 已取得的运行结果

| 验证 | 实测结果 |
| --- | --- |
| 生产模式下完整工程回归 | Gateway、生产前端、Nginx、Redis同时运行，68项通过，111.920秒；工程测试远程socket阻断 |
| 真正登录会话到MCP | 现有管理员诊断页面，3个新线程经Gateway注入签名后启动stdio MCP读取偏好，均200；没有模型或伪造owner |
| 生产前端 | pnpm start，实际旧Agent会话与工具记录可加载；没有发送新消息，不算新推理 |
| 连续只读HTTP | 600.015秒，4并发，480次路由请求和3个实际生产JS资源，共483次预期响应全部通过；P50 0.046秒/P95 0.297秒/最大0.500秒 |
| 真实账号隔离 | 两个通过正常注册、密码登录的普通账号，既有管理员会话保留；修正夹具后的71次HTTP与补充18次HTTP全部符合预期 |
| Docker外部关闭后恢复 | 四服务恢复，Gateway200、管理员原会话和已存偏好仍可读；构建退出255/OOMKilled=false，作为外部中断保存，不计成功构建 |
| 历史数据 | 所有基线业务行逐行相同；新增两个账号各自的演示实例/工单/附件/方案；执行操作增量0；原订单申报仍0 |

HTTP的预期为/login=200、/api/v1/auth/setup-status=200、未登录/api/after-sales/status=401以及实际静态资源=200。该采样包含有意验证的401，不应描述为483次业务成功；不包含真实模型并发。

## 构建与运行方式

首次固定官方prod目标在下载固定pnpm10.26.2时UND_ERR_SOCKET退出，尚未编译。随后复用现有已安装依赖镜像（Node22.23.3/pnpm10.26.2），不修改lock或升级底座。无界Turbopack编译期间Docker引擎失联，主机仅约790MiB可用；缺少OOM证据，不能断言其根因。有界3GiB/2CPU/无网络Webpack编译通过后，重复内置类型检查阶段被OOMKill，保留失败。

成功路径将完整类型检查与Webpack顺序执行：next typegen → tsc --noEmit → Next生产构建。Next配置只跳过第二次重复类型检查，前置完整tsc是强制成功门槛。首次顺序构建退出0，生成141页，BUILD_ID=XmV3QFNhQgX3z8EhjuwxC。其已验证运行镜像为after-sales-agent-frontend:production-check-20261014；保留现有依赖而非精简standalone镜像。

新增公开入口scripts/build-production-frontend.ps1、docker/frontend.production-source.Dockerfile与docker/production-build/：从固定工作区源码和已有依赖镜像开始、比对package/lock、无网络构建、限制3GiB与2CPU；失败保留容器和日志。用户关闭Docker后直接启动原构建暴露原配置重复覆盖的问题，已改为只首次保存原配置，并以新容器重新构建。最终可复现产物及启动结果见文末。

运行入口scripts/production-local.ps1及docker/compose.production-local.yaml使用生产前端、Gateway单worker/无reload；Gateway3GiB/2CPU、前端1GiB/2CPU。记忆socket仍0600，保留所有既有账户、配置、CSRF补丁、业务卷。Nginx仅发布127.0.0.1与::1两个loopback，不公开端口。单worker是当前私有记忆socket实现约束，多worker未验证。

## HTTP失败、定位与复验

首次10分钟采样在338.797秒超时，已记录256次成功响应；Nginx看到499，因此不能把超时唯一归因于IPv6。另行实测localhost解析优先::1，而原先仅绑定IPv4；localhost setup耗时2.141秒，显式IPv4约0.015秒。修复本项目生产overlay为双loopback后，localhost setup约0.11秒，上述相同规模采样完整通过。保留首次失败和外部中断；沙箱禁止套接字的0请求尝试单独保存，未算服务失败。没有降低10秒请求超时或缩短复验时长。

## 真实账号边界与范围

A/B账号使用独立CookieJar、实际注册和密码登录，/auth/me验证不同UUID且角色user；没有直接改认证角色、伪造JWT或用模型传owner。

- 本人订单、工单、方案、附件和事件可读；另一普通账号及已知管理员对象返回404；列表仅含本人对象。
- 越权申报、生成方案和上传返回404；尝试注入owner参数422；缺CSRF写请求403。
- 普通账号对本人及他人工单的审批、执行、证据核验、最终跟进全部403，写偏好403。
- 管理员通过现有工作台保存明确标记的合成补发偏好；两个普通账号同时读到空偏好，尝试遗忘真实管理员fact被403拒绝。管理员随后在同一工作台遗忘，回读暂无偏好。
- 管理员用原浏览器会话访问A的真实工单，返回TICKET_NOT_FOUND；管理员身份也不自动取得其他owner数据。
- 拒绝请求前后本人完整工单相同，无新增operation。所有历史业务行比对保持相同。

首批账号验证在13个已记录HTTP后因夹具误读proposal/proposals字段停止；保留失败，修正后复用已有账号/样本完成71次，另18次补充。三批合计102次已记录HTTP，另有管理员实际UI操作和浏览器GET；不是102个独立测试用例。两个新夹具保留待审核，没有为了完成测试执行审批或手动落库。当前工单11、方案13、操作6、演示实例11、附件3、物流跟进1。历史9张工单不变。

本阶段没有通过真实管理员会话对其他owner对象发送写请求，也没有验证跨管理员、客服团队共享队列、账号封禁/撤权；实际admin正向新操作是合成偏好保存/遗忘，审批正向证据沿用既有真实损坏/物流闭环。不能扩写为全部身份组合均已验收。

## 证据与保留

写前业务备份/app/after-sales-data/backups/20261014T100018447570Z-operator.tar.gz；认证核心库备份位于既有私有运行目录，详情在忽略的auth-backup-before-accounts.json，不公开账户与凭证。

私有证据.local/production-stability-20261014包含完整回归、构建失败、HTTP明细、真实账号请求矩阵、数据前后快照、MCP页面结果、截图与SHA256清单。新可复现构建的完整日志在.local/production-build-*。真实账号测试凭证仅存忽略的本机私有文件，不进入文档、提交或公开附件。

重启脚本同时归档真实文件日志及docker logs，避免生产Gateway输出到stdout时误读旧gateway.log。初期Docker故障前完整HTTP日志仍有缺口，不能声称覆盖全部阶段；后续切换前归档在.local/runtime-log-archive/。Docker Desktop故障曾需将仅含已核对零字节通信文件的run/secrets目录改名保留后恢复，没有factory reset、prune或删除卷。最新用户正常重启后直接恢复，无需再清理。

后续仍应按明确目标开展长时间浸泡、最大容量与真实模型负载评估；本轮有界通过不能代替这些结论。长会话token开销、配置恢复和最终系统评测继续列为后续工程工作，不以当前版本号宣称全部生产化。


## 最终可复现构建与新产物回读

修正后的新容器after-sales-production-build-20261014t194621042从固定源开始：完整typegen/tsc通过，Webpack6.8分钟编译成功，141页，退出0、OOMKilled=false。总容器运行约646.755秒（2026-10-14 19:46:31至19:57:18，+08:00）。BUILD_ID=wcDm3IHgE5rxdmMdJuQSC，image sha256:9a2873cdc436c98a6e078c89fb66eda3c244a7cb867a1269308c01b9d9f19dcb。完整源构建日志/容器状态/镜像ID位于.local/production-build-20261014T194621042。

已将旧已浸泡产物保留为production-soaked-20261014回退标签，新产物标记production-check-20261014并实际启动。BUILD_ID与容器回读一致，Gateway健康200、登录200，业务库integrity=ok、11工单/6操作，验证false、socket0600，四服务均运行/OOM=false。Start完成瞬间曾健康连接拒绝，随后日志显示仍在正常初始化；没有重复重建，等待后就绪。已增加并实测Start的50秒有界/health与/login检查；超时保留现场并提示先读日志。

10分钟完整采样属于前一成功产物；新构建产物另外进行60秒/4并发/51次实际资源和路由检查，结果见最终记录。新产物可加载原管理员工作台及已有真实Agent会话，后者显示的9,971 tokens属于先前运行，本阶段没有新增模型请求。切换前实际文件/容器日志已归档。

最终新产物采样：60秒，51次预期响应全部通过，P95 0.281秒/最大0.375秒。收尾资源采样：Gateway275.8MiB/3GiB，前端106MiB/1GiB；四服务RestartCount=0、OOMKilled=false。单次资源采样不等于峰值。
