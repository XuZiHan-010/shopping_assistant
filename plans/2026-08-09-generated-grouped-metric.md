# 受控临时分组指标实施计划

> **状态：** 已完成（2026-08-13；待 Task 13 的全链路 E2E 与 Task 14 的最终一致性验收统一收口）
> **日期：** 2026-08-12
> **关联路线图：** `plans/2026-08-12-post-f6-execution-roadmap.md` Task 12

## 目标与安全边界

还原参考项目的临时分组指标：LLM 可描述展示名称、单位、按 `spu_id` 或 `address_city_name` 分组，以及成对出现的固定筛选；后端按问题类别选择交易或退款的固定 SQLAlchemy 聚合模板。LLM 不得输出 SQL、公式、表名、列名或 `measure` 枚举。

- `GeneratedMetricPlan` 只允许 `group_by` / `filter_column` 为 `spu_id`、`address_city_name`；`filter_column` 与 `filter_value` 必须同时存在。
- 无分组时仅允许合法的城市筛选；其他形状、未知列和注入尝试必须将整条意图变为 `INVALID`，类别变为 `UNKNOWN`，并给出固定说明。该语义故意不同于 Task 11 跨业务计划的降级回退。
- 聚合模板、结果列、图表字段、截断阈值和导出重放全部由后端固定；每个数据库访问显式注入已验证的 `merchant_id`，所有值使用绑定参数。

## 实施步骤

### 1. 实现意图类型、严格 INVALID 语义与提示词（先写单元测试）

**文件：**

- 修改 `backend/app/intent/models.py`
- 修改 `backend/app/intent/prompts.py`
- 修改 `backend/app/intent/whitelist.py`
- 修改 `backend/tests/unit/intent/test_whitelist.py`
- 修改 `backend/tests/unit/intent/test_service.py`

**工作：**

1. 增加 `GeneratedMetricPlan`：`name`、`unit`、可选 `group_by`、成对的 `filter_column` / `filter_value`；只允许两列白名单。
2. 在 `QueryIntent` 加入可空 `generated_metric_plan`。嵌套计划形状非法、未知列、空/超长筛选值或不允许的无分组形态，均转为 `AnswerMode.INVALID` 与 `QuestionCategory.UNKNOWN`；不得把错误的计划静默清除后继续执行普通查询。
3. 补充理解提示词，明确类别选择模板、禁止自由指标公式与 SQL。
4. 测试 SPU 分组、城市分组、仅城市筛选、成对字段约束、非法列、SQL 注入式值和整体 INVALID 不变量。

### 2. 为交易和退款类别增加固定聚合仓储与安全查询路由（先写 PostgreSQL 集成测试）

**文件：**

- 修改 `backend/app/repositories/analytics.py`
- 修改 `backend/app/services/safe_query.py`
- 修改 `backend/app/services/visualization_service.py`（如图表白名单需扩展）
- 修改 `backend/tests/integration/repositories/test_analytics_aggregate.py`
- 修改 `backend/tests/integration/services/test_safe_query.py`
- 修改 `backend/tests/unit/services/test_safe_query_guards.py`

**工作：**

1. 定义不接受自由列名的交易与退款聚合模板；在两张类别对应的既有数据表中固定选择聚合值和白名单维度。
2. `SafeQueryService` 仅在 `METRIC` 意图携带有效计划时走该分支；普通注册指标路径保持不变。
3. 结果列、排序、截断和图表候选字段都从固定模板产出；不得由 `name`、`unit` 或 LLM 字符串决定 SQL 标识符。
4. 测试两个分组维度、仅城市筛选、多商家隔离、无效意图不抵达仓储，以及安全图表只引用结果列。

### 3. 让截断结果以同一受控计划导出

**文件：**

- 修改 `backend/app/services/safe_query.py`
- 修改 `backend/app/services/export_service.py`
- 修改 `backend/app/repositories/analytics.py`
- 修改 `backend/tests/unit/services/test_export_service.py`
- 修改 `backend/tests/integration/services/test_export_service.py`

**工作：**

1. 将受控生成指标计划序列化进 `ExportSpec`，并在签名下载时用固定模板重放完整结果。
2. 验证计划种类、固定列集合和商家范围；被篡改的计划、列或导出规格一律拒绝。
3. 测试预览截断时出现导出、CSV 列顺序稳定、导出与预览同源、公式注入转义及跨商家隔离。

### 4. 接入回答、图表、契约与文档

**文件：**

- 修改 `backend/app/agent/graph.py` 及对应单测（如生成指标字段映射需要补充）
- 修改 `docs/PRD.md`
- 修改 `docs/backend-development-plan.md`
- 修改 `docs/yshopping-parity-audit.md`
- 修改 `plans/2026-08-12-post-f6-execution-roadmap.md`
- 必要时重新生成 `docs/api.json`、`docs/api.md` 和前端 `generated.ts` / fixture

**工作：**

1. 让回答、图表和质量轨迹消费固定结果；所有无效计划以正常 `200` 的 `INVALID` 回答呈现，不写入可执行查询载荷。
2. 将 PRD、后端计划、审计清单和路线图同步为实现后的严格 INVALID、类别驱动模板与导出语义。
3. 仅在外部 ChatResponse 契约变化时运行 OpenAPI / 前端代码生成，并以 adapter fixture 验证。

## 验证命令

```powershell
cd backend
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run mypy app
$env:REQUIRE_INTEGRATION_DB='1'; $env:TEST_DATABASE_URL='postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_stage0_20260812_test'; uv run pytest -q
```

若外部 API 或前端展示发生变化，再执行：

```powershell
cd frontend
npm.cmd run codegen:check
npm.cmd run fixtures:check
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run format:check
npm.cmd run test
npm.cmd run build
npm.cmd run firstpaint:check
npm.cmd run secrets:check
npm.cmd run mock:check
```

验证仅使用 Fake LLM、静态 fixture 与本地 Docker PostgreSQL，不会调用 DeepSeek 或产生 token 费用。
