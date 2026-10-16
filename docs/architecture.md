# 架构与代码导航

DeerFlow 固定 v2.1.0。网页/登录/会话 → Gateway → 配置式 AfterSalesMiddleware → 运行循环 → stdio MCP → 自有业务服务 → SQLite；审批由工作台直接进入受认证的 Gateway API，不经过模型工具。

## 关键边界

1. **身份**：owner 来自 Gateway 可信运行上下文，经用途隔离 HMAC 元数据传给 MCP，不接受模型参数中的 owner。查询和写入按 owner 范围执行。
2. **决策**：模型负责理解与编排；金额、期限、状态迁移和方案资格由业务代码决定。不能用模型输出替代后端判定。
3. **审批**：交互式管理员会话批准，绑定方案 digest、工单 revision、政策与证据摘要、真实时钟过期时间。修改证据使旧审批失效。
4. **执行**：有效审批后在 SQLite 事务中登记操作并回写；唯一约束实现重复执行幂等，返回实际 readback。全部为本地合成操作。
5. **记忆**：Gateway 持有预热的无模型 DeerMem；MCP 通过 0600 私有 Unix socket 访问只读投影，签名绑定 owner/用途/60 秒 TTL，无写命令、公开 HTTP 或远程回退。保持单 worker。
6. **成本与停止**：历史正文仅在模型请求副本中投影，checkpoint 保留；待审批和执行回执可本地生成；工具错误后本地停止。预算响应后核对，可能越限后才能阻止下一次调用。

固定版本插件 middleware 钩子为观察用途；提示词改写和工具拒绝注册在支持的 `extensions_config.middlewares`。不能用观察钩子代替授权，最终权限在 API/MCP/业务事务层核验。

## 代码入口

路径均相对于 `apps/after-sales-agent/`。

| 文件 | 责任 |
| --- | --- |
| [store.py](../apps/after-sales-agent/business/after_sales/store.py) | SQLite/schema、owner 范围、状态迁移、审批摘要与执行事务 |
| [identity.py](../apps/after-sales-agent/business/after_sales/identity.py) | 可信上下文、用途隔离签名及 MCP interceptor |
| [plugin.py](../apps/after-sales-agent/business/after_sales/plugin.py) | 扩展生命周期、工具边界、精确目录、停止与本地交接 |
| [context_projection.py](../apps/after-sales-agent/business/after_sales/context_projection.py) | 请求副本的历史结果压缩与重读指针 |
| [MCP 服务](../apps/after-sales-agent/mcp_server/after_sales_mcp/__main__.py) | 12 定义，模型白名单 10 项，保留两个历史别名但不暴露给模型 |
| [routes.py](../apps/after-sales-agent/business/after_sales/routes.py) | 工作台 HTTP、可信会话及角色边界 |
| [evidence.py](../apps/after-sales-agent/business/after_sales/evidence.py) | 格式/解码/像素/哈希限制，无视觉模型 |
| [customer_memory.py](../apps/after-sales-agent/business/after_sales/customer_memory.py) / [memory_rpc.py](../apps/after-sales-agent/business/after_sales/memory_rpc.py) | DeerMem 适配与私有只读 IPC |
| [policy.py](../apps/after-sales-agent/business/after_sales/policy.py) | 按首次业务日期选择政策，本地词法检索与来源 |
| [Skills](../apps/after-sales-agent/skills/public/damage-intake/SKILL.md) | 业务步骤与缺项收集，不能越过审批 |

选择 SQLite、词法检索与人工确认记忆，是为了让演示状态、引用和审批可核对；没有为项目堆叠向量库、模型裁判、自动记忆抽取或真实外部执行。团队共享队列、跨账号客服受理和多 worker 尚未实现/验证。

维护补丁仅涉及通用 CSRF 缺失恢复；其余业务可靠性修复位于扩展层，不声称已经贡献给 DeerFlow 官方。更详细的带日期决策见[历史工程决策](../apps/after-sales-agent/docs/architecture-decisions.md)。
