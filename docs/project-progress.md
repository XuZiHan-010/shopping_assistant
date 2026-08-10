# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。每次完成一段可验证工作后，更新日期、状态、验证结果、下一步和风险。

**最后更新：2026-08-09**

> **当前集成验收快照（2026-08-09，优先于下方历史阶段摘要）**：B7 + F4 集成工作已在
> `feature/integrate-b7-f4` 完成，尚未提交或推送。后端在专用 PostgreSQL（55442）上为
> **707 passed / 0 skipped / 1 个第三方弃用警告**；非数据库路径为 **591 passed / 116 skipped /
> 1 warning**。`ruff check`、`ruff format --check` 与获批的 `mypy app`（88 个源文件）均通过。
> 前端 lint、格式、OpenAPI/fixture/mock 边界、类型检查、构建均通过，Vitest 为
> **206 passed**，Mock Playwright 为 **24 passed**，专用 F4 真实 API Playwright 为 **3 passed**。
> 全程使用 Fake/确定性 LLM 覆盖，DeepSeek 调用 **0**、费用 **0**；仅使用
> `borough-int-postgres`（55442）与 `borough-int-f4-postgres`（55443），未操作共享 Compose
> 或 `borough_borough_postgres_data`。后续类型债务为 `tests/`/`scripts/` 的 103 项既有 Mypy
> 错误（32 个文件）；ECharts 仍有非阻塞的 556.46 kB chunk-size 提示。下一步为在用户授权下
> 决定集成/发布路径，以及用户在 Railway 控制台完成真实部署。

## 产品裁决：参考项目是需求基准（2026-08-09）

用户裁定本项目的目标是把 `yshopping-merchant-ai 4/` **1:1 还原**成 Python + TypeScript 版本；
当我们自己的 `docs/PRD.md` 或开发计划与参考项目实际实现冲突时，**改我们的文档去跟随参考项目**，
不得反过来用「PRD 没写」论证参考项目里存在的字段可以不做。规则已固化为 `AGENTS.md` R9。

首次适用是指标口径契约。差异审计结论：参考项目 `MetricDefinitionPayload` 有 13 个字段，
我们的 `MetricDefinitionResponse` 只兑现了 7 个。缺失项与处置：

| 参考项目字段 | 我们的状态 | 处置 |
| --- | --- | --- |
| `sqlMeaning`（SQL 口径） | 库里 `metric_definitions.sql_definition` 有真实值，但未出口到 API | 补字段 |
| `dimensions`（维度集合） | 完全没有 | 补字段（P1） |
| `reportUrl`（关联报表） | 完全没有，且前端计划曾写「不在契约内就删掉 UI」 | 补字段（P1），前端计划那句已删 |
| `databaseName` / `tableName`（来源库表） | 完全没有 | 补字段 |
| `generated`（是否模型生成） | 无，前端用 `status === 'UNVERIFIED'` 反推 | 补独立布尔字段 |
| `notice`（待核验文案） | 无，文案写死在前端 | 改为后端返回 |
| `source` 语义 | 我们是自由文本（"Borough 指标目录"），参考项目是枚举 | 改为 `METRIC_CATALOG` / `COLUMN_COMMENT` / `AI_GENERATED` |
| 三级降级检索 | `app/metrics/catalog.py` 只有两级，缺「字段注释」中间级 | 补第二级 |

我们比参考项目多出的 `metric_code`（稳定英文标识）与 `metric_status` 予以保留——参考项目没有稳定
指标标识是它的缺陷，不是需要还原的行为。

已同步修订：`AGENTS.md`（新增 R9）、`docs/PRD.md`（§6.3 补 3 条用户故事并说明双口径不可合并、
§10 Metric Catalog 补三级检索来源表、§11.3 按模式必填表拆分业务口径/SQL 口径、§12.1 演示数据要求；
新增故事导致原 19–67 号顺延为 22–70）、`docs/frontend-development-plan.md`（§5.6 接口定义与 F4
验收项按参考项目重写，删除「不展示报表」条款）、`docs/backend-development-plan.md`（§8.2 字段表、
必测项、B4 口径端点登记未完成项）。

**代码实现尚未开始。** 落点应为 `feature/b4-safe-analytics-query`（`/api/metrics/{code}` 与
`metric_definitions` 表都在该分支），改动链路：迁移加列 → Seed 补值 → `MetricDefinitionResponse` /
`MetricPayload` / `ChatResponse` 加字段并把 `metric_definition` 改名为 `metric_business_definition`
→ 重跑 `codegen` 与 `fixtures` → 前端 `MetricDefinitionPanel.vue` 按参考项目版式还原。
注意 F4 已在 `feature/f3-real-api-integration` 上完成并提交，该前端改动会与其产生冲突，
需要先确定两个分支的合并顺序。

## 当前阶段

- 后端：**B4「安全经营数据查询」已收口并完成终审修复轮**，分支为 `feature/b4-safe-analytics-query`。Task 1–10 均已实现、复查并提交（Task 10 在 `72b2190`，REFUND 明细路由修复在 `7d28552`）。终审修复轮已提交（`b174bd9` 修掉 1 Critical + 6 Important，`50a28e6` 清理指向本阶段的过期文案并加机械防线）。
- 后端：**B5「回答、图表和 Reviewer」、B6「反馈与 CSV 导出」代码已完成并提交**，分支 `feature/b5-b6-answer-feedback-export`（提交 `7c60b12`/`18ba978`/`b494277`/`acc7efa`，2026-08-06）。之前这批工作只存在于本地 worktree 且未提交；本轮先修完 `ruff check`/`ruff format` 未通过的 10 处问题（都在下面提到的 B7 附带代码里），再按 Task 边界拆成 4 个提交落地。分支去向（合并/开 PR/保留）尚未决定。
- 后端：**B7「Railway、费用防护与 MVP 收口」代码层面已完成并提交**，分支 `feature/b5-b6-answer-feedback-export`（提交 `1efb79c`…`310fc42`，2026-08-06）。费用守卫、限流、可信 IP 补齐了必测；Docker 优雅关闭、`OperationalMetrics` 可观测性、`GET /api/admin/ops/status` 运维端点、`railway.json`、`docs/deployment.md` 均已实现。`REQUIRE_INTEGRATION_DB=1 pytest` 在真实 PostgreSQL 上跑通 **703 passed、0 skipped、0 failed**（首次跑通时发现一个真实 bug 并已修复，见「最近验证」）；`ruff`/`ruff format`/`mypy`（88 源文件）全绿。**未完成的只剩需要人工在 Railway 控制台操作的部分**：实际创建 Railway 项目、连接 PostgreSQL、填写环境变量、执行部署，以及依赖真实部署环境的验收项（见 `docs/backend-development-plan.md` §B7「验收（MVP 出口）」）。
- 前端：F0、F1、F2「Mock 会话闭环」已完成；下一阶段为 F3「API 契约与真实会话接入」。F3 开工前仍需补充设计说明与逐 Task 实施计划。前端目前仍对接 Mock，尚未消费 B5/B6 的新接口。
- F1 遗留：1440×1000 人工视觉比对待本地 Windows Computer Use helper 可用后补做；不影响已通过的结构、几何和无障碍自动化验收。
- **仓库结构提示（本轮确认）**：本机同时存在多个 worktree——主目录当前签出 `feature/b4-safe-analytics-query`；`.worktrees/feature-b5-b6-answer-feedback-export/` 签出 `feature/b5-b6-answer-feedback-export`（已推到 `origin`）。`plans/2026-08-05-backend-b5-b6.md`、`docs/specs/2026-08-05-backend-b5-b6-design.md` 是当初驱动 B5/B6/B7 实施的计划与设计文档，留在主目录未提交；它们描述的工作已经在另一个 worktree 里全部完成并提交，不要误读成「B5/B6 尚未开工」。

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
- 后端 B6（`18ba978`/`b494277`/`acc7efa`）：`POST /api/answers/{id}/feedback`（商家范围内幂等采纳/点赞点踩，跨商家 403 + 审计）、`GET /api/exports/{id}`（HMAC 签名 URL、15 分钟过期、下载时重新执行受控明细查询、UTF-8 BOM、公式注入防护、`Referrer-Policy: no-referrer`）、`export_files` 迁移与 `ChatService` 导出接线（只在 DETAIL 成功且未降级时创建导出记录）均已实现。此前一轮复审已修过 5 处问题（导出 CSV 双重 BOM、本地校验缺两条方案要求的检查、导出记录未排除降级回答、签名密钥兜底值重复、feedback/exports 路由完全没有 HTTP 层测试），新增 24 条测试后全量后端测试从 628 涨到 652 passed；随后 B7 Task 1-18 又新增测试，2026-08-06 用真实 PostgreSQL 复核全分支得到 703 passed、0 failed，见「最近验证」。
- 后端 B7（`1efb79c`…`310fc42`，2026-08-06）：`LlmCostGuard`/`SlidingWindowRateLimiter`/`resolve_client_ip` 补齐单元测试，新增伪造 `X-Forwarded-For` 的端到端信任边界测试和 `LlmBudgetRepository` 并发原子扣减的真实库回归；`app/run.py` 显式声明 30 秒优雅关闭窗口并记录「保持单 worker」的架构决策；新增 `OperationalMetrics`（进程内运维指标：路由/Agent 节点耗时、错误码分布、限流命中、降级计数）并接入请求中间件、异常处理器、`ChatService`、`MerchantQaGraph`；新增 `require_admin_token` 依赖（只认 `X-Admin-Token`）与 `GET /api/admin/ops/status`（未配置 `ADMIN_TOKEN` 时整体不挂载路由）；新增 `railway.json` 与 `docs/deployment.md`；`CURRENT_STAGE` 推进到 `"B7"`。**实际 Railway 部署未执行**——按计划约束本轮只产出配置产物，创建项目/连接数据库/填写环境变量/验证部署留给用户。

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
- **B7 收口 + 真实 PostgreSQL 首次复核（2026-08-06）**：`docker-compose -p borough up -d postgres` 起库后
  跑 `REQUIRE_INTEGRATION_DB=1 pytest`，**首次运行 701 passed、2 failed**——`tests/api/test_feedback.py`
  里排在后段的两个用例稳定收到 `503 LLM_BUDGET_EXCEEDED`。根因：`tests/postgres.py::TRUNCATE_ALL_TABLES`
  没有包含 `llm_daily_budget`；该表按 `usage_date` 记账，一整轮 pytest 在同一天内跑数百个真实请求，
  所有集成测试共用同一行预算，跑到后段就把默认 `llm_daily_budget_tokens=20_000` 耗尽，是真实的测试隔离
  缺陷而非误报——不跑真实库、只跑 Fake LLM 或单元测试都发现不了。补上 `llm_daily_budget` 后
  （提交 `64e60e3`）重新跑通：**703 passed、0 skipped、0 failed**（较 2026-08-05 收口时的 652 新增
  51 条，含 B7 全部必测）。`ruff check`、`ruff format --check`、`mypy`（88 个源文件）全绿。

## 下一步

1. **实际执行 Railway 部署**：`railway.json` 与 `docs/deployment.md` 已就绪，但创建 Railway 项目、
   连接 PostgreSQL Service、填写 `docs/deployment.md`「必填环境变量」表里的真实值（`ADMIN_TOKEN`、
   `EXPORT_SIGNING_SECRET`、`LLM_API_KEY` 等）、触发首次部署，都需要用户在 Railway 控制台手动操作——
   不是本地能完成的工作。部署后按 `docs/backend-development-plan.md` §B7「验收（MVP 出口）」逐条验收
   （重启后数据仍在、健康检查、SIGTERM 优雅关闭、伪造转发头无法绕过限流、演示商家端点生产下不可访问等）。
2. **决定分支去向**：仓库当前有四个相关分支/worktree——`main`、`feature/f2-mock-conversation`（前端
   F0–F2）、`feature/b4-safe-analytics-query`（B4，已通过终审）、`feature/b5-b6-answer-feedback-export`
   （已含 B5/B6/B7，真实库回归 703 passed，是四者中最新最完整的一支）。是否合并、开 PR 还是保留，
   尚未决定；合并前建议先确认 `feature/b5-b6-answer-feedback-export` 是否基于 `feature/b4-safe-analytics-query`
   的最新提交（`c8efd1d`）而非更早的祖先，避免合并时丢掉终审修复轮的内容。
3. **前端 F3「API 契约与真实会话接入」**：依赖的后端契约（B0–B7）均已就绪，不必等 Railway 部署完成
   才开工；开工前先补设计说明与逐 Task 实施计划，接入真实 HTTP 传输、`Authorization` 头与统一错误
   处理，不重写已交付的 SSE、Adapter 和 Store 主路径。
4. **可观测性的已知小缺口**：SQL 查询本身的独立耗时尚未单独记录（目前只随 Agent 节点整体耗时被
   间接计入），不阻塞 MVP 出口，但补查询耗时对定位慢查询有帮助，可在 B7 部署验收后顺手补上。

## 风险与约束

- 未获用户明确同意，不得调用真实 DeepSeek API、收费 OCR 或日报生成；单元测试必须 mock LLM。真实模型调用前须先说明模型、调用次数和预期费用。
- 商家身份只可由 Bearer Token 解析；后端所有经营查询必须强制注入 `merchant_id`，不得信任前端传入的商家编号。
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 常量在 `feature/b5-b6-answer-feedback-export`
  分支上已推进到 `"B7"`；`feature/b4-safe-analytics-query` 分支上仍是 `"B4"`。**分支合并时要以更晚阶段的值为准**，
  否则该防线会继续只挡旧阶段字样而放过新的过期文案。
- **Docker Desktop 在本机环境偶发无法启动**：曾出现引擎持续返回 `500 Internal Server Error`（不是
  常见的「还在启动」connection-refused 现象），完全重启 Docker Desktop 进程后仍未恢复，等了将近
  20 分钟后才自行恢复正常。如果下次又遇到真实 PostgreSQL 集成测试连不上库，先确认这不是环境本身的
  瞬时故障，必要时重启 Docker Desktop 并耐心等待，而不是假设代码或配置有问题。
- **`GET /api/admin/ops/status` 是新增的敏感面**：只认 `X-Admin-Token`（`hmac.compare_digest` 比较），
  `Authorization` 头一律忽略；`ADMIN_TOKEN` 未配置时端点整体不挂载路由（404，而非 401/403），避免
  「路由存在但认证总是失败」暴露端点存在性。修改这块代码时留意 `tests/api/test_admin_ops.py` 的
  401/403/404/200 四态断言仍然成立。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码、文案和资源必须使用 Borough。
- 后端 B4 的具体 Task 状态以 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md` 和 Git 提交记录为准；该目录被 `.gitignore` 忽略，只存在于产出它的那个工作副本里，不会随分支/worktree 一起出现。B5/B6/B7 本轮没有对应的 SDD 账本，本文件是这段工作的权威摘要。
- 本机存在多个 git worktree（见「当前阶段」末尾一条），核对进度前先用 `git worktree list` 和
  `git log <branch> --oneline` 确认自己看的是哪个分支的状态，不要只看主目录当前签出分支的文件是否存在
  就下结论。

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
- `backend/app/llm/guard.py`、`app/core/rate_limit.py`、`app/core/client_ip.py`、`app/repositories/llm_budget.py`：B7 费用防护/限流/可信代理 IP 基础设施，必测已补齐（`tests/unit/llm/test_guard.py`、`tests/unit/core/test_rate_limit.py`、`tests/unit/core/test_client_ip.py`、`tests/integration/repositories/test_llm_budget_repository.py`、`tests/api/test_rate_limit_trust_boundary.py`）。
- `backend/app/core/metrics.py`、`app/api/routes/admin.py`：B7 运维可观测性（`OperationalMetrics`）与 `GET /api/admin/ops/status` 运维端点。
- `backend/railway.json`、`docs/deployment.md`：B7 Railway 配置即代码与部署运维手册；实际部署仍需用户在 Railway 控制台执行。
- `backend/tests/integration/services/test_safe_query_security.py`：B4 §验收清单的安全回归测试（跨商家隔离、SQL 注入、180 天上限、statement timeout、拒绝原因不泄漏 SQL/表名）。
- `backend/tests/api/test_exports.py`、`test_feedback.py`：B6 端点的 HTTP 契约测试（签名、过期、跨商家、公式注入、BOM）。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md`：B4 逐 Task 账本、复查和延后项。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/task-10-report.md`：B4 §验收清单逐条对照表、真实库端到端验收记录和文档改动说明。
