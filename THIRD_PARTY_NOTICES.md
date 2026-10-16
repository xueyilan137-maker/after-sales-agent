# 第三方代码与许可证

本项目基于 [bytedance/deer-flow](https://github.com/bytedance/deer-flow)，固定 v2.1.0 / `345f08be00c8a9495079b732a39b46aa9af1584e`。

DeerFlow Copyright (c) 2025 Bytedance Ltd. and/or its affiliates；Copyright (c) 2025-2026 DeerFlow Authors。MIT 许可证原文保留在 [third_party/DeerFlow-LICENSE](third_party/DeerFlow-LICENSE)。底座由脚本获取，不随本仓库复制；获取后仍保留上游 LICENSE。

`apps/after-sales-agent/patches/deerflow-v2.1.0-csrf-recovery.patch` 包含修改和上游上下文，沿用上游 MIT 声明。`docker/frontend.production-source.Dockerfile` 基于上游依赖镜像；`local.ps1` 从固定上游 Dockerfile 生成带来源注释的 HTTPS APT/有界下载重试派生文件，生成物不提交。

自有业务代码、MCP、Skills、配置与文档按根目录 MIT 许可提供。DeerFlow 提供的网页、认证、harness、MCP 传输与 DeerMem 不属于本项目原创。项目未获得或声称获得 DeerFlow 官方背书。

Python/前端依赖仍使用固定上游 uv/pnpm 锁文件，不在本仓库重复维护。MCP、FastAPI、LangChain、Pillow、Next.js 等依赖及容器基础软件的许可证以各包声明为准；不将根目录 MIT 声明解释为覆盖全部第三方内容。发布二进制镜像时需另行核对镜像所含依赖与通知，本次仅准备源码仓库。
