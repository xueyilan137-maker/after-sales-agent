# 固定底座适配补丁

底座来源：bytedance/deer-flow，MIT License，`v2.1.0`，提交
`345f08be00c8a9495079b732a39b46aa9af1584e`。

`deerflow-v2.1.0-csrf-recovery.patch` 是本项目新增的工程适配：

- 有效登录会话缺失 CSRF Cookie 时，成功的同源或已允许来源的
  `GET /api/v1/auth/me` 补发 Cookie，使用现有登录持久化策略。
- 前端 REST 与 LangGraph SDK 共用异步恢复：并发请求共用一次 GET，
  等待 Cookie 可读后再发送写请求，恢复请求超时为 10 秒。
- 原有令牌存在时保持不变；未登录、非交互式登录和不允许的来源不会获得恢复令牌。
- 后端继续要求 CSRF Cookie 与请求头匹配；原写请求不自动重放。
- 不将令牌放入响应体，不记录令牌或密码。

启动脚本先核对固定 commit，再检查补丁是否已应用；未应用时先做
`git apply --check`，有冲突就保留已有编辑并报错。补丁包含三份源码改动
和对应前后端模块说明，实际 checkout 因此有受管理的 tracked 修改。
上游依赖锁文件和版本号未改变。

新安装先执行根目录 bootstrap-deerflow.ps1，再按[安装说明](../../../docs/setup.md)构建和运行。
生产 frontend 使用有界构建入口后运行 pnpm start；backend 使用源码挂载，
重载前归档实际文件和 docker stdout 日志。不要用旧开发重启命令替代生产入口。
已有工程与有界真实会话验证见[验证索引](../../../docs/validation.md)；
未向上游提交 PR，也未验证上游最新版本是否仍需要此补丁。
