# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。

**最后更新：2026-08-20**

## 当前阶段

P1 的记忆沉淀子 agent 与知识库维护后台均已实现。知识库后台提供管理员独立令牌入口、
三根目录树、团队知识文档读写与 ETag 乐观锁、业务域维护，以及商家记忆的只读展示；
管理员令牌只存在页面内存并仅以 `X-Admin-Token` 发送。

不在当前切片范围的商家自助记忆 `GET/PATCH/DELETE /api/memories`、附件、日报、
知识库版本历史与回滚均未实现。

## 已完成

- 从参考运行时目录导入 23 篇团队知识文档；
- `merchant_memories` 迁移、商家隔离仓储、团队知识优先/商家记忆回退、可见 `MEMORY` 来源，
  以及回答成功后的异步沉淀；
- 知识库目录树固定为 `index`、`业务`、`memory` 三根，业务域固定四板块，记忆仅可读；
- 管理员文档 CRUD、13 个适用的路径/写入错误码、大小写冲突检测、428/412 乐观锁与业务域端点；
- OpenAPI、生成前端类型与领域 Adapter 同步；前端包含内存令牌对话框、目录树、编辑器、
  412 冲突保留输入和只读记忆文档；
- Mock Playwright E2E 覆盖未授权、授权后目录、编辑保存及记忆只读。

## 最近验证

- 专用 PostgreSQL 测试库且无并发写入：`REQUIRE_INTEGRATION_DB=1 uv run pytest` **899 passed**；
  `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app` 全绿；
- 前端 `typecheck`、`lint`、`format:check`、`codegen:check`、`fixtures:check` 与 Vitest **267 passed** 全绿；
  `build` 与 `secrets:check` 全绿（仅既有 ECharts chunk size 非阻塞警告）；
- `npx.cmd playwright test e2e/knowledge-base.spec.ts` **1 passed**；
- 全程使用 Fake/Mock LLM，真实 DeepSeek 调用 **0**、费用 **0**。

## 下一步

1. 根据产品优先级选择 P1 剩余附件/日报，或规划商家自助记忆端点；
2. 如要上线，单独完成 Railway 环境变量、管理员令牌与真实数据库部署验收；
3. 真实模型验收须先按 R3 说明模型、调用次数与费用并获明确许可。

## 风险与约束

- 真实 PostgreSQL 测试必须独占测试库；并发 `TRUNCATE_ALL_TABLES` 曾导致锁竞争；
- 不得调用真实 LLM；所有自动化测试继续 mock/Fake；
- 团队知识与商家记忆保持单向边界：团队知识优先，记忆仅作同商家回退，绝不升级写回团队库；
- 参考目录 `yshopping-merchant-ai 4/` 只读；业务板块按计划指定的四板块执行，
  即使 importer 排除项与之不一致也不得自行扩大范围。
