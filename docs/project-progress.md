# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。每次完成一段可验证工作后，更新日期、状态、验证结果、下一步和风险。

**最后更新：2026-08-06**

## 当前阶段

- 后端：**B4「安全经营数据查询」已收口并完成终审修复轮**，分支为 `feature/b4-safe-analytics-query`。Task 1–10 均已实现、复查并提交（Task 10 在 `72b2190`，REFUND 明细路由修复在 `7d28552`）。终审修复轮已提交（`b174bd9` 修掉 1 Critical + 6 Important，`50a28e6` 清理指向本阶段的过期文案并加机械防线）。
- 后端：**B5「回答、图表和 Reviewer」、B6「反馈与 CSV 导出」代码已完成并提交**，分支 `feature/b5-b6-answer-feedback-export`（提交 `7c60b12`/`18ba978`/`b494277`/`acc7efa`，2026-08-06）。之前这批工作只存在于本地 worktree 且未提交；本轮先修完 `ruff check`/`ruff format` 未通过的 10 处问题（都在下面提到的 B7 附带代码里），再按 Task 边界拆成 4 个提交落地。分支去向（合并/开 PR/保留）尚未决定。
- **B7「Railway、费用防护与 MVP 收口」未完成，但已有部分基础设施随 B6 提交顺带落地**：`app/llm/guard.py`（`LlmCostGuard`，按 `llm_daily_budget` 表原子扣减/回填每日 token 预算）、`app/core/rate_limit.py`（进程内滑动窗口限流）、`app/core/client_ip.py`（仅在配置可信代理跳数时解析 `X-Forwarded-For`）、`Settings` 里的 `admin_token`/`trusted_proxy_*`/`llm_daily_budget_tokens` 等字段，均已实现并接入 `main.py`/`dependencies.py`/`chat_service.py` 的运行时路径，`ruff`/`mypy` 全绿。**但这几个模块本身没有任何单元/集成测试**——§B7「必测」明确要求的「10 个并发请求逼近预算边界不超发」「伪造 `X-Forwarded-For` 不能重置限流计数」两类测试都不存在，只有 `Settings` 字段校验有测试覆盖。Docker、Railway 部署配置、`GET /api/admin/ops/status` 运维端点、结构化可观测性（LLM 用量/降级/限流命中计数）均未开始（Dockerfile 本身在初始提交就有且大致合规，但那是 B0 遗留，不是本轮工作）。**不要把这批代码的存在当作 B7 完成的证据**，动手前先补齐必测用例。
- 前端：F0、F1、F2「Mock 会话闭环」已完成；下一阶段为 F3「API 契约与真实会话接入」。F3 开工前仍需补充设计说明与逐 Task 实施计划。前端目前仍对接 Mock，尚未消费 B5/B6 的新接口。
- F1 遗留：1440×1000 人工视觉比对待本地 Windows Computer Use helper 可用后补做；不影响已通过的结构、几何和无障碍自动化验收。

## 已完成

- 后端 B0–B3：FastAPI 工程、演示商家身份与商家隔离、PostgreSQL/Alembic、会话和回答持久化、Chat JSON/SSE 双路径、幂等、跨商家审计和服务端推荐问题；指标/维度/筛选白名单、知识检索、Fake/DeepSeek LLM Client、两阶段结构化意图和 LangGraph 问答图均已落地。真实 DeepSeek 尚未调用。
- 后端 B4 Task 1–2：创建订单、订单项、退款、退货、商品和工单六张经营数据表与迁移；完成可重复的 180 天演示经营数据 Seed。
- 后端 B4 Task 3–4：建立指标、维度与筛选 SQL 契约，完成业务时区日期解析和查询范围控制；完全落在未来的日期范围会显式拒绝，不再被静默截断。
- 后端 B4 Task 5–6：完成受控指标聚合和五类受控明细查询。已修复订单按商品/类目拆分时的 join 放大问题：GMV 改按订单项金额聚合，订单数去重，并由真实 PostgreSQL 回归测试覆盖。
- 后端 B4 Task 7：完成 Safe Query Service，按白名单路由指标和明细查询，强制商家范围、绑定筛选值、限制预览行数，并确保拒绝原因与查询计划不暴露表名、列名或 SQL 片段。
- 后端 B4 Task 8：新增 `GET /api/metrics/{code}` 指标口径接口；OpenAPI、`docs/api.md`/`docs/api.json` 和前端生成类型已同步。已废弃指标可供口径面板查询，但不会重新进入聊天查询路径。
- 后端 B4 Task 9：`MerchantQaGraph` 的 `query_data` 节点已接入 `SafeQueryService`。`METRIC` 和 `DETAIL` 回答可返回真实数据行、总数、截断状态、查询计划和 `DATABASE` 数据来源；没有查询服务、查询被拒绝或失败时仍返回可见降级；有查询结果时不再输出否认查询发生的建议文案。
- 后端 B4 Task 10：新增 `tests/integration/services/test_safe_query_security.py`（6 个用例），把§B4 验收清单里「跨商家隔离」「SQL 注入」「180 天上限」「statement timeout」「拒绝原因不泄漏 SQL/表名」逐条钉成可独立失败的测试（跨商家用例特意让两个商家在同一天持有不同金额的数据，避免用两个空集合互相比较导致测不出回归）；`tests/integration/test_migrations.py` 补充断言六张经营表由迁移建出。详见 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/task-10-report.md`。
- 后端 B4 收尾（`7d28552`）：`REFUND` 分类的明细按「维度/筛选字段 → 分类关键词 → 兜底查退款」三级信号分流到 `returns` 或 `refunds`。此前 `DETAIL_BY_CATEGORY` 把 REFUND 写死指向 `refunds`，退货明细永远查不到，§B4 验收的「退货明细可查询」实际不可达。分流规则写在 `docs/backend-development-plan.md` §B4「实现说明」的第 4 条偏离里。
- 后端 B4 终审修复轮（2026-08-05，`b174bd9`、`50a28e6`）：修掉 1 条 Critical 与 6 条 Important——`ChatResponse.answer` 有查询结果时不再否认查询发生过（自洽性不变量扩到 `answer`/`recommendations`/`quality_notes`/`degraded_reason` 四个字段）；仓储与问答图之间补上 `SQLAlchemyError → UnsupportedQueryError` 异常边界，并校验 `date` 筛选值、夹紧 `limit` 下界，合法意图不再可能返回 500；`scripts/seed_demo_analytics.py` 补生产环境护栏、`--dry-run`，默认 `--end-date` 改按业务时区推导；商品明细改为不按业务日过滤（`DetailSpec.date_filtered`）；补齐商品与工单两张明细表、`support_ticket_count` 聚合的运行时测试，以及「契约列名 ↔ ORM 列」的参数化不变量。
- 后端 B4 文案卫生防线（`50a28e6`）：`test_stage_reference_hygiene.py` 用 AST 扫 `app/agent/**` 的非 docstring 字符串字面量、并递归扫每个已发布 fixture 的字符串值，禁止出现指向**当前阶段**的前向引用（指向后续阶段的引用是诚实的，不禁）。指向本阶段的「将在 B4 接入」两次躲过人工评审——一次漏在 `answer`、一次漏在 `fallback_reason`——所以改用机械防线。**该测试的 `CURRENT_STAGE` 常量需在每个阶段合并时更新**（本轮已随 B6 提交改成 `"B6"`）。同轮补齐 `DIMENSION_SPECS` 的「契约列名 ↔ ORM 列」参数化不变量。
- 前端 F0–F2：Vue 3 + TypeScript + Vite 工程、三栏商家助手布局、SSE 解析、Mock 传输、会话状态机、取消/重试、演示商家切换、会话历史与轮次目录均已交付；F2 审查整改已包含降级状态展示、商家切换清理和并发提交保护。
- 后端 B5（`7c60b12`）：`VisualizationService`（只用 `QueryResult` 已登记的维度/指标列生成图表，不信任模型字段名）、`AnswerService`（结构化回答草稿 + 本地确定性校验：数字幻觉、非加和指标合计、内部标识符泄露三类拦截）、`ReviewService`（独立 Reviewer，只出「通过/问题列表」，不改写回答，最多两轮）均已接入 `MerchantQaGraph`；`quality_status` 覆盖 `PASSED`/`DEGRADED`/`FAILED`/`NOT_RUN`，`quality_attempts`/`quality_notes` 如实记录。
- 后端 B6（`18ba978`/`b494277`/`acc7efa`）：`POST /api/answers/{id}/feedback`（商家范围内幂等采纳/点赞点踩，跨商家 403 + 审计）、`GET /api/exports/{id}`（HMAC 签名 URL、15 分钟过期、下载时重新执行受控明细查询、UTF-8 BOM、公式注入防护、`Referrer-Policy: no-referrer`）、`export_files` 迁移与 `ChatService` 导出接线（只在 DETAIL 成功且未降级时创建导出记录）均已实现。此前一轮复审已修过 5 处问题（导出 CSV 双重 BOM、本地校验缺两条方案要求的检查、导出记录未排除降级回答、签名密钥兜底值重复、feedback/exports 路由完全没有 HTTP 层测试），新增 24 条测试后全量后端测试从 628 涨到 652 passed（该次数字未在本轮重新用真实 Postgres 复核，见「最近验证」）。

## 最近验证

- B4 Task 5 的聚合修复：目标 PostgreSQL 集成测试 12 项通过；全量后端测试 510 项通过。
- B4 Task 7 修复后：目标测试 15 项通过；全量后端测试 528 项通过。
- B4 Task 8：口径端点及 OpenAPI/前端类型同步已完成，`codegen:check` 通过。
- B4 Task 9：后端测试 536 项通过；前端测试 118 项通过；fixture 漂移检查通过。
- **B4 Task 10（2026-08-05，真实库实跑）**：在测试用 PostgreSQL（`borough_test`）上依次执行
  `alembic upgrade head` → 播种三个演示商家 → `scripts/seed_demo_analytics.py`（写入 17538 行）→
  全量 `pytest`，**544 passed、0 skipped**（较收口前的 538 新增 6 条安全回归用例）。
  `ruff check`、`ruff format --check`、`mypy`（69 个源文件）全绿。
  三条最容易「测不出回归」的用例做过手工变异验证：临时把商家过滤条件改成恒真、
  把 180 天截断分支临时禁用，两次都能让对应测试真实失败（分别报出 1099.00 的跨商家泄漏总额、
  和缺失的截断说明），验证后已还原，`git diff` 确认改动未残留。
- **B4 终审修复轮（2026-08-05）**：后端 **612 passed、0 skipped**（较修复前的 550 新增 62 条），
  `ruff check`、`ruff format --check`、`mypy`（69 个源文件）全绿；Chat Fixture 已重新导出并同步前端，
  `fixtures:check` 一致，前端 **118 passed**、`lint`/`format:check` 全绿。
  商品明细的时间窗修复做过手工变异验证：把 `DETAIL_SPECS["products"].date_filtered` 改回 `True`，
  4 条新用例（契约层 1 条 + 仓储层 2 条 + 服务层 1 条）同时真实失败，验证后已还原。
- **B5/B6 提交前复核（2026-08-06）**：提交前发现 `ruff check` 有 21 处错误（导入排序 2 处 + 行长超限
  19 处，全部集中在 B6 提交里附带的 B7 限流/成本守卫代码，以及 `answer_service.py`/`operations.py`/
  迁移文件里少数几行）、`ruff format --check` 要求重排 15 个文件——**此前记录的「652 passed，ruff/mypy
  全绿」并不准确，本轮已实际修复并重新验证**：修复后 `ruff check`/`ruff format --check`/`mypy`（86 个
  源文件）全绿。因本机 Docker Desktop 引擎当时不可用（`npipe` 连接失败），**本轮只重新跑通了非 DB 用例
  （549 passed、112 项因缺数据库被跳过），没有重新用真实 PostgreSQL 复核此前声称的 652 passed**；
  合并/开 PR 前必须先起 `docker-compose -p borough up -d postgres` 补跑一次
  `REQUIRE_INTEGRATION_DB=1 pytest`。`docs/api.json` 当时相对实际 FastAPI schema 有漂移（403 状态码
  说明文案），已用 `uv run python ../scripts/export_openapi.py` 重新导出并随 B6 Task 5 提交。

## 下一步

1. **合并/PR 前先补一次真实数据库回归**：起 Postgres 容器后跑 `REQUIRE_INTEGRATION_DB=1 pytest`，
   确认 112 项被跳过的集成用例（含 B4 安全回归、B6 导出/反馈的商家隔离用例）依然全绿，再决定
   `feature/b5-b6-answer-feedback-export` 是合并、开 PR 还是保留待后续处理。
2. **B7 落地前先给已存在的费用防护/限流代码补测试**：`app/llm/guard.py`、`app/core/rate_limit.py`、
   `app/core/client_ip.py`、`app/repositories/llm_budget.py` 已经在运行时路径上生效，但§B7「必测」
   要求的并发预算不超发、伪造转发头不能绕过限流两类测试都不存在，属于活跃风险而非完成项。
3. **B7 剩余工作**：Docker 优雅关闭与合理 worker 数、Railway 部署配置（健康检查、CORS 精确 Origin、
   Migration 发布步骤）、`GET /api/admin/ops/status` 运维端点、结构化可观测性（LLM 用量、降级计数、
   限流命中计数）。详见 `docs/backend-development-plan.md` §B7。
4. **前端 F3「API 契约与真实会话接入」可与 B7 并行**：F3 依赖的是已完成的后端契约（B0–B6），
   不必等 B7 部署收口才开工；开工前先补设计说明与逐 Task 实施计划，
   接入真实 HTTP 传输、`Authorization` 头与统一错误处理，不重写已交付的 SSE、Adapter 和 Store 主路径。
5. `feature/b4-safe-analytics-query` 分支去向仍待决定：是否推送并开 PR（代码层面已全部通过终审）。

## 风险与约束

- 未获用户明确同意，不得调用真实 DeepSeek API、收费 OCR 或日报生成；单元测试必须 mock LLM。真实模型调用前须先说明模型、调用次数和预期费用。
- 商家身份只可由 Bearer Token 解析；后端所有经营查询必须强制注入 `merchant_id`，不得信任前端传入的商家编号。
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 常量目前是 `"B6"`，**进入 B7 时必须改成 `"B7"`**，否则该防线会继续只挡 B6 字样而放过新的过期文案。
- **已接入运行时但缺测试的 B7 代码是活跃风险**：`LlmCostGuard`（每日预算原子扣减/回填）、
  `SlidingWindowRateLimiter`、`resolve_client_ip`（可信代理跳数解析）目前唯一的保障是 `ruff`/`mypy`
  和「代码能跑通已有测试」——没有任何测试验证并发场景下预算不超发、或伪造 `X-Forwarded-For` 头无法
  绕过限流，这两条正是 §B7「必测」明确要求的。部署前必须补齐。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码、文案和资源必须使用 Borough。
- 后端 B4 的具体 Task 状态以 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md` 和 Git 提交记录为准；该目录被 `.gitignore` 忽略，只存在于产出它的那个工作副本里，不会随分支/worktree 一起出现。B5/B6 本轮没有对应的 SDD 账本，本文件是这段工作的权威摘要。

## 关键入口

- `AGENTS.md`：项目规则、目录与开发顺序。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/backend-development-plan.md`：后端阶段、API/SSE 契约与 B4–B9 顺序。
- `docs/frontend-development-plan.md`：前端 F0–F9 阶段计划。
- `backend/app/services/safe_query.py`：B4 受控查询应用服务；`ExportSpec`/`export_detail` 供 B6 导出复用。
- `backend/app/repositories/analytics.py`：B4 指标聚合与明细数据访问；B6 的 `export_detail` 也在这里。
- `backend/app/agent/graph.py`：B4 真实查询、B5 回答/审核编排接入问答图的落点。
- `backend/app/services/answer_service.py`、`review_service.py`、`visualization_service.py`：B5 回答草稿、独立 Reviewer 与安全图表。
- `backend/app/services/export_service.py`、`feedback_service.py`：B6 签名 CSV 导出与商家反馈。
- `backend/app/api/routes/exports.py`、`feedback.py`：B6 对外端点。
- `backend/app/llm/guard.py`、`app/core/rate_limit.py`、`app/core/client_ip.py`、`app/repositories/llm_budget.py`：B7 费用防护/限流/可信代理 IP 基础设施，已接入运行时但**无专属测试**，见上方风险条目。
- `backend/tests/integration/services/test_safe_query_security.py`：B4 §验收清单的安全回归测试（跨商家隔离、SQL 注入、180 天上限、statement timeout、拒绝原因不泄漏 SQL/表名）。
- `backend/tests/api/test_exports.py`、`test_feedback.py`：B6 端点的 HTTP 契约测试（签名、过期、跨商家、公式注入、BOM）。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md`：B4 逐 Task 账本、复查和延后项。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/task-10-report.md`：B4 §验收清单逐条对照表、真实库端到端验收记录和文档改动说明。
