# R9 指标口径还原实施计划

> **状态：** 已完成（2026-08-12 实现；2026-08-13 重跑前后端门禁复核）
> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现“正式目录 → 受控字段注释 → 明确标记的 LLM 候选”三级指标口径检索，补齐双口径、维度、来源库表、报表链接和历史 JSONB 兼容。

**Architecture:** 正式口径保存于 PostgreSQL `metric_definitions`；二级注释只能读取后端不可变常量；三级 LLM 只能生成展示文本，不能返回库表、列名或 SQL。旧 `answers.response_payload` 在读取时由 `upgrade_payload()` 幂等补齐安全默认值，不做全表 JSONB 迁移。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy、Alembic、PostgreSQL、Vue 3、TypeScript、pytest、Vitest。

## 全局约束

- 不修改 `yshopping-merchant-ai 4/`；仅以它的 `MetricDefinitionService` 三级语义为参考。
- LLM 单测只使用 Fake LLM；真实 DeepSeek 调用前仍须取得 R3 成本授权。
- 查询标识符只能来自 `app.analytics.contract` / `app.intent.whitelist` 的不可变白名单；参数绑定且强制商家范围。
- `report_url` 后端仅允许绝对 HTTP/HTTPS；前端仅渲染二次校验通过的链接，并带 `target="_blank" rel="noopener noreferrer"`。
- 不手改 `docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts`；由导出链生成。
- 用户确认本计划前，不修改 Task 9 生产代码；计划本身可先提交。

## 字段与职责

保留 `metric_definition` 作为业务口径；新增 `sql_definition/metric_sql_definition`、`dimensions/metric_dimensions`、`source_database/metric_source_database`、`source_table/metric_source_table`、`report_url/metric_report_url`、`generated/metric_generated`、`notice/metric_notice`。

新增来源枚举：`METRIC_CATALOG`、`FIELD_COMMENT`、`AI_GENERATED`。正式/字段注释命中不调用 LLM；LLM 候选必须为 `UNVERIFIED`、`generated=true` 且 `notice` 非空。历史 payload 的兼容默认值为 `[]`、`""`、`false`、`null`，不得伪造来源数据。

### Task 1: 正式目录、迁移与外部契约

**Files:**

- Create: `backend/migrations/versions/20260812_0009_metric_definition_parity.py`
- Modify: `backend/app/models/knowledge.py`、`backend/app/metrics/seed.py`、`backend/app/schemas/chat.py`、`backend/app/schemas/metric.py`、`backend/app/api/routes/metrics.py`
- Test: `backend/tests/api/test_metrics.py`、`backend/tests/unit/schemas/test_chat.py`、`backend/tests/integration/test_migrations.py`

**Produces:** ORM/API 字段 `dimensions`、`source_database`、`source_table`、`report_url`、`generated`、`notice`，以及 METRIC `ChatResponse` 对应的 `metric_*` 字段。

- [x] Step 1 — 在 `test_metrics.py` 写失败测试：`GET /api/metrics/gmv` 必须返回 `sql_definition`、`dimensions=['date','product','category']`、`source_database='public'`、`source_table='orders'`、`generated=false`、`notice=null`；在 `test_chat.py` 令 `metric_sql_definition=None`，断言 `ChatResponse` 校验失败。
- [x] Step 2 — 运行 `cd backend; uv run pytest tests/api/test_metrics.py tests/unit/schemas/test_chat.py -q`，预期因字段不存在失败。
- [x] Step 3 — 增加迁移：JSONB `dimensions`、字符串 `source_database/source_table`、可空 `report_url/notice`、布尔 `generated`；用九个 `METRIC_SEED` 回填（库 `public`、表来自 `METRIC_SPECS`、来源 `METRIC_CATALOG`），迁移末尾移除非空字段 server default。扩 ORM、Seed、端点和 Schema；METRIC 逐项要求新字段，`generated=true` 强制 `UNVERIFIED + AI_GENERATED + 非空 notice`，否则 `notice is None`。
- [x] Step 4 — 用隔离测试库运行 `tests/integration/test_migrations.py tests/api/test_metrics.py tests/unit/schemas/test_chat.py`，预期全部通过且迁移可升级/降级。
- [x] Step 5 — 提交范围为本任务列出的迁移、ORM、Schema、端点与三份测试，提交信息 `feat: extend metric definition contract`。

### Task 2: 受控三级检索

**Files:**

- Create: `backend/app/metrics/field_comments.py`
- Modify: `backend/app/metrics/catalog.py`、`backend/app/repositories/metric.py`、`backend/app/agent/graph.py`
- Test: `backend/tests/unit/metrics/test_catalog.py`、`backend/tests/unit/agent/test_graph.py`

**Produces:** `MetricPayload` 增加全部治理字段；`MetricCatalog.resolve()` 依序查正式目录、字段注释、LLM。

- [x] Step 1 — 写失败矩阵：目录空但 `gmv` 注释命中时返回 `FIELD_COMMENT`、表为 `orders`、Fake LLM 的 `calls=[]`；猴子补丁使二级未命中后，Fake LLM JSON 候选必须为 `AI_GENERATED/UNVERIFIED/generated=true/GENERATED_NOTICE`。
- [x] Step 2 — 运行 `cd backend; uv run pytest tests/unit/metrics/test_catalog.py tests/unit/agent/test_graph.py -q`，预期因不存在字段注释目录失败。
- [x] Step 3 — 创建 `FieldCommentDefinition(metric_code, business_definition, sql_definition, dimensions, source_database, source_table)` 与不可变 `FIELD_COMMENT_DEFINITIONS`；九个键必须等于 `METRIC_SPECS`，每个表必须匹配 `MetricSpec.table`。正式目录命中映射 `METRIC_CATALOG`；目录未命中才查常量；两级均未命中时 LLM 仅读取 `display_name/unit/definition/sql_definition`，模型输出绝不参与库表、维度或 SQL 标识符选择。
- [x] Step 4 — 在 Graph 响应逐项写入新增 `metric_*` 字段，保留 LLM 不可用/JSON 非法的现有显式降级语义。
- [x] Step 5 — 运行 `test_catalog.py test_graph.py test_graph_review.py`，预期正式命中、注释命中、候选、LLM 失败四条路径独立通过；提交信息 `feat: add metric definition retrieval tiers`。

### Task 3: 报表 URL 与旧 JSONB 回放

**Files:**

- Create: `backend/app/metrics/report_url.py`
- Modify: `backend/app/models/knowledge.py`、`backend/app/services/chat_service.py`
- Test: `backend/tests/unit/services/test_chat_service.py`、`backend/tests/unit/schemas/test_chat.py`

**Produces:** `normalize_report_url(value) -> str | None`；`upgrade_payload(payload) -> dict[str, Any]`。

- [x] Step 1 — 写失败测试：`javascript:alert(1)`、`data:text/html,x`、`/internal/report` 均被 URL 规范化器拒绝；删除旧 METRIC payload 的所有新增键后，`_stored_response()` 仍返回 `metric_report_url is None`、`metric_generated is False`、`metric_dimensions == []`。
- [x] Step 2 — 实现 `urlsplit` 检查：仅 `http/https` 且 `netloc` 非空才保留；ORM `@validates('report_url')` 在写入调用它。`_stored_response()` 先调用不修改入参、两次结果相同的 `upgrade_payload()`，仅为旧 METRIC payload `setdefault` 新字段。
- [x] Step 3 — 运行 `cd backend; uv run pytest tests/unit/services/test_chat_service.py tests/unit/schemas/test_chat.py -q`，预期非法 URL 被拒绝、HTTPS 保留、旧 payload 可重放；提交信息 `fix: secure metric reports and payload replay`。

### Task 4: 前端领域映射与可追溯面板

**Files:**

- Modify: `frontend/src/types/chat.ts`、`frontend/src/api/adapters/chat.ts`、`frontend/src/components/insights/MetricDefinitionPanel.vue`
- Test: `frontend/src/api/adapters/chat.spec.ts`、`frontend/src/components/insights/InsightPanels.spec.ts`
- Modify: `docs/fixtures/chat/metric-gmv.json`、`docs/fixtures/chat/metric-refund.json`
- Generate: `docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts`、`frontend/src/api/mock/fixtures.generated.ts`

- [x] Step 1 — 写失败测试：Adapter 将 `metric_sql_definition`、维度、库表和 generated 映射到 `MetricDefinition`；输入 `metric_report_url='javascript:alert(1)'` 时面板没有 `metric-report-link`。
- [x] Step 2 — `MetricDefinition` 扩为 `sqlDefinition/dimensions/sourceDatabase/sourceTable/reportUrl?/generated/notice?`；Adapter 用 `new URL()` 二次仅接受 http/https，否则加入 `contractWarnings` 且不传组件。
- [x] Step 3 — 面板依次展示业务口径、SQL 口径、维度、来源库表、来源、负责人、状态；候选显示 notice；安全外链固定使用 `target="_blank" rel="noopener noreferrer"`。
- [x] Step 4 — 依次运行后端 `export_openapi.py`、前端 codegen 与 fixtures 同步，再运行两个前端定向测试，预期通过且生成文件未手改；提交信息 `feat: show traceable metric definitions`。

### Task 5: 全量门禁与文档收口

**Files:**

- Modify: `docs/PRD.md`、`docs/backend-development-plan.md`、`docs/frontend-development-plan.md`、`docs/yshopping-parity-audit.md`、`docs/project-progress.md`、`plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`

- [x] Step 1 — 后端依次运行 `ruff check app tests`、`ruff format --check app tests`、`mypy app`、隔离数据库 `pytest`；预期全绿，只有已有第三方弃用警告，DeepSeek 调用 0。
- [x] Step 2 — 前端依次运行 `codegen:check`、`fixtures:check`、`typecheck`、`lint`、`format:check`、`test`；预期全绿。
- [x] Step 3 — 文档登记三级顺序、字段注释白名单、双层 URL 防护、payload 升级器与实际测试数；审计标记“指标口径”已修复但不得宣称复刻自由 SQL；下一步改为 Task 10 子计划审阅。
- [x] Step 4 — 运行 `git diff --check`，确认未改参考项目、未提交密钥或测试库地址；提交文档收口，信息 `docs: close metric definition parity task`。

## 自检

- Task 1 覆盖迁移和完整字段；Task 2 覆盖三级检索；Task 3 覆盖 URL 与历史兼容；Task 4 覆盖前端安全展示；Task 5 覆盖全量门禁和文档。
- 不存在自由 SQL、自由列名或模型决定标识符的路径；生成候选始终可见降级。
- 每项都有文件、失败测试、命令与通过条件；没有 TODO/TBD 或“适当处理”占位。

## 执行门

本计划须由用户审阅确认后，使用 `superpowers:executing-plans` 在当前 `feature/integrate-b7-f4` 分支逐任务 TDD 执行。Task 9 完成后，按 roadmap 先产出并审阅 Task 10 纯明细子计划。
