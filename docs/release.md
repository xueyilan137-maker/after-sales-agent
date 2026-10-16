# GitHub 发布准备

本目录是从原工作区按目录白名单筛出的独立源码仓库。未复制整个工作区，也没有复制 DeerFlow checkout、.local、账号、密钥、数据库、原始日志、截图、checkpoint、备份或其他项目资料。

自有代码采用 MIT；DeerFlow 原文许可证单独保留。上游由脚本按固定 commit 获取，必要补丁独立维护。没有默认账号、预制生产镜像或远程服务地址。历史报告只提供文字证据，不伪称已公开全部原始资料。

发布前从仓库根目录执行：

```powershell
python .\scripts\check-release.py
# 暂存后复查，扫描实际 index 内容而非只扫描工作树：
python .\scripts\check-release.py --staged
git diff --cached --stat
```

检查器拒绝运行/私有目录、数据库、归档、密钥、个人绝对路径与常见凭证格式，并检查本地 Markdown 链接、Python/JSON 语法。它是规则检查，不是“绝无泄漏”的数学保证；公开文件清单仍应人工审阅。仅输出规则名和位置，不回显匹配到的秘密。

本次发布整理的实际检查结果记录在[preparation.json](preparation.json)。新安装未从空缓存完整跑一次，不复用既有机器证据冒充新安装结果。真实模型测试与现有业务没有在发布整理阶段重跑。

离线使用既有本地 Git 对象验证固定 commit 获取、补丁首次应用及重复执行；示例 Setup 重复执行保留配置；Compose 仅做 config --quiet 解析。发布守卫8项回归和日志归档本地替身4场景通过，均没有访问模型或启动容器。

发布副本的 production-local.ps1 补充了首次安装不存在旧容器时跳过其日志归档的分支；已有容器仍必须成功归档，daemon/日志失败仍阻止后续重建。业务/MCP/Skills 原逻辑保持；其他差异是发布文档、私有链接移除、文件筛选和换行规范。原工作区运行脚本未被替换。

发布准备阶段结束时尚未创建 commit、remote、远程仓库或进行上传；这些检查结果是发布前的记录。随后用户已明确授权发布到公开仓库 `xueyilan137-maker/after-sales-agent`。实际发布状态与版本以该仓库 Git 提交历史为准，本页不将准备检查冒充线上部署或全量新机验收。
