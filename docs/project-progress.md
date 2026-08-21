# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。

**最后更新：2026-08-21**

## 当前阶段

P1 的日报已完成：`GET /api/reports/daily` 固定返回 `Asia/Shanghai` 昨日的六项指标与两条建议，使用商家级 `DAILY_REPORT` 系统会话和 `daily-report:{report_date}` 答案幂等键物化结果。并发首次请求回读同一份已完成报告；查询失败或无近七日数据均显式降级，不调用 LLM，也未引入 Cron、Worker 或推送。本地后端与前端门禁均已复跑通过。

P1 的记忆沉淀子 agent 与知识库维护后台的**结构**已实现，本地门禁全绿。

2026-08-21 按 R9 逐条对照参考项目后发现记忆链路存在一处静默行为退化——沉淀时不读历史问答，
导致记忆无法累积；**当天已修复并提交**（`98e40d0`）。同时确认此前登记为"缺口"的
`/api/memories` 一项在参考项目中并不存在，用户已裁定不还原；相关文档说明已删除，
OpenAPI 契约测试永久禁止重新暴露这些路径。

同日核对出的两处记忆缺口——管理员手动记忆压缩端点、`suggestQuestions` 未按历史高频问题排序——
均已实现并通过全量后端门禁。手动压缩沿用我方管理员知识库路径；历史推荐查询使用
savepoint 隔离，统计查询失败只会回落静态推荐，不会污染主聊天事务。

## 已完成

- 从参考运行时目录导入 23 篇团队知识文档；
- `merchant_memories` 迁移、商家隔离仓储、团队知识优先/商家记忆回退、可见 `MEMORY` 来源，
  以及回答成功后的异步沉淀；
- 记忆沉淀已接入**同商家同分类的历史问答**（`AnswerRepository.recent_answers_for_category`，
  取 80 条，2026-08-21 修复），不再是每轮覆盖写入的单句摘要；
- 管理员手动压缩端点 `POST /api/admin/knowledge/memories/compress`：`X-Admin-Token` 鉴权、
  商家存在性校验在费用守卫构造前完成、审计独立提交先于记忆写入；模型不可用时返回可见的
  `degraded` / `degraded_reason`，并仍落盘确定性兜底文本；
- 「猜你想问」已按同商家同分类的历史**高频**问题排序（频次降序、同频按最近回答时间降序），
  静态 `suggestion_alternates` 保持可用；历史查询异常由 savepoint 隔离并回落静态推荐；
- 知识库目录树固定为 `index`、`业务`、`memory` 三根，业务域固定四板块，记忆仅可读；
- 管理员文档 CRUD、13 个适用的路径/写入错误码、大小写冲突检测、428/412 乐观锁与业务域端点；
- OpenAPI、生成前端类型与领域 Adapter 同步；前端包含内存令牌对话框、目录树、编辑器、
  412 冲突保留输入和只读记忆文档；
- Mock Playwright E2E 覆盖未授权、授权后目录、编辑保存及记忆只读。

## 2026-08-21 R9 对照结论

参考项目共 3 个 Controller、14 个端点（`ChatController` 5 个、`AttachmentController` 1 个、
`WikiAdminController` 8 个）。逐条对照结果：

| 项 | 参考项目 | 我方 | 结论 |
| --- | --- | --- | --- |
| 沉淀输入含历史问答 | `recentAnswers(merchantId, 80)` 按分类过滤后一并压缩 | 已接入同款仓储方法 | ✅ **已修复（2026-08-21，`98e40d0`）** |
| `POST /api/wiki/compress` 手动压缩 | 有，可指定 `categoryName` + `manualMarkdown` | `POST /api/admin/knowledge/memories/compress` | ✅ 已修复（2026-08-21）；路径差异已登记为有意偏离 |
| `suggestQuestions` 按历史高频问题排序 | `topCategoryQuestions` 按 `COUNT(*) DESC` 排序 | 已按频次、同频最近时间取同商家同分类历史问题 | ✅ 已修复（2026-08-21） |
| 知识库版本历史与回滚 | **没有**，`version()` 仅 SHA-256 乐观锁 | 428/412 乐观锁已实现 | ✅ 已 1:1 还原 |
| 商家自助记忆端点 | **没有**，商家无任何记忆读写入口 | 无 | ✅ 已裁定不还原（2026-08-21），文档与永久契约已同步 |

处置记录：

1. **`history=[]` 静默退化已修复**。`MemoryService.consolidate()` 的 `history` 形参此前从未被
   传值，参考语义是"该分类下最近 80 条问答的累积压缩"，我方之前是"只有本轮这一问一答"。
   已在 `backend/app/services/memory_agent.py` 接入 `AnswerRepository.recent_answers_for_category`
   并补齐输入内容断言测试（`test_answer_history.py`、`test_memory_agent_history.py`），
   commit `98e40d0`。
2. **`GET/PATCH/DELETE /api/memories` 已按用户裁定撤回**。参考项目本无对应设计；
   文档已同步删除，`test_openapi_chat_contract.py` 的路径断言现为永久契约，差异登记见
   `docs/yshopping-parity-audit.md` §5.9。

## 最近验证

后端门禁于 2026-08-21（本轮）跑出：

- 专用 PostgreSQL 测试库：`REQUIRE_INTEGRATION_DB=1; uv run pytest -q` **930 passed, 1 warning**；
  唯一警告为第三方 LangGraph 的 `LangChainPendingDeprecationWarning`；
- 管理员压缩 API（6 条）、记忆服务降级信号（2 条）、历史高频仓储（5 条）、图节点回落
  （4 条）、既有记忆历史回归（3 条）全部通过；
- 历史推荐的事务回归使用真实 PostgreSQL 在共享 Session 内触发 `LIMIT -1` 查询错误：修复前主回答
  写入遭遇 `InFailedSqlTransaction`，修复后由 `begin_nested()` 隔离，主回答仍以 `SUCCEEDED`
  持久化且 USER/ASSISTANT 消息均落库；
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app` 与前端
  `npm run codegen:check` 全绿；全程使用 Fake/Mock LLM，真实 DeepSeek 调用 **0**、费用 **0**。
- 全程使用 Fake/Mock LLM，真实 DeepSeek 调用 **0**、费用 **0**。

前端门禁**本轮未重跑**，以下结果仍是 2026-08-20 的快照，与本轮后端改动无关联：

- 前端 `typecheck`、`lint`、`format:check`、`codegen:check`、`fixtures:check` 与 Vitest **271 passed** 全绿；
  `build` 与 `secrets:check` 全绿（仅既有 ECharts chunk size 非阻塞警告）；
- `npx.cmd playwright test e2e/knowledge-base.spec.ts` **1 passed**。

## 下一步

按优先级：

1. ~~修 `memory_agent.py:140` 的 `history=[]`~~ **已完成（2026-08-21，`98e40d0`）**；
2. ~~执行 `/api/memories` 裁定的文档同步~~ **已完成（2026-08-21）**：文档已清理，
   OpenAPI 路径断言已正名为永久契约；
3. ~~执行 `plans/2026-08-21-memory-compress-and-history-suggestions.md`~~ **已完成（2026-08-21）**：
   管理员手动压缩端点与历史高频「猜你想问」均已实现；
4. ~~裁定并落地 `docs/specs/2026-08-21-daily-report-contract.md` 里的 8 个问题并实施每日经营报告（B8/F7）~~ **已完成（2026-08-21）**：Q1–Q8 均按 A 实现，日报前后端、Mock、并发幂等与采纳反馈已有定向测试；
5. **T3**：`backend/app/metrics/catalog.py:99` 的 `complete()` 调用仍未上报 usage，
   该次 token 落进未知，`llm_usage` 记账有洞；
6. **B7 九题真实模型验收**（T7）：须先按 R3 说明模型、调用次数与预计费用并获明确许可；
   预算配置已从计划预填值收敛为 `llm_max_calls_per_request=6`、`llm_max_tokens_per_request=20_000`，
   但九题验收本身从未执行；
7. P1 剩余的**附件**：参考项目有 `POST /api/attachments`，我方尚未实现对应服务；详细缺口清单见 `plans/2026-08-21-gap-roadmap.md` §2；
8. 上线另需单独完成 Railway 环境变量、管理员令牌与真实数据库部署验收。

## 风险与约束

- **门禁全绿不等于行为正确**：`history=[]` 曾在 899 passed 的前提下存活到 2026-08-21 才被发现。
  凡是"参考项目传了值、我方传空值"的形参，都要有一条断言输入内容的测试，而不只断言不抛异常；
- 本地 PostgreSQL 测试容器是**一次性数据卷**：`alembic_version` 一旦记录了已被删除/重命名的
  历史迁移号，`command.upgrade(config, "head")` 会直接报错而非自动修复，需重建容器与卷
  （`docker-compose -p borough down postgres && docker volume rm borough_borough_postgres_data`）；
- 真实 PostgreSQL 测试必须独占测试库；并发 `TRUNCATE_ALL_TABLES` 曾导致锁竞争；
- 不得调用真实 LLM；所有自动化测试继续 mock/Fake；
- 团队知识与商家记忆保持单向边界：团队知识优先，记忆仅作同商家回退，绝不升级写回团队库；
- 参考目录 `yshopping-merchant-ai 4/` 只读；业务板块按计划指定的四板块执行，
  即使 importer 排除项与之不一致也不得自行扩大范围。
