# 2026-10-13 接续：首次完整损坏 Agent 尝试与非模型修复

本记录接续 2026-10-12 的三层授权与前两层结果。用户同意 1 个新的 DeepSeek 正常损坏对话、最多 2 条用户消息，约定错误、usage 缺失、累计阈值或循环时停止。实际运行发生于 **2026-10-12 19:58 +08:00**，当时源码 v0.3.1；2026-10-13 继续采集与修复，源码为 v0.3.2、schema v2。固定 DeerFlow commit 和依赖锁未升级。

## 实际结果：未完成闭环

发送了 **1 条用户消息**，DeepSeek Flash、闪速模式（实际运行日志 thinking_enabled=false / reasoning_effort=minimal），未发送第二条。新合成订单 `DEMO-A16F8CB66A4E43EC`、实例 `RUN-03A6168A99F4`；线程 `32810068-8e8d-481e-9a2a-1d09661ae358`，run `5cd77ec8-fc75-45f5-9759-a9389acc4c3a`。

真实工具轨迹：

1. read_file 成功读取 damage-intake Skill，同时 MCP get_demo_order 成功。
2. save_damage_report 传中文“补发”，返回 INVALID_RESOLUTION；并行 search_after_sales_knowledge 没有 ticket_id，按当前日期检索，未绑定首次业务申报日期。
3. 模型自行将参数改为 reship 再保存，创建 `TKT-B8ABBC5E2030`，revision=1、investigating、资料齐全。
4. 第四次模型响应准备调用 propose_after_sales_resolution；累计 token 超限，调用被剥离，**未实际生成方案**。日志先记录 token budget hard stop，随后 run 以 GraphRecursionError（50步）结束，stop_reason=null。

仅4次模型调用，不能将此称为模型循环。底座多项 graph hooks 与预算结束路由的交互需要验证；本轮采用自有配置式适配器明确结束，未修改底座或提高 recursion/token 配置。界面保留中间“准备生成方案”文字与工具意图，不能作为工具执行成功证据。工作台和SQLite确认新工单仍investigating，没有新方案、审批或操作。原两张resolved工单与原订单历史保留。

## 用量核对

| API响应 | input | output | total | cache_read | middleware elapsed_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 3,110 | 114 | 3,224 | 0 | 1,460 |
| 2 | 4,425 | 249 | 4,674 | 2,816 | 1,839 |
| 3 | 7,527 | 159 | 7,686 | 4,608 | 1,407 |
| 4 | 8,310 | 71 | 8,381 | 7,680 | 1,030 |
| 合计 | **23,372** | **593** | **23,965** | **15,104** | **5,736** |

Gateway HTTP日志有4条DeepSeek POST 200；自有usage日志、checkpoint AI usage与runs累计一致，llm_call_count=4。没有观察到额外provider重试；第三次请求属于模型在工具错误后自行纠正。UI耗时21秒；run created→updated约21.697秒；middleware耗时总和不是整条流程耗时。缓存字段不等于免费token；货币账单未核对。P1的22,696是不同查询任务，不能用本样本推断优化收益或总体成功率。

20,000阈值是调用完成后累计检查，本次越过3,965；仍不是金额硬上限。超过阈值后停止后续消息，未继续审批或执行，未新增另一对话。

## 非模型修复与验证

- MCP requested_resolution改为Literal[reship, refund, 空字符串]或null；保留省略/清空语义，不放宽业务规则。真实固定加载器检查JSON schema，并验证中文值在MCP参数验证阶段拒绝、没有工单写入。
- Skill与system prompt明确中文偏好映射；先成功保存，再携带ticket_id检索，禁止首报与政策检索并行。是否改善模型选择仍需另获授权的真实对话验证。
- 配置式AfterSalesMiddleware复用固定TokenBudgetMiddleware的累计、历史排除及tool-call stripping，在同一配置阈值触发时通过公开hook_config跳转end；保留usage和token_capped上下文。宿主预算仍启用，未改锁、底座源码、阈值或密钥。该回归验证本地固定响应的LangChain graph，尚未证明修复后真实Gateway/DeepSeek run的停止呈现。
- 工具批次出现status=error或结构化ok=false错误时，自有model wrapper返回本地解释，绕过provider handler；不扫描之前用户回合、不把检索散文识别为错误指令。记录after_sales_tool_error_stop provider_called=false。本地响应无provider usage，不能计作收费模型请求。
- 运行固定Gateway依赖的隔离测试，remote socket guard保持启用；假模型只是固定AIMessage列表，无provider客户端、模型裁判、embedding或记忆提取。审批仍由业务后端约束，测试模拟审批不能代替交互式会话证据。

最终回归结果及重启状态在下方追加，原始日志保留。真实完整损坏流程、模型成功生成方案/等待审批/执行回写仍缺证据。下一次真实模型重放必须明确重新授权场景、消息数与停止方式；本轮“继续工作”不作为额外付费重放授权。

## 数据与证据保留

写新实例前保存业务备份 `backups/20261012T115159299744Z-operator.tar.gz`。只读采集后表计数：tickets=3、proposals=3、movements=2、demo_runs=3、evidence=0、shipping_followups=0。新工单不修改、删除或假装完成。

私有证据：`.local/agent-normal-20261012/` 内 baseline.json、run-evidence.json、gateway-run.log、chat-stopped.png、chat-visible.txt、chat-export.json、regression-first.txt和regression-final.txt。checkpoint包含真实工具参数/返回和usage；网页JSON导出只有可见消息，不包含完整工具轨迹，不能单独替代checkpoint证据。凭据不导出，公开前需脱敏。

证据采集曾因Codex自动审批审核用量限制未执行，2026-10-13重试恢复；属于工具审批系统不可用，不是业务安全拒绝或DeepSeek错误。

## 收尾核对（2026-10-13）

最终 **35项通过，76.602秒**。没有新增真实模型请求。重启前新增业务备份 `20261013T021224256966Z-operator.tar.gz`。RestartGateway的50秒health等待超时，启动期间页面短暂502；没有盲目重复重启，读取日志确认之后Application startup complete，再直接核对health=200、version=0.3.2、verification_enabled=false，工作台正常打开。启动有tiktoken预热超时提示，不能将字符fallback当作provider真实计费token；本次23,965依据provider usage而非fallback估算。

repair-startup.json确认原两工单resolved，新工单investigating，计数不变；workbench-final.png确认暂无可审核方案。固定底座tracked修改仍只有原CSRF的5文件，锁文件无差异，CSRF patch SHA256保持 `D28B2B791012259C14A88D9210D3907D28E48422BEFBC3B906C7DDABF7BEEDF4`。本轮修复已通过隔离回归和启动核对，真实模型闭环仍未通过。
