# 2026-10-13 完整链诊断、第二次真实尝试与 v0.3.4 修复

用户同意先完成开销/停止诊断，再按“正常真实闭环→审批后证据变化→图片、记忆、检索、物流”推进。按此前明确的单次范围，本轮真实运行限1个新正常损坏对话、最多2条用户消息，错误/usage缺失/循环/累计阈值或10次可观测API尝试时停止。本轮实际只发送1条，超阈值后未审批、执行或新增对话。后续阶段以正常闭环通过为前提；不将同意扩为无限调用。

固定 DeerFlow v2.1.0 commit不变，schema v2不变；真实尝试使用v0.3.3，之后非模型修复为v0.3.4。43项最终回归通过（66.875秒），见私有regression-warning-fix.txt；真实模型没有验证v0.3.4修复效果。

## 完整运行时发现与修复

v0.3.2的35项回归仅验证简化graph。新增使用固定公开build_middlewares与ThreadState构建真实26项middleware链；provider工厂禁止构造，辅助模型断言关闭，临时路径隔离，remote socket guard开启。50步配置在第四个模型节点之后、结束hook之前耗尽，即使已在wrapper中计算到预算上限，仍无法完成终止路径。保留runtime-chain-first/second/trace失败日志；不能依据之前35项通过宣称完整链问题已修复。

预算初始化和累计改在自有model wrapper完成，不增加before_agent/after_agent节点；预算结束通过公开after_model jump_to=end。**graph节点限制从25/最大50改为100/最大100**，仅修改自有配置示例和现有成对备份的operator配置，不修改底座/锁。20,000 token、80%警告、完成后累计检查和模型端点/密钥不提高或替换。节点数包括middleware，不等于API次数。100步下完整链预算停止、错误后无provider重试均通过；后来的真实run也确认token_capped正常结束，没有GraphRecursionError。

模型请求中的JSON返回做无损紧凑序列化，原始checkpoint、MCP响应和审计保留。上次样本工具文本5998→5123个Unicode字符（减少875，约14.6%）；Skill全文、字段、引用、文本和所有消息保留。该度量不是provider token/费用节省证明。

方案MCP投影追加与方案政策ID/版本/哈希一致的policy_basis，供正常流程直接引用，额外知识检索仍可按ticket_id调用；规则与审批digest不改。执行工具调用原execute_resolution，事务提交后以同一可信owner真实get_ticket回读，验证operation_id存在并返回readback。幂等重复保持同一操作。隔离模拟审批仅用于MCP回归，不能称为真实会话审批证据。

新增程序生成的待审批交接与执行回执，取自最新已完成的签名工具结果，不审批、不执行、不改业务状态，也不冒充模型推理输出。readback缺失或不一致不生成成功回执。模型仍负责调查和工具选择，明确的业务状态边界由程序结束以减少额外总结请求。

## 第二次实际 DeepSeek 尝试：生成方案但没有闭环

2026-10-13 11:12:56–11:13:17 +08:00；DeepSeek Flash、闪速、实际执行thinking_enabled=false。订单`DEMO-814668C236074F58`，工单`TKT-82DC2E38BFAB` revision1，方案`PRP-CEF5A4A1D0F5` pending；线程`ce133f7d-5368-44dd-a231-4c218c08ea0a`，run`00a71900-0881-4fce-9b66-5ae62440ec67`。

真实顺序：查询订单→读取damage-intake Skill→保存reship损坏申报→生成政策方案→额外模型总结。没有参数纠正、重复工具错误或provider重试。前四次累计17,225 tokens，方案真实落库。宿主此时追加80%预算提醒，程序交接检测未生效，第五次总结响应后总计26,541，完成后阈值触发；run.status=success但stop_reason=token_capped、error=null。status=success表示graph正常结束，**不是售后流程验收通过**。

| API响应 | input | output | total | cache_read | elapsed_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 3223 | 70 | 3293 | 256 | 1286 |
| 2 | 3728 | 83 | 3811 | 3200 | 1124 |
| 3 | 4550 | 175 | 4725 | 2944 | 1528 |
| 4 | 5312 | 84 | 5396 | 4608 | 1397 |
| 5 | 8887 | 429 | 9316 | 5376 | 2768 |
| 合计 | **25700** | **841** | **26541** | **16384** | **8103** |

5条HTTP POST 200、5组自有usage、checkpoint与runs累计一致。UI20秒，run created→updated约21.183秒；middleware耗时8.103秒不是完整流程耗时。货币账单未核对；缓存读取不等于免费token。任务/步骤不同，不能据26,541与此前23,965推断成本优化成功或失败率。

没有发送第二条消息、点击审批或执行。当前工单awaiting_approval，操作仍只有原先2个。用户停留在审批阶段不算正常完整闭环通过，因此未启动审批后证据变化或图片/记忆/检索/物流真实验证。

## v0.3.4 提醒遮挡边界修复

根因：检测从request.messages尾部反向找最新ToolMessage，而宿主TokenBudgetMiddleware将budget_warning HumanMessage追加在请求尾部，导致提前停止查找。改为使用request.state中的原始已完成工具批次，仍不扫描之前用户回合；模型请求的提醒和消息历史继续保留。自有预算适配仅复用hard limit，80%提醒只由宿主注入，避免重复排队/日志。

完整26项链夹具现在主动使用17,000 tokens触发真实宿主提醒，验证工具错误和待审批边界都绕过下一次provider handler；MCP文本块形态也单独回归。还对本次真实checkpoint的最后方案工具返回加预算提醒进行无模型回放，实际识别awaiting_approval（boundary-replay.json），provider_called=false。回放不是v0.3.4新的真实Agent运行，也不能把实际已支付的第五次调用删除或改记。

## 备份、环境与剩余边界

业务写入前备份`20261013T030709959026Z-operator.tar.gz`，ConfigureBusiness保存成对配置备份。最新原始表：工单4、方案4、操作2、实例4、附件0、跟进0；原两工单resolved、第一次失败工单investigating、新工单awaiting_approval。原订单时间与首次申报历史保留。

本轮Docker服务原先不可用。确认两处旧通信socket导致启动失败后，关闭故障Docker后台并将run和仅含engine.sock的目录改名保留，再启动已有Docker。未删除文件、factory reset、重建或清理镜像/卷，也未改账户/密钥。已有项目容器按自身restart policy恢复，未单独修改Hadoop/Airflow。保留私有docker-recovery*.json；后续仍需排查Windows通信文件残留的长期稳定性。

原始真实证据在`.local/agent-normal-v033-20261013/`，完整链首次失败、上下文诊断与42项回归在`.local/agent-normal-20261012/`。不包含账户凭据或签名密钥，公开前仍需脱敏。新版模型是否合并Skill/订单调用、是否按方案引用、正常审批/执行/回写以及异常恢复尚需真实验证。下一次付费重放须明确新的单次范围和同意，不能自动重试本轮已触发停止条件的对话。

收尾确认：v0.3.4重启前另存业务备份20261013T032643696734Z-operator.tar.gz。脚本50秒health等待再次超时，随后读取Application startup complete并直接确认health=200、version=0.3.4、token_budget=20,000、graph_node_limit=100、verification_enabled=false，四工单状态/4方案/2操作不变。启动等待窗口与Docker通信残留属于后续稳定性事项，未盲目重复重启或重置。MCP文本块+预算提醒单项完整链回归另通过1项（5.411秒）；真实checkpoint无模型回放识别待审批，不能当作额外真实Agent成功。
