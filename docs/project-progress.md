# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。每次完成一段可验证工作后，更新日期、状态、验证结果、下一步和风险。

**最后更新：2026-08-05**

## 当前阶段

- 后端：**B4「安全经营数据查询」已收口**，分支为 `feature/b4-safe-analytics-query`。Task 1–9 均已实现并完成复查提交；Task 10（安全回归与端到端验收）已完成——§B4 验收清单逐条对应到测试并在真实 PostgreSQL 上跑过一次完整迁移 + Seed + 全量测试。**Task 10 的改动尚未提交**（等待用户授权 commit）。下一阶段为 B5「回答、图表和 Reviewer」。
- 前端：F0、F1、F2「Mock 会话闭环」已完成；下一阶段为 F3「API 契约与真实会话接入」。F3 开工前仍需补充设计说明与逐 Task 实施计划。
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
- 前端 F0–F2：Vue 3 + TypeScript + Vite 工程、三栏商家助手布局、SSE 解析、Mock 传输、会话状态机、取消/重试、演示商家切换、会话历史与轮次目录均已交付；F2 审查整改已包含降级状态展示、商家切换清理和并发提交保护。

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

## 下一步

1. 用户授权后提交 B4 Task 10（安全回归测试与文档）与此前尚未提交的 Task 1–9 改动。
2. 进入 **B5「回答、图表和 Reviewer」**：Answer Composition、回答 Prompt、Visualization Service、
   独立 Reviewer（`quality_status` 从当前的 `NOT_RUN` 接入 `PASSED`/`DEGRADED`/`FAILED`）、
   非加和指标保护接入回答层。B4 已确认的三处偏离（join 放大改按订单项聚合、完全未来区间拒绝、
   口径端点需返回已废弃指标）会影响 B5 复用同一批聚合表达式和口径端点时的实现方式，
   动手前先读 `docs/backend-development-plan.md` §B4「实现说明」。
3. 之后是 B6 反馈与 CSV 导出（`ExportSpec` 已由 Task 7 产出，落地导出端点在 B6），
   再到 B7 Railway、费用防护与 MVP 收口。
4. 前端 F3 在设计说明和实施计划完成后，接入真实 HTTP 传输、`Authorization` 头与统一错误处理；
   不重写已交付的 SSE、Adapter 和 Store 主路径。

## 风险与约束

- 未获用户明确同意，不得调用真实 DeepSeek API、收费 OCR 或日报生成；单元测试必须 mock LLM。真实模型调用前须先说明模型、调用次数和预期费用。
- 商家身份只可由 Bearer Token 解析；后端所有经营查询必须强制注入 `merchant_id`，不得信任前端传入的商家编号。
- B4 的代码改动（Task 1–10）尚未提交，等待用户授权；提交前需决定拆分粒度。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码、文案和资源必须使用 Borough。
- 后端 B4 的具体 Task 状态以 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md` 和 Git 提交记录为准；本文件只保留面向后续开发的摘要。

## 关键入口

- `AGENTS.md`：项目规则、目录与开发顺序。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/backend-development-plan.md`：后端阶段、API/SSE 契约与 B4–B9 顺序。
- `docs/frontend-development-plan.md`：前端 F0–F9 阶段计划。
- `backend/app/services/safe_query.py`：B4 受控查询应用服务。
- `backend/app/repositories/analytics.py`：B4 指标聚合与明细数据访问。
- `backend/app/agent/graph.py`：B4 真实查询接入问答图的落点。
- `backend/tests/integration/services/test_safe_query_security.py`：B4 §验收清单的安全回归测试（跨商家隔离、SQL 注入、180 天上限、statement timeout、拒绝原因不泄漏 SQL/表名）。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md`：B4 逐 Task 账本、复查和延后项。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/task-10-report.md`：B4 §验收清单逐条对照表、真实库端到端验收记录和文档改动说明。
