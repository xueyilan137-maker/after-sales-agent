# 验证材料、失败与实际边界

公开的是文字记录、源码和固定合成样本；原始日志、截图、Cookie、账号、数据库、checkpoint、签名材料和私有恢复快照不随仓库发布。报告中的 `.local/` 路径说明证据原始保存位置，不是可下载附件。文字报告可供追溯，但不等同公开了全部原始证据或第三方独立审计。

| 阅读顺序 | 报告 | 主要结论 |
| --- | --- | --- |
| 1 | [最新工具 schema 诊断](../apps/after-sales-agent/docs/tool-schema-diagnosis-20261015.md) | 完整链本地绑定正确；实际工具全名目录修复；17 项/13.095 秒；真实单次修复后查询通过，2 API/7,578 tokens |
| 2 | [隔离恢复与系统评测](../apps/after-sales-agent/docs/recovery-evaluation-20261015.md) | 独立无网络 Gateway 恢复；8/8 HTTP 样本；真实初批 1/2，检索错误及停止修复复验失败均保留 |
| 3 | [四轮同会话与上下文](../apps/after-sales-agent/docs/long-context-validation-20261015.md) | 4 消息/8 API/50,691 tokens；四 run 单独核对；人工重新审批后 resolved，唯一操作 |
| 4 | [生产与账号验证](../apps/after-sales-agent/docs/production-stability-20261014.md) | 本机生产模式、四服务共存回归、A/B 真账号隔离、两份前端产物各自的有界 HTTP 采样 |
| 5 | [图片](../apps/after-sales-agent/docs/image-evidence-validation-20261013.md) / [记忆](../apps/after-sales-agent/docs/memory-validation-20261013.md) | 人工核验与失效；人工偏好的跨会话读取/纠正/遗忘，无视觉或自动抽取 |
| 6 | [检索](../apps/after-sales-agent/docs/retrieval-validation-20261013.md) / [物流](../apps/after-sales-agent/docs/logistics-validation-20261014.md) | 日期/版本/引用、无结果；合成调查执行后等待人工跟进、签收冲突人工处理 |
| 历史 | [正常闭环](../apps/after-sales-agent/docs/normal-agent-success-20261013.md) / [证据变化](../apps/after-sales-agent/docs/evidence-change-agent-20261013.md) | 早期较高 token 成本、失败、审批失效及恢复过程，不能当最终成本结论 |

## 不合并成一个“通过率”

工程测试、HTTP 测试与真实模型样本的对象不同。8/8 是隔离业务 HTTP 固定样本，不是模型准确率。真实 Agent 初批核心判定是 1/2；第二个样本错误工具名被拒绝，之后错误停止修复的复验仍未完成检索。最后全名目录修复后另记一次通过，原分数不改。

四轮同会话均未超过 20,000 每 run 响应后阈值，但总计 50,691 tokens。历史请求前缀字符下降 18.8%/15.8% 不是实际 token/金额降幅，也没有同条件真实 A/B 成本实验。

## 已知不足

- 单个修复后检索样本不足以证明工具选择普遍可靠。
- 稳定性只做有界 HTTP 共存采样，无最大容量、24 小时运行或真实模型并发证据。
- 权限覆盖已有 admin/user owner 边界，未覆盖跨管理员写、封禁/撤权和团队共享队列。
- 当前完整恢复快照偏好为空；非空偏好恢复来自另一个历史演练，不能混称本次结果。
- 早期 v0.3.5/故障前完整 Gateway HTTP 日志存在缺口；后续已同时归档实际文件与 stdout，不能声称所有历史日志完整。
- 没有真实客户数据集、真实支付/发货/承运方系统或视觉分析；案例是设计示例。

新机器安装流程此次只完成静态/离线检查，尚未从空 Docker 缓存重跑全量构建。仓库公开之前的文件审查见[发布记录](release.md)。
