# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。

**最后更新：2026-08-20**

## 当前阶段

P1 记忆沉淀子 agent 已完成：`merchant_memories` 迁移、商家隔离仓储、团队知识优先/商家记忆回退、
`analysis_sources=MEMORY` 可见来源、回答成功落库后的 `BackgroundTasks` 异步沉淀，以及双库防污染不变量均已落地。
知识库已从参考运行时目录导入 **23** 篇团队文档。下一阶段是
`plans/2026-08-20-knowledge-admin-backend.md` 的知识库维护后台 Task 1–11。

不在当前切片范围的商家自助记忆 `GET/PATCH/DELETE /api/memories`、附件、日报、版本历史与回滚均未实现。

## 已完成

- `merchant_memories` 表、唯一约束 `(merchant_id, category)`、状态与版本控制，以及 migration
  `upgrade → downgrade → upgrade` 往返验证；
- `MerchantMemoryRepository` 的按商家读取、覆盖写入、归档过滤与跨商家隔离；同一 Session 重复 upsert 会刷新 ORM identity map，正确返回新内容和版本；
- 独立记忆提示词与契约测试；预算耗尽时确定性兜底，LLM/数据库错误仅记录日志；
- 团队知识命中时不读取记忆，团队知识未命中才读取该商家的对应分类记忆；记忆来源通过 `MEMORY` 明确显示；
- 回答成功持久化后异步登记沉淀任务；任务自开数据库 Session、单独计费预算，不阻塞 JSON 或 SSE 的 `done` 事件；
- 四条双库防污染不变量：记忆服务/调度器不接触团队知识文档，团队知识仓储没有记忆写入路径，兼容标记固定为 `本轮自动沉淀`。

## 最近验证

- 在独立 PostgreSQL 测试库、确认无其他 agent 并发写入的前提下：
  `REQUIRE_INTEGRATION_DB=1 uv run pytest` **821 passed / 0 skipped / 0 failed**；
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app` 全绿（94 个源文件）；
- Task 6 SSE 回归和 Task 7 四条不变量均通过；全程使用 Fake/确定性 LLM，真实 DeepSeek 调用 **0**、费用 **0**。

## 下一步

1. 按知识库维护后台计划从 Task 1 开始，逐条 TDD 实施；
2. 完成后运行后端和前端全量门禁，并同步 OpenAPI/生成类型（如契约有变化）；
3. 真实模型记忆压缩验收须先按 R3 单独说明模型、调用次数与费用并获得许可。

## 风险与约束

- 真实 PostgreSQL 测试必须独占测试库；并发 `TRUNCATE_ALL_TABLES` 曾导致锁竞争；
- 不得调用真实 LLM；所有自动化测试继续 mock/Fake；
- 团队知识与商家记忆必须保持单向边界：团队知识优先，记忆只作同商家回退，绝不升级写回团队库；
- 参考目录 `yshopping-merchant-ai 4/` 只读；知识库维护后台的业务板块以计划指定的四板块为准，
  即使当前 importer 排除项与之不一致也不得自行扩大范围。
