# 跨业务关联查询还原实施计划

> **状态：** 进行中  
> **日期：** 2026-08-12  
> **关联路线图：** `plans/2026-08-12-post-f6-execution-roadmap.md` Task 11

## 目标

还原参考项目的受控跨业务关联查询：商家可通过订单号查看关联退款、商品，或同时查看订单、退款与商品。模型只能给出经过 Pydantic 校验的固定关联计划；后端始终先在已验证的 `merchant_id` 范围内解析订单，再执行固定关系查询。不得让模型输出或执行 SQL、表名、列名或自由关联条件。

本任务同时落实路线图规定的失败语义：缺少计划时走既有普通查询；计划结构非法或订单不属于当前商家时，清除关联计划、保留有效基础意图、附加用户可见说明，并实际执行普通的商家范围查询。订单不存在与跨商家订单不作可区分的响应，避免形成跨商家存在性探测通道。

## 设计边界

- 新增的受控类型仅允许：`ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS`。
- 关联键字段名为 `sub_order_no`，在 Borough 的演示模型中只映射到当前商家范围内的 `orders.order_no`；它不是模型可选的数据库字段。
- `sub_order_no` 必须是受长度与字符集约束的订单号，且不可为空。
- 嵌套计划的 Pydantic 校验错误不能使整个 `QueryIntent` 变为 `INVALID`。`QueryIntent` 的前置校验器应清除计划并记录内部拒绝标记；意图白名单服务把该标记转换为固定的语义说明。
- 结构有效但无法在当前商家范围解析订单的计划，由安全查询层降级为普通详情查询，并返回不暴露订单归属的固定说明。
- 所有查询、导出重放和结果列均由后端固定模板决定，且每次数据库访问显式带 `merchant_id`。
- 跨业务结果保持现有 `DETAIL` 响应形态；`analysis_requested=false` 时复用 Task 10 的纯表格响应，不调用回答或 Reviewer LLM。

## 实施步骤

### 1. 为关联计划建立可恢复的意图契约（先写单元测试）

**文件：**

- 修改 `backend/app/intent/models.py`
- 修改 `backend/app/intent/prompts.py`
- 修改 `backend/app/intent/whitelist.py`
- 修改 `backend/app/intent/service.py`（如测试揭示语义说明未被保留）
- 修改 `backend/tests/unit/intent/test_models.py`
- 修改 `backend/tests/unit/intent/test_whitelist.py`
- 修改 `backend/tests/unit/intent/test_service.py`

**实现：**

1. 增加 `CrossBusinessPlanType` 枚举和 `CrossBusinessPlan`，将 `plan_type` 限制为三个固定值，将 `sub_order_no` 限制为非空、最长 64 个字符且仅允许订单号安全字符。
2. 在 `QueryIntent` 增加 `cross_business_plan: CrossBusinessPlan | None`，并用 `model_validator(mode="before")` 单独尝试解析原始计划；无效嵌套对象改为 `None`，不抛出顶层 `ValidationError`。
3. 拒绝标记只由前置校验器写入，忽略 LLM 自行提交的同名内部字段；白名单服务识别该标记，返回固定中文语义说明和不带关联计划的有效意图。
4. 在理解提示词中声明关联计划是可选的固定 JSON 对象，禁止输出 SQL、表名、列名、join 条件或其他查询标识符。
5. 覆盖有效三种计划、未知计划类型、遗漏订单号、空订单号、过长订单号、非法字符、无计划和服务层语义说明传播。

**验收：**

- 每一个非法计划测试均断言结果意图不是 `AnswerMode.INVALID`，且 `cross_business_plan is None`。
- 未提供计划时没有“计划已拒绝”说明。
- 提示词与模型的 JSON Schema 都只暴露受控计划字段。

### 2. 增加商家范围内的固定关联仓储查询（先写集成测试）

**文件：**

- 修改 `backend/app/repositories/analytics.py`
- 修改 `backend/app/services/safe_query.py`
- 修改 `backend/tests/integration/services/test_safe_query.py`
- 修改 `backend/tests/unit/services/test_safe_query.py`（按现有测试组织补充）

**实现：**

1. 在 `AnalyticsRepository` 增加固定的订单解析和关联结果读取方法；解析条件固定为 `Order.merchant_id == merchant_id` 与 `Order.order_no == sub_order_no`。
2. 关联退款时，固定从已解析订单的 `order_items` 关联 `refunds`；关联商品时，固定从已解析订单的 `order_items` 关联 `products`。每个后续查询也包含 `merchant_id` 条件。
3. 在 `SafeQueryService.execute` 中优先识别有效的 `cross_business_plan`，只允许其以 `DETAIL` 语义执行，构造固定的列、来源表、计划步骤和截断信息。
4. 若关联订单无法在当前商家范围内解析，清除本次执行的关联计划，使用原意图执行普通详情查询，并增加“关联订单不存在或不在当前商家范围，已按普通明细查询”的固定说明；不得查询其他商家的订单来区分原因。
5. 为三种固定计划分别测试返回列与关联数据；同时测试跨商家订单号、未知订单号和非法计划降级后均实际调用普通详情查询，且不会返回其他商家记录。

**验收：**

- 所有执行路径使用绑定参数和 ORM 固定表达式，没有来自 LLM 的标识符参与 SQL 组合。
- 跨商家/不存在订单不会泄漏关联订单、退款、商品或存在性差异。
- `analysis_requested=false` 的关联结果可作为纯详情表格返回。

### 3. 让导出按同一安全计划重放

**文件：**

- 修改 `backend/app/services/export_service.py`
- 修改 `backend/app/repositories/export.py`（如现有导出仓储需要新受控分支）
- 修改 `backend/app/schemas/export.py`（如 `ExportSpec` 需要受控关联计划载荷）
- 修改 `backend/tests/unit/services/test_export_service.py`
- 修改 `backend/tests/integration/api/test_exports.py`

**实现：**

1. 扩展导出规格，使其可表达受控的跨业务计划、订单号和固定导出种类；不得将这些值编码为可执行 SQL 或可选表/列名。
2. 导出服务从保存的规格重放与聊天完全相同的商家范围关联查询，保持请求商家与规格商家一致校验。
3. 测试三个计划的 CSV 表头与数据、导出重放的商家隔离，以及被篡改或不支持规格的拒绝行为。

**验收：**

- 聊天展示与 CSV 导出的关联结果列一致。
- 不能通过历史导出规格绕过 `merchant_id` 限制或访问自由表名。

### 4. 接入 Agent、更新契约文档并完成端到端验证

**文件：**

- 修改 `backend/app/agent/graph.py`（如质量说明或表格响应映射需补充）
- 修改 `backend/tests/unit/agent/test_graph_query_data.py`
- 修改 `docs/PRD.md`
- 修改 `docs/backend-development-plan.md`
- 修改 `docs/yshopping-parity-audit.md`
- 修改 `plans/2026-08-12-post-f6-execution-roadmap.md`
- 生成 `docs/api.json`、`docs/api.md`
- 如 OpenAPI 变化，生成 `frontend/src/api/generated.ts` 并更新相关 fixture

**实现：**

1. 确认 Agent 将意图拒绝说明和安全查询降级说明传递到现有 `quality_notes`，并且纯详情路径不触发回答或 Reviewer LLM。
2. 将 PRD、后端计划和还原度审计更新为实际实现的受控计划、降级语义和商家隔离保证；完成路线图 Task 11 勾选。
3. 重新导出 OpenAPI，只有在外部 API 契约确实变化时才更新前端生成类型与 fixture。

**验收：**

- 非法计划的 API 响应仍为正常详情结果，带可见说明而非 `INVALID`。
- 正常计划、纯表格计划、跨商家降级计划均有端到端或 API 覆盖。

## 验证命令

后端：

```powershell
cd backend
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run mypy app
$env:REQUIRE_INTEGRATION_DB='1'; $env:TEST_DATABASE_URL='postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_stage0_20260812_test'; uv run pytest -q
```

前端（仅在生成类型或展示逻辑变化时）：

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

上述验证仅使用 Fake LLM、静态 fixture 与本地 Docker PostgreSQL；不会调用 DeepSeek 或产生 token 费用。

