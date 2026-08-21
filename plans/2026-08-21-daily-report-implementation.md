# 每日经营日报实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:executing-plans` 逐项实施。步骤使用 `- [ ]` 勾选框跟踪。

**目标：** 交付商家身份隔离的 `GET /api/reports/daily` 与首页日报卡片；报告固定为业务时区昨日、可采纳、同日幂等且对查询失败可见降级。

**架构：** `DailyReportService` 通过受控 PostgreSQL 聚合构建六项固定顺序指标及两条确定性建议，并以 `daily-report:{report_date}` 复用既有商家级 Answer 幂等约束。为维持 Answer 必属会话的不变量，增加每商家唯一的 `DAILY_REPORT` 系统会话；普通会话列表只返回 `CHAT`。前端通过 generated type 与专用 adapter 将日报响应映射到领域模型，卡片复用既有反馈 API。

**技术栈：** Python 3.12、FastAPI、SQLAlchemy Async、Alembic、PostgreSQL、Vue 3、TypeScript、Pinia、Vitest、pytest。

> **实施状态（2026-08-21）：** 已完成 Task 1–5。`GET /api/reports/daily`、固定六项指标、两分支建议、商家级日报系统会话、并发幂等回读、可见降级、前端卡片与 answer-level 采纳反馈均已落地；OpenAPI 与生成类型已同步。本地最终验证：后端 `930 passed, 1 warning`，前端 Vitest `271 passed`；未调用真实 LLM。

## 全局约束

- 所有页面文案、错误消息、日志说明和项目文档使用中文；代码标识符保持英文。
- 商家只从已验证的 Bearer Token 得到，日报端点不接受 `merchant_id` 或 `report_date` 查询参数。
- 所有 SQL 从受控 ORM/注册表生成；不得引入模型生成或执行 SQL。
- 不调用真实 DeepSeek；测试只使用确定性数据、Fake/Mock，零 token 费用。
- 失败时返回 `degraded=true`、原因和空 `metrics`，不得以一组零指标伪装查询成功。
- 固定使用 `Asia/Shanghai` 的昨日；金额字段保持 `Decimal`，不引入浮点金额。
- 本轮明确排除 Railway Cron、推送、Celery、Redis、对象存储和附件功能。
- 未经用户明确许可不得执行 Git 提交、推送、标签或 PR 操作。
- 不修改 `yshopping-merchant-ai 4/`；不改动本轮既有三份计划或日报契约设计说明。

---

### Task 1：受控日报指标与近七日建议数据

**文件：**
- 修改：`backend/app/analytics/contract.py`、`backend/app/repositories/analytics.py`
- 新建：`backend/tests/integration/repositories/test_daily_report_analytics.py`

**接口：**
- 输入：`merchant_id: UUID`、`report_date: date`。
- 输出：`AnalyticsRepository.daily_report_metrics(...) -> tuple[DailyMetricValue, ...]` 和 `recent_daily_report_signals(...) -> DailyReportSignals`；六项严格顺序为 `gmv`、`ordering_user_count`、`order_count`、`successful_order_count`、`return_count`、`refund_amount`。

- [x] **步骤 1：先写集成测试。** 为两个商家插入同日及近七日订单、退款、退货和工单；断言 `ordering_user_count` 统计未付款订单的去重买家、金额是 `Decimal`、无跨商家行，并覆盖报表日和近七日边界。
- [x] **步骤 2：运行新测试并确认失败。**
  ```powershell
  cd backend
  $env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/repositories/test_daily_report_analytics.py -v
  ```
  预期：因日报聚合接口尚不存在而失败。
- [x] **步骤 3：最小实现白名单指标和聚合。** 在 `METRIC_SPECS` 加 `ordering_user_count`，使用 `count(distinct Order.buyer_key)` 且不加付款过滤；在 repository 以固定列对象和绑定日期生成单查询/固定聚合，绝不接收表名或列名字符串。
- [x] **步骤 4：复跑测试并确认通过。**

### Task 2：日报系统会话、迁移和持久化原语

**文件：**
- 修改：`backend/app/models/conversation.py`、`backend/app/repositories/conversation.py`、`backend/app/api/routes/chat.py`
- 新建：`backend/migrations/versions/20260821_0012_daily_report_conversations.py`、`backend/tests/integration/repositories/test_daily_report_conversation.py`

**接口：**
- 输入：`ConversationRepository.get_or_create_daily_report_conversation(merchant_id)`。
- 输出：一条 `conversation_kind="DAILY_REPORT"` 的 `Conversation`；同一商家最多一条，普通列表只返回 `conversation_kind="CHAT"`。

- [x] **步骤 1：先写迁移后集成测试。** 断言首次和重复调用返回同一系统会话；两个商家各有一条；直接尝试插入第二条日报会话命中 PostgreSQL 条件唯一索引；普通会话列表和聊天详情保持既有行为且不露出日报会话。
- [x] **步骤 2：运行测试并确认失败。**
- [x] **步骤 3：最小实现模型、条件唯一索引和 repository。** 使用 `conversation_kind` 非空列、默认 `CHAT`，以 PostgreSQL `postgresql_where` 建 `DAILY_REPORT` 的条件唯一索引；`get_or_create` 在完整性冲突后重读，不依赖标题识别。
- [x] **步骤 4：将普通列表查询显式限制为 `CHAT` 并复跑测试。**

### Task 3：日报服务、API 契约和端点

**文件：**
- 新建：`backend/app/schemas/report.py`、`backend/app/services/report_service.py`、`backend/app/api/routes/reports.py`、`backend/tests/unit/services/test_report_service.py`、`backend/tests/api/test_reports.py`
- 修改：`backend/app/api/dependencies.py`、`backend/app/api/router.py`

**接口：**
- 输出：`DailyReportResponse(answer_id, report_date, metrics, suggestions, degraded, degraded_reason)`；`metrics` 每项为 `{metric_code, display_name, unit, value}`，`suggestions` 恒为两个中文字符串。
- 端点：`GET /api/reports/daily`，仅商家身份认证；无查询参数。

- [x] **步骤 1：写 service 单元测试。** 用可控时钟和 repository 替身覆盖：业务时区跨零点取昨日、退款金额大于零/等于零、工单占比大于 20%/兜底、无近七日数据的两条固定建议、查询异常的可见降级。
- [x] **步骤 2：运行单元测试并确认失败。**
- [x] **步骤 3：实现 `DailyReportService.get_or_create_daily_report()`。** 先取得日报系统会话，再按 `daily-report:{report_date}` 查既有 Answer；不存在时生成固定 payload 并保存 `SUCCEEDED` Answer，冲突后重读获胜行。成功报告不可变；查询错误也以一条可见降级报告物化，避免重试时伪装不同结果。
- [x] **步骤 4：写 API 集成测试。** 覆盖 401、忽略伪造 `merchant_id`、没有 query 参数、跨商家结果隔离、同日重复请求同一 `answer_id`/payload、反馈端点可对其写入采用状态。
- [x] **步骤 5：实现依赖装配与路由并复跑单元/API 测试。** 路由只解析身份和调用 service；不得调用 LLM。

### Task 4：前端领域模型、日报卡片和反馈交互

**文件：**
- 新建：`frontend/src/api/adapters/report.ts`、`frontend/src/api/report.ts`、`frontend/src/components/chat/DailyReportCard.vue`、对应 `*.spec.ts`
- 修改：`frontend/src/types/chat.ts`、`frontend/src/stores/chat.ts`、`frontend/src/views/AssistantView.vue`、`frontend/src/api/mock/transport.ts`

**接口：**
- `getDailyReport(signal) -> DailyReport` 只消费 `generated.ts`，由 `toDailyReport` 转为 camelCase 领域模型。
- `DailyReportCard` 显示日期、六项指标、两条建议和唯一的“采纳本期建议”动作；反馈写 `POST /api/answers/{id}/feedback`。

- [x] **步骤 1：先写 adapter 与组件失败测试。** 断言 snake_case 到 camelCase 转换、`Decimal` JSON 数字原样显示、`degraded` 原因可见、没有报告/加载失败不伪造 mock 数据、点击采用只提交 answer-level `is_adopted=true`。
- [x] **步骤 2：运行 Vitest 并确认失败。**
  ```powershell
  cd frontend
  npm run test -- --run src/api/adapters/report.spec.ts src/components/chat/DailyReportCard.spec.ts
  ```
- [x] **步骤 3：实现 API、adapter、store 状态和卡片。** 商家恢复完成后加载日报；商家切换时取消旧请求并清除旧日报，防止跨商家显示。卡片不嵌套在装饰卡内，使用现有图标、控件和响应式布局。
- [x] **步骤 4：实现 mock transport 同一契约的响应，复跑组件/Store 测试。**

### Task 5：契约导出、文档同步和全量验证

**文件：**
- 修改：`docs/PRD.md`、`docs/backend-development-plan.md`、`docs/frontend-development-plan.md`、`docs/yshopping-parity-audit.md`、`docs/project-progress.md`、`AGENTS.md`
- 生成：`docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts`
- 修改：`backend/tests/api/test_openapi_chat_contract.py`

- [x] **步骤 1：补 OpenAPI 契约测试。** 断言 `/api/reports/daily` 仅有 GET、没有 `merchant_id`/`report_date` query parameter，并列出 401/422/500 的统一错误响应与新 schema。
- [x] **步骤 2：同步文档。** 将 Q1–Q8 的用户裁定、路径偏离、数组响应、无审核拒绝数据源和排除 Cron 登记到权威文档；只更新本新计划的执行状态，既有三份计划和设计说明保持原样。
- [x] **步骤 3：导出 OpenAPI 并更新前端类型。**
  ```powershell
  cd backend
  uv run python ../scripts/export_openapi.py
  cd ../frontend
  npm run codegen
  npm run codegen:check
  ```
- [x] **步骤 4：执行后端全量门禁。**
  ```powershell
  cd backend
  $env:REQUIRE_INTEGRATION_DB=1; uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy app
  ```
- [x] **步骤 5：执行前端验证。**
  ```powershell
  cd frontend
  npm run test
  npm run typecheck
  npm run lint
  npm run format:check
  npm run build
  npm run secrets:check
  ```
- [x] **步骤 6：检查无意外改动。** 确认三份既有计划、日报契约、受保护的移交文件和 `scripts/export_chat_fixtures.py` 未被本任务改写；不执行 Git 提交。

## 计划自检

- Q1–Q8 各有对应任务：指标、两分叉建议、数组 schema、系统会话、无 Cron、固定日期、幂等和 answer-level 反馈均已覆盖。
- 安全、商家隔离、R7 降级、固定业务时区与 Decimal 均由可执行测试覆盖。
- 未包含附件、OCR、对象存储、定时推送或真实模型调用。
