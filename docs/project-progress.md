# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。

**最后更新：2026-08-21**

## 当前阶段

P1 的记忆沉淀子 agent 与知识库维护后台的**结构**已实现，本地门禁全绿。

2026-08-21 按 R9 逐条对照参考项目后发现记忆链路存在一处静默行为退化——沉淀时不读历史问答，
导致记忆无法累积；**当天已修复并提交**（`98e40d0`）。同时确认此前登记为"缺口"的
`/api/memories` 一项在参考项目中并不存在，用户已裁定不还原、代码零改动，
但相关文档说明的删除尚未执行（见下方「下一步」）。

同日还核对出两处新缺口——管理员手动记忆压缩端点、`suggestQuestions` 未按历史高频问题排序——
均已排出可执行计划，尚未实施，见「下一步」。

## 已完成

- 从参考运行时目录导入 23 篇团队知识文档；
- `merchant_memories` 迁移、商家隔离仓储、团队知识优先/商家记忆回退、可见 `MEMORY` 来源，
  以及回答成功后的异步沉淀；
- 记忆沉淀已接入**同商家同分类的历史问答**（`AnswerRepository.recent_answers_for_category`，
  取 80 条，2026-08-21 修复），不再是每轮覆盖写入的单句摘要；
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
| `POST /api/wiki/compress` 手动压缩 | 有，可指定 `categoryName` + `manualMarkdown` | 无任何等价物 | 🔴 真实缺口，已排入 `plans/2026-08-21-memory-compress-and-history-suggestions.md` Task 1 |
| `suggestQuestions` 按历史高频问题排序 | `topCategoryQuestions` 按 `COUNT(*) DESC` 排序 | 纯静态预置，与历史无关 | 🔴 真实缺口（2026-08-21 新发现），已排入同上 Task 2 |
| 知识库版本历史与回滚 | **没有**，`version()` 仅 SHA-256 乐观锁 | 428/412 乐观锁已实现 | ✅ 已 1:1 还原 |
| 商家自助记忆端点 | **没有**，商家无任何记忆读写入口 | 无 | ✅ 已裁定不还原（2026-08-21），**文档删除待执行**，见下 |

处置记录：

1. **`history=[]` 静默退化已修复**。`MemoryService.consolidate()` 的 `history` 形参此前从未被
   传值，参考语义是"该分类下最近 80 条问答的累积压缩"，我方之前是"只有本轮这一问一答"。
   已在 `backend/app/services/memory_agent.py` 接入 `AnswerRepository.recent_answers_for_category`
   并补齐输入内容断言测试（`test_answer_history.py`、`test_memory_agent_history.py`），
   commit `98e40d0`。
2. **`AGENTS.md` §10.2 的 `GET/PATCH/DELETE /api/memories` 三条已由用户裁定为不还原**，
   参考项目本无对应设计；代码侧本就零实现，无需改动，**但 `AGENTS.md` §10.2、
   `docs/PRD.md:585-587`、`docs/backend-development-plan.md:655-657`/668/1653-1655
   仍残留这三条端点的说明，尚未按裁定删除**——这是纯文档清理，排入
   `plans/2026-08-21-gap-roadmap.md` §5 第一项，处置记录见其 §3（D2）。

## 最近验证

后端门禁于 2026-08-21（本轮，含 `history=[]` 修复后的重新验证）跑出：

- 专用 PostgreSQL 测试库（本地 Docker 卷因残留旧迁移版本号 `20260808_0005` 而失效，
  已重建）：`REQUIRE_INTEGRATION_DB=1 uv run pytest` **904 passed, 3 failed**——
  失败全部集中在 `backend/tests/api/test_knowledge_memory_compress.py`，是尚未实现的
  管理员手动记忆压缩端点（404），已排入
  `plans/2026-08-21-memory-compress-and-history-suggestions.md` Task 1，非本轮回归；
- `uv run ruff format --check .`、`uv run mypy app` 全绿；`uv run ruff check .` 仅在
  `backend/app/schemas/knowledge.py` 报已知的 `Field, Field` 重复导入（同一份移交计划里修），
  非本轮改动引入；
- 记忆沉淀历史问答修复本身：`test_answer_history.py`（3 条）、`test_memory_agent_history.py`
  （1 条）全部通过，并做过反转验证（临时改回 `history=[]` 确认测试会红，再恢复确认转绿）；
- 全程使用 Fake/Mock LLM，真实 DeepSeek 调用 **0**、费用 **0**。

前端门禁**本轮未重跑**，以下结果仍是 2026-08-20 的快照，与本轮后端改动无关联：

- 前端 `typecheck`、`lint`、`format:check`、`codegen:check`、`fixtures:check` 与 Vitest **267 passed** 全绿；
  `build` 与 `secrets:check` 全绿（仅既有 ECharts chunk size 非阻塞警告）；
- `npx.cmd playwright test e2e/knowledge-base.spec.ts` **1 passed**。

## 下一步

按优先级：

1. ~~修 `memory_agent.py:140` 的 `history=[]`~~ **已完成（2026-08-21，`98e40d0`）**；
2. **执行 `/api/memories` 裁定的文档同步**（纯文档，零代码）：删除
   `AGENTS.md` §10.2、`docs/PRD.md:585-587`、`docs/backend-development-plan.md:655-657`/
   668/1653-1655 中残留的 `GET/PATCH/DELETE /api/memories` 说明，
   清单见 `plans/2026-08-21-gap-roadmap.md` §5；
3. **执行 `plans/2026-08-21-memory-compress-and-history-suggestions.md`**：
   Task 1 补管理员手动记忆压缩端点（对齐参考 `POST /api/wiki/compress`，
   已裁定路径改为 `POST /api/admin/knowledge/memories/compress`）；
   Task 2 让「猜你想问」接入商家历史高频问题（`topCategoryQuestions`，2026-08-21 新发现的缺口）；
4. **裁定并落地 `docs/specs/2026-08-21-daily-report-contract.md`** 里待裁定的 8 个问题，
   再排每日经营报告（B8/F7）的可执行实施计划；
5. **T3**：`backend/app/metrics/catalog.py:99` 的 `complete()` 调用仍未上报 usage，
   该次 token 落进未知，`llm_usage` 记账有洞；
6. **B7 九题真实模型验收**（T7）：须先按 R3 说明模型、调用次数与预计费用并获明确许可；
   预算配置已从计划预填值收敛为 `llm_max_calls_per_request=6`、`llm_max_tokens_per_request=20_000`，
   但九题验收本身从未执行；
7. P1 剩余的**附件**与**日报**：参考项目有 `POST /api/attachments` 与 `GET /api/daily-report`，
   我方 `backend/app/services/` 下无任何对应服务，属未开工阶段；详细缺口清单见
   `plans/2026-08-21-gap-roadmap.md` §2、§4；
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
