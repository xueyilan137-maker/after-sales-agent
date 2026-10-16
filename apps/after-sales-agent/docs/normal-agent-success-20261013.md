# 2026-10-13 v0.3.4 正常损坏真实闭环证据

用户明确同意再次运行1个新正常损坏对话、最多2条用户消息，保持错误/usage缺失/循环/10次可观测API尝试及原有预算停止条件。实际发送2条，5次DeepSeek API响应，没有额外对话、provider重试、视觉、embedding、模型裁判、自动记忆提取或付费回退。本轮不修改业务源码、不重新运行无新变化的43项回归；此前工程证据仍有效，真实运行证据单独记录。

固定DeerFlow v2.1.0 commit `345f08be00c8a9495079b732a39b46aa9af1584e`，自有源码v0.3.4、schema v2；DeepSeek Flash、闪速模式，执行日志thinking_enabled=false。所有订单、资料、政策和操作都是合成演示，没有真实支付、发货或承运方联络。

## 已完成的实际链路

订单`DEMO-8FA8187B5DA34DA9`；工单`TKT-D400DCA0C55D`、revision1；方案`PRP-9AC1028F0356`；操作`OP-1361A7596164`。线程`2c5457d4-bb5e-4ae2-b6ac-6bbfbd8ce8f3`。

1. 第一条完整损坏申报。模型同时读取damage-intake Skill并调用真实MCP查询订单，然后保存reship资料、调用propose_after_sales_resolution生成方案。后端按独立实例首次业务日期2026-10-12选damage-demo-v1 v1.0.0，返回DAMAGE-01至05条款正文/引用，等待人工审批。没有额外知识检索调用，不将本样本当作检索质量验证。
2. 程序从已完成的工具state生成待审批交接，日志after_sales_boundary_stop state=awaiting_approval provider_called=false。审批前工单awaiting_approval，操作为空；没有模型approve工具。
3. 用户授权的浏览器自动化操作**现有交互式管理员会话**：核对陶瓷杯订单、文字陈述、补发方案和政策，勾选核验并填写明确的合成验证备注，经工作台POST review HTTP200于2026-10-13 15:29:31 +08:00审批。数据库proposal/ticket均approved、revision1；不是数据库模拟审批，也不代表用户本人逐条点击。没有图片上传或视觉核验。
4. 第二条请求继续。模型先真实MCP get_after_sales_ticket确认approved，再调用execute_approved_resolution。业务事务写入演示补发、方案executed、工单resolved；该工具提交后以同一可信owner真实读取工单，确认操作号存在，返回readback。
5. 程序从readback输出完成回执，日志after_sales_boundary_stop state=resolved provider_called=false。工作台和SQLite再次只读确认resolved、方案executed、恰好1个操作，审批审计和首次日期保留。

模型负责调查和工具选择；待审批交接与最终回执是自有程序按工具事实生成的非模型响应，不宣称这两段文字是模型推理。运行时、网页、Skills投影和MCP传输复用DeerFlow；规则、身份签名适配、SQLite状态、审批/执行/回读及边界处理是本项目自有贡献。

## 精确用量与范围

| 模型API | input | output | total | cache_read | middleware elapsed_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 申报1 | 3226 | 113 | 3339 | 2944 | 1545 |
| 申报2 | 4511 | 162 | 4673 | 3072 | 1195 |
| 申报3 | 5217 | 67 | 5284 | 4608 | 940 |
| 继续1 | 8896 | 71 | 8967 | 5248 | 1152 |
| 继续2 | 10018 | 73 | 10091 | 8960 | 1243 |
| 整对话合计 | **31868** | **486** | **32354** | **24832** | **6075** |

首轮run `62d4dc2d-0258-4b38-a2db-0b2924b6ddb3`：13,296 tokens、3次调用，15:19:19–15:19:37 +08:00（约17.970秒）；执行轮run `fc709a1a-d7d7-4115-a3d7-eece6b9b63c9`：19,058 tokens、2次调用，15:32:23–15:32:29（约6.190秒）。两run均success、error=null、stop_reason=null；第二轮触发95.3%的软警告，本地完成回执之后没有下一次provider调用。

**20,000是原有底座每个run的完成后累计阈值，未提高；整对话累计32,354，超过20,000。** 不把“每run未超限”写成“整对话低于20,000”，不当作金额硬上限。HTTP日志5条DeepSeek POST200、自有usage、checkpoint与两run计数/累计一致；本地交接/回执无provider usage，不算API。金额账单未核对，缓存不等于免费token，middleware耗时总和不是业务完整耗时。单样本不证明总体成功率、稳定费用或与不同步骤的失败样本可直接比较的优化收益。

## 数据、异常与证据保留

写新实例前备份`backups/20261013T070833954346Z-operator.tar.gz`。收尾业务表tickets=5、proposals=5、movements=3、demo_runs=5、evidence=0、shipping_followups=0。本工单resolved；两个之前未完成样本仍保留investigating/awaiting_approval，没有手动完成或删除。原`ORD-2026-0017`签收仍2026-10-08 14:30+08:00、没有新增原订单申报；窗口截至2026-10-15 14:30+08:00。

首次发送操作的Codex自动审批审核超时。随后页面输入框仍空、Gateway无run/模型请求，确认未提交后只重试一次；实际用户消息计数仍2，没有重复模型请求。审批前截图捕获失败，因它位于动作之前，未执行审批；之后单独完成实际工作台审批，最终截图捕获成功。均属工具操作问题，不隐藏为业务成功或收费模型重试。

私有证据`.local/agent-normal-v034-20261013/`：baseline.json、intake-evidence.json（审批前）、final-evidence.json（完整checkpoint/最终业务）、usage.json、gateway-run.log、workbench-resolved.png、chat-resolved.png、chat-visible.txt及manifest.json。审计包含工作台交互式审批和approved_executor操作；签名由可信Gateway上下文注入，模型参数不含owner。证据保持私有，发布前脱敏。

## 下一阶段

正常真实闭环本样本通过，可按用户要求转入审批后证据变化场景。已有隔离回归和前两层MCP/工作台异常闭环不等于真实Agent异常恢复证据。先准备新独立实例、旧方案失效与重新审批的可核对步骤；新增真实模型场景仍先明确对话/消息数量、费用与停止范围，不自动扩大本次单对话授权。随后依次收尾现场图片、客户记忆、检索质量和物流。跨真实账号隔离、异常恢复、配置/记忆恢复及持续运行稳定性等缺口仍保留。
