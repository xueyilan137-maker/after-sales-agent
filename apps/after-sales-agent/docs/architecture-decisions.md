# 本地实现决策（2026-10-12）

2026-10-15恢复/评测增量：恢复SQLite路径必须匹配固定database.sqlite_dir相对于backend的定位；仅设置DEER_FLOW_HOME不足。工具失败停止改为接受任意尾部status=error（框架可能不提供name），成功的未知文本不作为控制错误；未知工具仍拒绝，不扩大白名单或静默改写。16项相关回归及真实1API错误停止通过；无匹配检索模型样本仍失败。详见[恢复与小评测](recovery-evaluation-20261015.md)。

2026-10-15实测补充：历史投影已通过一个真实四轮同会话样本（4消息/8API/50,691 tokens，每run均低于20,000），含旧审批失效、真实工作台重新审批和同会话MCP执行resolved；原checkpoint保留。不是配对A/B、货币预算或任意轮数稳定性结论。见[详细记录](long-context-validation-20261015.md)。

2026-10-15增量：历史工具快照定位投影与重复引用复用仅作用于模型请求副本；保留当前轮、原checkpoint和审批事务边界，不引入模型总结。22项相关非模型测试与离线回放结论见[长上下文记录](long-context-validation-20261015.md)，尚非真实长会话token验收。

当前状态（2026-10-14）：v0.3.7。图片/记忆/检索/物流阶段已取得分层证据，68项非模型测试在受控资源条件下通过；最新结论见本文末及[物流与工程验收](logistics-validation-20261014.md)。下方早期版本、待办及授权文字按日期作为历史，当前有界请求授权不需重复询问。

## 固定底座与新增边界

DeerFlow v2.1.0 / `345f08be00c8a9495079b732a39b46aa9af1584e` 提供网页对话、运行循环、流式响应、日期上下文、Skills 投影、MCP 传输与 DeerMem 本地记忆 CRUD。CSRF 适配以维护 patch 保存。新增业务版本 0.3.1 在 `business/after_sales`，使用固定 lock 中已有的 Pillow/FastAPI/LangChain/MCP，没有追加依赖或修改上游 lock。

## 扩展接口选择

固定版本 `plugins:` 通过公开 API 0.2.0 注册 Gateway service/router；插件 middleware 是观察式，宿主会忽略其 request 替换并在异常时放行。因此提示词改写和工具拒绝使用底座支持的 `extensions_config.middlewares` 配置类 `after_sales.plugin:AfterSalesMiddleware`。构造失败使 Agent 创建失败，不承担审批授权；真正的审批约束在业务 API 与数据库事务内。

MCP 用户身份通过 `mcpInterceptors` 和底座 stdio call metadata 传递。运行时的 user_id 由 Gateway 覆写为真实登录 owner；本项目添加 60 秒有效的 HMAC 签名，服务不接受模型提供的客户/用户/审批字段。签名密钥只在独立业务卷内，未加入提示词、工具参数或浏览器响应。此方案针对同一私有 Gateway 的本地 stdio 连接；未来跨主机接入应换服务认证。

## 知识检索与业务规则

损坏和物流的政策 Markdown 按条款标题分块，英文词和中文二元词项按交集计分；manifest 保存生效期、版本、机器规则和联合内容哈希。传入 ticket_id 时，从 owner 范围的工单首次业务申报日期选择唯一适用版本，避免检索按今天、执行按申报日期的偏差。引用含政策版本、条款、内容哈希与可打开来源；增加版本应添加新 manifest，不能覆盖历史条款。

四条案例是明确标记为 synthetic_design_example 的设计示例，不是已执行的成功记录，不能用于资格判断。无适用版本或无检索匹配时不补造依据。此实现仍是小语料词法检索，没有向量库、embedding、reranker 或质量测量。资格判断直接读取订单与规则，不依赖模型解释或相似度。

## 持久化与执行

业务 SQLite v2 在独立 business-data volume 内，隔离于 DeerFlow checkpoint。启动以 SQLite backup 保存 v1 快照，BEGIN IMMEDIATE 串行化增量迁移；增加业务类型、业务首次申报时间、实例、证据与跟进表，不删除旧行。真实 reported_at 原样保留。旧方案若不匹配新增摘要结构，会被要求重新生成和人工审批，不继承为有效新审批。

一位 owner 的一张订单仍只有一张售后工单，跨类型请求交人工协调。申报改为部分字段更新：None/省略保留旧值，空字符串明确清空；编辑携带 expected_revision，过期版本拒绝覆盖。工单投影含已知资料与截断标记，模型不能把截断投影覆盖回完整资料。修改前后资料摘要保存在审计中。

方案绑定订单、资料、附件及其核验状态、政策、业务时钟和工单版本；审核与执行重新比较 payload/digest。审批有效期为真实时钟 24 小时，批准还要求明确证据确认和全部附件人工接受。模型没有 approve 工具，API 要求 interactive session + admin。新方案可重新核对过期/变化的旧方案；拒绝后需要补充资料。

操作、执行结果和工单状态在同一 SQLite 事务中提交；操作表唯一约束 proposal_id 和 owner/ticket_id，重复执行读取既有结果。已经执行的工单不能再生成第二个方案动作。损坏处理进入 resolved；物流登记进入 awaiting_followup，由管理员记录一个最终合成跟进后关闭或转人工。跟进不覆盖原轨迹，相同内容重试读取既有记录，不同内容不能覆盖。此阶段仅 demo_recorded，不调用支付/承运方，不实现跨系统副作用恢复。

工作台每次投影最近 30 个事件、10 个方案；事件按不可变 event_id 游标分页，原始方案有独立 owner 校验读取端点。工单列表用固定时间/ID 游标，避免以会变化的当前行更新时间解释旧游标。分页不承诺跨请求一致快照。

## 可复现演示与业务时钟

原 ORD-2026-0017 保持 2026-10-08 14:30 +08:00 签收和真实时钟，新申报截止 2026-10-15 14:30 +08:00。五个场景创建新的 RUN/DEMO 订单，每个实例的 frozen_synthetic 时间进入订单快照并绑定方案；真实首次申报和业务申报分栏保存。冻结时钟只影响合成业务判断，不用于 HMAC、审批过期或日志。重放创建新实例，不改旧时间、不删除旧历史。

## 证据与客户记忆

图片以有界流接入，最多每工单 5 张、每张 4 MiB/一千万像素、单帧 PNG/JPEG/WebP。复用固定依赖 Pillow 解码校验；保存原始 bytes、SHA256、媒体类型和审核记录。读取按 owner 限制并禁用浏览器缓存/内容嗅探。解码不是语义分析，人工接受不是模型核验。

记忆直接构造固定 DeerMem.from_config 无模型后端，使用业务卷独立 customer-memory root、strict_user_scope 与 after-sales bucket，保留底座的事实存储和 CRUD。不经注入宿主默认模型的 factory、不调用 add/add_nowait 或自动提取、不启用通用 memory_add 工具。

自有适配器只允许三个有限偏好字段；交互式管理员记录确认来源、修订号、前一摘要，可纠正或遗忘。模型只读偏好，不读取自由来源备注；业务事实和本次处理决定不写成长期偏好。适配层用业务写锁串行化读改写，DeerMem 负责 canonical 持久化；SQLite 不存另一份偏好。读取/写入失败返回结构化错误，不触发模型或远端降级。偏好不是审批授权。

## 维护与运行观察

BackupBusiness 在业务写锁内生成 SQLite snapshot + DeerMem 私有归档，仅放业务卷 backups，排除账户、身份签名密钥、API key 和 DeerFlow checkpoint。ConfigureBusiness 无论哪份配置变化都保存成对备份；RestoreBusinessConfig 校验完整时间戳后缀及 schema45，先备份当前配置，复制错误时回退该对文件。本轮已修复BackupBusiness导入路径、执行手动备份并验证隔离SQLite解包完整性；备份当时没有记忆文件，记忆恢复与配置恢复仍待演练，也不自动回退数据库 schema。

配置式 middleware 记录响应 usage 与 elapsed_ms，不记录消息正文或凭据、不计算未经确定的币种费用。未获得新模型调用样本。此为代码新增，不能当作成本告警、可靠传输或完成性能测量。

## 上下文开销

P1 用户真实订单查询显示累计 22,696 tokens，超过 20,000 限制。运行时按累计调用 usage 在请求完成后检查，不能保证首次/后续调用不会越过阈值。新本地配置使用独立业务 Skill 根、精简 system prompt、限定工具集和紧凑工单投影；保留消息历史、日期注入及原 token 限制。未发起新模型请求，尚无改造后的 token 或成本测量。通用网页/命令/写文件等工具在这个本地售后配置中不提供，未来按具体业务需要再引入受限适配器。

## 已知限制

v0.3.1有28项非模型回归、真实签名MCP与工作台会话正常/审批失效两条损坏闭环证据，详见verification-results-20261012.md。业务库已有2张resolved工单、3个方案和2个操作。模型Skill使用、真实Agent损坏闭环、现场图片核验、记忆跨会话、物流全流程、记忆/配置恢复、usage实测与检索质量仍待验证。模型白名单 10 个业务工具，源码另留 2 个历史别名；比 v0.2 工具更多，实际 token 仍待测量。

自动视觉/embedding、新政策版本冲突质量验证、多次人工接管、外部执行恢复、货币预算、生产构建与前端长期资源稳定性、在线多用户部署仍待决定或开发。本轮首次重启的 tiktoken 预热超时，最终重载预热成功，实际统计精度未确认；不能提高 token 预算掩盖开销。GitHub 发布范围与费用资源待用户确定。

此前v0.3.0源码重载曾有health读取超时，随后确认启动成功。本轮v0.3.1的RestartGateway实际运行最多50秒等待health分支并确认HTTP 200。管理员当前仅审核本人owner范围工单，跨账号客服授权/分配仍待扩展。


## 非模型集成验证适配器（v0.3.1）

默认关闭的verification入口仅接受交互式管理员会话，沿用Gateway CSRF。浏览器手选工具，经固定Gateway inject_authenticated_user_context写入可信ToolRuntime，再调用固定get_mcp_tools产生的持久stdio coroutine；原identity interceptor及MCP签名校验均运行。限制唯一固定售后本地服务与10个白名单，按真实JSON schema检查业务参数，拒绝额外owner/runtime/header字段，没有审批接口。采用固定lock已有jsonschema，无新增依赖。探针结束关闭scope session，收尾禁用入口。此为工程接入证据，不能代替模型自主工具/Skill选择；工作台自动化使用用户授权的现有会话，不能描述为用户本人手工审核。

## v0.3.2 实际失败驱动的停止适配（2026-10-13）

2026-10-12已获准运行一个真实损坏对话：4次DeepSeek响应累计23,965 tokens，Skill与签名MCP查询/申报成功，阈值触发后未生成方案，GraphRecursionError结束。旧的“未取得新模型样本”内容仅属于此前阶段。详见agent-validation-20261013.md；货币账单未核对，完整Agent闭环未通过。

通过extensions_config中的自有AfterSalesMiddleware复用固定TokenBudgetMiddleware的配置、累计和raw/structured tool-call stripping，并在公开after_model hook上显式jump_to=end。同样排除之前用户run的usage，不提高20,000阈值或递归上限；底座宿主预算仍保留。工具错误在自有model wrapper返回本地AIMessage，识别当前批次的status=error或JSON ok=false，不把检索散文当控制指令，不再调用provider handler。该响应标记after_sales_non_model_stop，不算收费API请求。

MCP偏好使用Literal枚举，空字符串仍用于明确清空，省略/null保持部分更新语义。Skill先成功保存再按ticket_id检索；当前模型是否遵循需真实重验。35项非模型回归包括固定依赖LangChain假模型graph，不代表完整Gateway/DeepSeek修复验收；不修改底座/锁/身份/人工审批规则。

## 2026-10-13 v0.3.4 完整链诊断与第二次真实尝试（最新）

- 用户同意依次推进正常真实闭环、审批后证据变化、图片、记忆、检索、物流。本轮沿用1个新正常对话、最多2条用户消息的明确范围；实际只发送1条，5次API累计26,541 tokens超20,000后停止，没有第二条、审批或执行，不扩为不限调用。
- v0.3.2简化graph回归不足：固定公开build_middlewares构成26项完整链，50步在第四个响应后、结束hook之前耗尽。自有预算累计移入wrapper；graph节点配置25/最大50→100/最大100（含middleware节点），并保存成对配置备份；token20,000、模型端点/密钥、底座和锁不改。43项非模型回归通过66.875秒，含完整链预算/错误/程序交接、真实MCP回读和幂等。
- 请求专用JSON紧凑序列化不删字段、引用或历史；旧样本工具文本5998→5123字符，不当作provider token节省结论。方案工具携带按业务日期选定并核对哈希的policy_basis；正常流程不重复检索同一政策。执行MCP在事务提交后以可信owner真实回读，并验证操作号；不会绕过交互式管理员审批。
- 第二次真实样本v0.3.3：线程ce133f7d-5368-44dd-a231-4c218c08ea0a，run00a71900-0881-4fce-9b66-5ae62440ec67；查询订单→读Skill→保存reship→生成方案→额外总结。input25,700/output841/total26,541；自有usage/checkpoint/runs一致。run.status=success但stop_reason=token_capped，证明预算正常结束，不代表业务验收成功。新TKT-82DC2E38BFAB待审批，PRP-CEF5A4A1D0F5 pending；没有新操作。
- 程序交接在真实链遗漏宿主追加的budget_warning HumanMessage；v0.3.4改为检查原始request.state已完成工具批次。完整链夹具用17k触发真实提醒，错误/待审批均不再调用provider。真实MCP文本块形态回归与本次checkpoint无模型回放通过；修复后的真实模型效果未重验，不删除或改记已支付的第五次调用。
- 当前4工单/4方案/2操作/4实例/0附件/0跟进；原两工单resolved、旧失败investigating、新待审批。原日期/历史保留。写实例前业务备份20261013T030709959026Z-operator.tar.gz。Docker两处旧通信socket故障采用改名保留恢复，未重置、删除卷/镜像/账户；其他项目容器按自身策略恢复，未单独修改。
- 详见apps/after-sales-agent/docs/agent-validation-v033-20261013.md；私有实际证据在.local/agent-normal-v033-20261013，完整链首次失败/42项回归在.local/agent-normal-20261012。正常完整真实闭环尚未通过，后续异常/图片/记忆/检索/物流尚未进入真实验证。下次付费重放明确新单次范围与授权；不自动重试已触发停止条件的对话。

## 2026-10-13 v0.3.4 正常真实闭环通过（最新）

- 本次用户明确同意1个新正常损坏对话、最多2条消息，实际2条/5次DeepSeek API。订单DEMO-8FA8187B5DA34DA9，工单TKT-D400DCA0C55D revision1，方案PRP-9AC1028F0356，操作OP-1361A7596164；线程2c5457d4-bb5e-4ae2-b6ac-6bbfbd8ce8f3。
- 模型同时读damage-intake Skill/查询订单，再保存reship申报和生成政策方案；代码输出待审批交接。用户授权浏览器自动化在现有交互式管理员会话核验/勾选/备注/审批，Gateway review200及SQLite confirmed approved。第二条模型先读取approved，再经真实签名MCP execute；提交后同owner真实get_ticket回读resolved、操作存在；代码输出完成回执。工作台审计和独立只读SQLite再确认1个操作。不是模型approve、模拟审批或真实发货。
- 首run62d4dc2d-0258-4b38-a2db-0b2924b6ddb3：13,296 tokens、3 calls；执行runfc709a1a-d7d7-4115-a3d7-eece6b9b63c9：19,058、2 calls。两run success/error=null/stop_reason=null；执行轮95.3%软警告后程序正确结束，没有额外provider请求。整对话input31,868/output486/total32,354/cache_read24,832，HTTP/usage/checkpoint/runs一致，金额账单未核对。
- 20,000保持原有每run完成后累计检查，不是整对话/账户金额硬限额；不能称32,354低于20,000。待审批交接/执行回执属于自有确定性程序，非额外模型推理。Skill/模型选工具/真实MCP/人工会话/事务回写首次完整取得证据；单样本不宣称总体成功率或稳定开销。
- 业务库5工单/5方案/3操作/5实例/0附件/0跟进；本次resolved，原两resolved，两未完成样本保持investigating/awaiting_approval。原ORD-2026-0017签收2026-10-08 14:30+08、原订单申报数0；日期/历史未改。写实例前备份20261013T070833954346Z-operator.tar.gz。
- 自动审批审核首次发送操作超时，核对空输入与无run/API后仅重试一次，未重复模型请求；审批前截图捕获失败，动作尚未执行，之后单独工作台审批，最终截图成功。真实证据保留，不将工具故障隐去或称为provider重试。
- 本轮未改业务源码/底座/锁或新增测试；43项先前非模型回归保留。详见apps/after-sales-agent/docs/normal-agent-success-20261013.md，原始证据.local/agent-normal-v034-20261013。下一步转入审批后证据变化；新增真实对话先明确数量/预算/停止边界，再依次图片、记忆、检索、物流。没有自动增加本次单对话授权、购买、发布或部署。

## 2026-10-13 v0.3.5 审批失效与跨会话续办（最新）

- 用户已同意正常闭环后验证审批后证据变化，再依次收尾图片、记忆、检索和物流，并明确允许新增模型请求。新增请求按有界批次推进，保留20,000每run完成后阈值；非模型测试/接口授权持续有效，不重复询问。没有无限调用、新付费后端、购买、发布或部署授权。
- v0.3.5仅在模型请求副本延后旧轮次方案policy_basis正文，保留业务事实、状态、revision和引用；当前正文/原始MCP/checkpoint/审计保持。它不是完全无损正文投影。44项非模型回归通过68.554秒，包括历史/当前政策投影、原对象和宿主提醒；没有远程模型调用。
- 本次DEMO-89EF76252C7E44E7 / TKT-AE92A4E8AC1D：模型读取Skill、签名MCP保存及生成版本1，管理员会话批准PRP-6158C005B1AE；工作台补充证据升revision2，旧方案superseded。模型读取最新状态并明确拒绝沿用旧审批；另一次非模型真实签名MCP execute旧方案返回STALE_PROPOSAL，不冒充模型执行拒绝证据。
- 模型生成版本2新PRP-5DF03772D64B，现有交互式管理员会话核验/填写备注/重新批准。原四轮会话最后run累计20,592，执行tool calls被剥离，stop_reason=token_capped，操作为空。不能将run.status=success写成业务成功或四轮一次通过。
- 新增请求授权内限定另1个会话/1条消息/2次API续办，重新读Skill和数据库审批再经MCP执行新方案；8,934 tokens，resolved/revision2，恰好1个OP-3AFA27C78662。旧新方案、两次审批备注/时间和首次申报日期保留。待审批交接/最终回执由自有程序生成；不是模型approve、模拟数据库审批或真实发货。
- 五run分别13,371 / 14,597 / 8,137 / 20,592 / 8,934，共10次API、input64,519/output1,112/total65,631，初始会话56,697。持久化provider usage/checkpoint与runs已逐轮核对；含预算失败的费用不遗漏，金额账单未核对。长会话在阈值内连续闭环及费用稳定性仍未通过；跨会话续办是本次恢复方法，未宣称已经修复长期上下文开销。
- 写入前备份20261013T082731654538Z-operator.tar.gz。收尾6工单/7方案/4操作/6实例/0附件/0跟进；此前失败样本保持历史。本次没有修改原订单、业务store规则、底座、锁文件、账户密钥、CSRF补丁或其他工作区材料。
- 临时验证入口已关闭，实际health200。重启50秒等待曾超时，随后Application startup complete，不重复重建。收尾重启截断gateway.log，完整HTTP原始日志未归档；缺口明确记录，durable checkpoint/run用量、原始MCP、两次审核与阶段截图保留。后续必须在重启前保存日志。
- 详细报告：apps/after-sales-agent/docs/evidence-change-agent-20261013.md；私有证据：apps/after-sales-agent/.local/agent-evidence-change-20261013/。正常真实闭环证据仍见normal-agent-success-20261013.md。当前完成的是审批失效拒绝/跨会话恢复，图片现场核验、记忆跨会话、检索质量、物流仍按既定次序开展，不宣称全部功能已实测完成。
## 2026-10-14 v0.3.7 最终续办记录（当前）

图片、客户偏好、词法检索和物流已分别取得隔离测试、工作台/接口及有界真实Agent证据，不能由此推断整体成功率。最新报告：apps/after-sales-agent/docs/logistics-validation-20261014.md；各阶段报告见应用README。

物流停滞TKT-3C4CD029C8AD：真实Agent读取已批准调查并执行OP-D47D750E8EE6后为awaiting_followup；10月14日交互式管理员工作台记录明确标记的合成最终跟进后resolved/revision2，只有1个调查操作、1条跟进，原轨迹和首次申报不变。初次申报、方案与审批来自工作台，不称Agent全自主闭环。签收冲突TKT-2EC1C90FD916保持manual_review/revision1、方案0/操作0；新会话真实Agent只读5个工具，正确识别冲突、无有效审批及已遗忘的空偏好，不执行。今日1消息/2次API，input9107/output864/total9971；物流两样本共2消息/4API/19608 tokens，各run分开核对，金额账单未核对。

v0.3.7移除每MCP进程DeerMem预热及固定包缓存，改由Gateway持有无模型DeerMem，通过私有Unix socket提供owner范围只读投影：0600、用途隔离签名、60秒有效期、无写命令/公开HTTP/远端回退。原工具/初始化超时、20,000每run完成后阈值不提高。63项首次回归59通过/2失败/2错误（517.918秒）和首次IPC/MCP组合失败均保留。资源控制下先通过7项MCP回归，再完整68项非模型测试通过108.347秒，远程socket阻断。全套期间仅暂停本项目frontend，finally恢复同一容器；恢复后真实Agent成功读取新IPC。不能称全负载冷启动或长期稳定性验收通过。

最终只读业务计数：9工单/11方案/6操作/9实例/1附件/1物流跟进；原订单申报0，既有未完成样本保留。写入前备份20261014T050014809640Z-operator.tar.gz；修复前备份20261014T052344566719Z-operator.tar.gz。本轮重载前日志已归档；此前v0.3.5完整Gateway日志截断缺口仍存在。checkpoint、runs、provider usage和最终业务快照已离线交叉核对。私有证据.local/continuation-20261014，不发布原始身份/会话材料。

后续工程任务：长会话开销、全负载冷启动、跨真实账号权限、配置恢复、生产构建与持续运行；然后有界系统评测和作品集整理。隔离记忆恢复已完成，但不等于完整配置恢复。保持既有有界少量DeepSeek授权，批前说明范围，异常/超限/usage缺失/循环停止；没有视觉、embedding、模型裁判、自动提取、新付费后端、购买、发布或部署授权。


## 2026-10-14 生产与账号验收补充

本机生产模式复用已安装依赖、固定源与锁；无网络/3GiB/2CPU构建先完整typegen+tsc再Webpack。Gateway单worker无reload，记忆socket仍0600；多worker不在验收范围。仅双loopback公开本机端口。完整结果、失败记录和限制见[本阶段报告](production-stability-20261014.md)。


2026-10-15后续收尾：完整链无模型schema诊断、实际工具全名目录、17项针对性回归和一次真实普通账号检索复验已完成；本次2API/7578 tokens通过，原失败保留。范围与限制见[收尾报告](tool-schema-diagnosis-20261015.md)。
