# 2026-10-12 前两层非模型验证结果

时间以 Asia/Shanghai 记录。固定 DeerFlow v2.1.0 / `345f08be00c8a9495079b732a39b46aa9af1584e`，Python 3.12.15、MCP 1.28.1。业务源码接续 v0.3.0，本轮收尾为 v0.3.1；schema 保持 v2，底座、锁文件、账户、密钥、CSRF patch 和数据卷保留。未发起模型推理、自动记忆提取、视觉、embedding、模型裁判或付费回退。

## 第一层：隔离工程测试

固定 Gateway interpreter 运行 stdlib unittest、真实 SQLite/Pillow 与固定依赖。每项测试创建临时业务数据库、身份密钥及记忆根；路由测试使用模拟身份。`tests/sitecustomize.py` 拒绝非本地 socket 连接，并包含实际阻断断言。没有创建 Agent 或模型对象。

最终 **28 项通过，32.058 秒**：19 项损坏/网络约束、6 项接口权限、3 项 MCP 传输测试。覆盖正常补发/退款、缺资料、部分字段保留/明确清空、revision 冲突、未审批执行、证据确认、审批后文字/图片变化、重新审批、重复及四线程并发执行、实体归属隔离、7天精确边界、金额超限、真实审批期限、拒绝后补充、摘要损坏、独立重放和审计分页。模拟审批只证明业务与权限代码的覆盖范围。

复现：

```powershell
& .\apps\after-sales-agent\scripts\local.ps1 -Action TestEngineering
```

原始最终日志 `regression-final.txt` 仅保存在私有证据目录，不随公开仓库发布。首轮结果和修正保留：退款预期误写成9900分，按合成订单4900分纠正；MCP SDK实际返回JSON文本块，测试原先假定必有structuredContent，改为支持两种标准返回。业务规则未因这些测试问题而放宽。

## 第二层：固定 MCP 与交互式管理员会话

默认关闭的 `/api/after-sales/verification` 仅供交互式管理员操作。临时启用后，浏览器调用固定 `get_mcp_tools()`；真实 Gateway `inject_authenticated_user_context()` 将登录用户写入 ToolRuntime，自有 interceptor 签入 metadata，固定持久 stdio session 调用真实业务 MCP。请求没有 owner/runtime/header/signature 输入。每次探针调用结束关闭其 MCP session。

工具目录实际发现12个定义，10个当前白名单，2个旧名称别名；审批工具缺席。两条 Skill 文件存在，限定读取与其他路径拒绝经过非模型回归。此轮没有证明模型主动选择/读取 Skill。独立临时库的原始 MCP SDK 调用验证缺失、错误、过期、篡改用户签名拒绝；固定加载器验证模拟 owner A/B 隔离。真实管理员身份经现有会话验证，未创建第二个真实账号。

工作台审批由用户授权的浏览器自动化操作现有交互式管理员会话，保留 Gateway CSRF 校验；不是直接写数据库，也不代表用户本人逐条点击审核。所有内容和执行均为合成业务。

| 场景 | 预期 | 实际结果 |
| --- | --- | --- |
| A 正常损坏 | 申报→规则方案→交互式管理员审批→MCP执行→回写 | resolved；演示补发；1个操作；重复请求idempotent_reuse=true且operation_id相同 |
| A 未审批执行 | 拒绝且无操作 | HUMAN_APPROVAL_REQUIRED；拒绝后才在工作台审批 |
| B 审批后补充文字证据 | 旧方案拒绝→生成并审批新方案→完成 | revision 1→2；旧方案superseded且原审批时间/备注保留；旧MCP执行STALE_PROPOSAL；新方案演示退款4900分；resolved且1个操作 |

现场正常闭环使用v0.3.0业务规则和本轮探针，随后更新版本标记并完成v0.3.1回归与异常闭环；本轮没有修改store.py的损坏规则/状态实现。现场A的问题陈述把商品写成“保温杯”，订单实际为陶瓷马克杯；人工会话流程未识别这一语义差异。本轮证明规则与接入链路，不能宣称已具备证据语义核验。后续真实Agent样本使用准确商品描述，历史不修改。

私有原始响应、截图与业务快照位于操作者本机的 `verification-20261012` 证据目录，未公开：`directory.json`、`normal-*.json`、`anomaly-*.json`、`business-final.json` 和两条 `*-resolved.png`。MCP返回标准JSON文本块；Gateway日志记录真实ListToolsRequest/CallToolRequest。这里只是人工选择工具的MCP集成证据，没有模型自主调用证据。

最终只读业务快照：tickets=2、proposals=3、movements=2、demo_runs=2、evidence=0、shipping_followups=0。两张工单resolved，各1个操作；原订单签收仍为2026-10-08 14:30 +08:00，原订单没有创建申报，未改首次时间。现场没有上传图片；Pillow接入/核验/失效链路仅有隔离测试证据。

## 修复、备份与保留

`BackupBusiness`首跑失败：maintenance.py无法导入after_sales。已为docker exec补上`PYTHONPATH=/app/backend`，重试成功。写现场验证实例之前，在业务卷保存 `backups/20261012T111620830300Z-operator.tar.gz`。隔离目录解包后SQLite integrity_check=ok、schema=2、六表均为写入前0，现有库没有被覆盖。此备份只有business.sqlite3，未包含记忆文件，不能据此认定客户记忆恢复通过。

验证入口用 `RestartGateway -EnableVerification` 临时开启，收尾以不带此开关的RestartGateway关闭；生产默认false。该入口没有增加Agent工具。启动health等待分支实际运行成功。测试客户端的上游弃用提示保留，未因此升级依赖。

## 第三层待授权的首批计划

先只运行 **1个新DeepSeek对话、最多2条用户消息**，创建新的damage-in-window实例：第一条给完整损坏资料，观察Skill、订单/政策/申报/方案工具和等待审批；通过工作台真实会话审批后，第二条要求执行并读取结果。正常样本完成后检查结果，再决定下一次异常样本；本次授权请求不包含第二个对话或全面模型评测。

停止条件：出现越权/审批绕过、业务写入不一致、模型循环或重复相同无进展调用时停止；累计10次可观测模型API尝试时中止运行；现有每轮20,000 token完成后累计检查保持不变，遇到阈值/usage缺失/异常立即停止后续消息并检查。调用可能先完成再超阈值，取消也可能来不及阻止已在途请求；这不是金额硬上限或不会超额的保证。不自动重试付费场景、不增加对话、不启用新模型/服务。

用量记录：线程/run、每次usage及累计input/output/total tokens、可获得的缓存字段、API尝试/重试、耗时、工具序列、工单/方案/操作ID、最终状态与失败；对账底座usage和after_sales_model_usage，缺失或不一致明确标记。金额账单未确定，不给未经核对的费用数字。用户消息数不等于API次数。真实对话必须等用户明确同意。

客户偏好写入/纠正/遗忘及跨会话、现场图片核验、政策检索质量、物流/人工跟进、配置成对恢复、生产构建和持续稳定性仍待逐项验证。28项开发回归与两条集成流程不构成总体成功率或完整系统评测。

## 2026-10-13 最新进展与重放边界

已获准的一次真实损坏尝试只发送1条消息，4次API累计23,965 tokens后停止；Skill与MCP申报有证据，工单investigating，无方案或执行，完整Agent闭环未通过。v0.3.2枚举、检索顺序与停止适配已有35项非模型回归，未付费重放。详情见agent-validation-20261013.md。先读该记录再演示；不要把保留的失败工单手动完成后称为Agent成功。

下一次真实重放必须先明确新的单次场景、对话/消息数量、错误/循环/usage/阈值停止条件及记录方式，并获明确同意。日常非模型修复与回归继续沿用已授权的前两层；本地固定假模型不访问provider，记录为工程验证。20,000仍为完成后累计检查，不能保证不会超出。
