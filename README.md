# 智能售后与工单协同 Agent

基于 **DeerFlow v2.1.0** 的可运行售后 Agent 工程项目。重点是模型与确定性业务规则的协同：可信身份、工单状态、人工审批、幂等执行，以及失败后的停止与恢复。

**所有订单、政策、退款、补发和物流调查均为合成演示业务，没有真实付款、发货或承运方联络。** 图片只做格式/解码/哈希与人工核验，不做视觉语义分析。

自有业务源码 v0.3.7（含后续上下文与工具目录修复），SQLite schema v2。DeerFlow 固定 commit：`345f08be00c8a9495079b732a39b46aa9af1584e`。仓库不包含 DeerFlow 本体、运行数据、账号、密钥或原始私有证据。

## 我的工作与开源复用

| 范围 | 实现与归属 |
| --- | --- |
| DeerFlow 提供 | Agent harness、网页/登录/会话、流式响应、Skills 投影、MCP 传输、公开扩展接口、DeerMem 本地 CRUD |
| 本项目实现 | 合成订单/场景/政策、工单状态机、方案摘要与版本、可信身份签名、人工审批、事务与执行幂等 |
| 本项目实现 | 图片接入与人工核验、偏好确认策略、按业务日期检索、损坏/物流 Skills、售后工作台 |
| 本项目工程工作 | 只读记忆 IPC、历史工具结果请求投影、预算/错误停止、精确工具目录、隔离恢复与分层验证 |
| 上游适配补丁 | 登录会话缺失 CSRF Cookie 的恢复；本地维护，未提交或合并至上游 |

没有将底座网页、模型、通用运行循环或 DeerMem 存储声称为自研。详见[架构与贡献边界](docs/architecture.md)及[第三方声明](THIRD_PARTY_NOTICES.md)。

## 业务链路

客户陈述 → 读取本人订单/最新工单 → 保存资料 → 代码检查期限、金额与证据 → 生成方案 → **交互式管理员人工审批** → Agent 校验并执行合成操作 → 事务回写与回读。

证据变化会递增 revision，使旧方案/审批失效。物流调查执行后为 awaiting_followup，需人工记录最终结果。签收冲突进入 manual_review。模型没有审批、图片核验或记忆写工具。

## 已验证什么

| 证据层 | 实际结果与边界 |
| --- | --- |
| 非模型工程回归 | 本机四服务共存时，历史完整回归 68 项通过，111.920 秒；远程 socket 阻断。后续增量另有 17 项针对性回归通过，并非当前套件仅 68 项 |
| 真实 Agent 连续闭环 | 同一会话 4 消息/8 API，经历审批失效、重新人工审批和执行 resolved；每 run 为 13,776 / 13,528 / 6,895 / 16,492 tokens，合计 50,691 |
| 身份与权限 | 两个正常密码登录的普通账号和原管理员的有界隔离验证；本人可读、跨 owner 404、普通账号敏感写 403。未覆盖跨管理员写/撤权 |
| 恢复 | 无网络、无发布端口的独立 Gateway 恢复业务/认证/checkpoint/配置/记忆材料；业务逐行一致，两个原账号正常登录。当前快照偏好为空，非空恢复另有历史证据 |
| 小规模评测 | 隔离 HTTP 工程样本 8/8；真实 Agent 初批核心判定 1/2，工具名错误失败保留；最终定向复验正确检索空结果，2 API/7,578 tokens，仅一个修复后样本 |
| 有界稳定性 | 旧成功前端产物 600.015 秒/4 并发/483 次预期响应；最终新产物另测 60 秒/51 次响应，不能称最终镜像跑了 10 分钟 |

这些是开发阶段的有界证据，**不代表总体准确率、任意长会话成本稳定、最大容量或 24 小时 SLA**。20,000 tokens 是每 run 响应完成后的累计检查阈值，可能越过后才停止，不是整会话/金额硬上限；未核对货币账单。详见[验证索引与失败记录](docs/validation.md)。

## 快速开始

主要维护环境为 Windows PowerShell + Docker Desktop Linux containers。需要 Git、Docker Compose >= 2.24.4；首次构建需要网络和较充足的 Docker 内存/磁盘。完整步骤见[安装与复现](docs/setup.md)。

```powershell
# 在独立仓库根目录执行，只获取固定底座，不启动服务或调用模型。
& .\scripts\bootstrap-deerflow.ps1
& .\apps\after-sales-agent\scripts\local.ps1 -Action Setup
# 在忽略的 vendor/deer-flow/.env 填自己的 DEEPSEEK_API_KEY。
```

首次构建、业务激活和生产模式的顺序必须按 setup 文档执行。仓库没有预制镜像；不能在新机器上直接运行 production-local Start。当前已有运行环境不需要重复初始化。

非模型工作台：`http://localhost:2026/api/after-sales/workbench`；对话：`http://localhost:2026/workspace/chats/new`。新安装通过 `/setup` 创建自己的管理员，没有默认账号或演示密码。模型对话需要自己的付费 API 配置；基础工作台和工程测试无需模型推理。

## 阅读与演示

- [5 分钟演示](docs/demo.md)：独立合成场景、审批失效、安全边界。
- [架构与代码导航](docs/architecture.md)：核心文件、数据流与设计取舍。
- [验证材料](docs/validation.md)：区分工程测试、HTTP、真实 Agent、失败和限制。
- [面试讲解提纲](docs/interview.md)：问题、贡献、取舍与真实失败。
- [发布边界](docs/release.md)：脱敏、源码范围与发布检查。

```text
apps/after-sales-agent/
  business/after_sales/  状态、规则、身份、审批、记忆、检索、工作台
  mcp_server/           stdio MCP 服务与维护入口
  skills/public/       损坏受理与物流调查 Skills
  config/              无密钥示例配置
  docker/              业务和本机生产 overlay、有界前端构建
  scripts/             启动、备份、恢复、诊断脚本
  tests/               无模型工程测试
  docs/                分阶段文字验证报告（历史按日期阅读）
scripts/               固定底座获取与发布检查
third_party/           DeerFlow MIT 许可证原文
```

自有代码采用 [MIT](LICENSE)。DeerFlow 及补丁中的上游内容保留原版权与 MIT 声明，其他依赖遵循各自许可证。
