# 纯明细仅表格还原实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 还原参考项目的纯明细行为：用户只要求查看明细时仅返回表格；明确要求分析时才返回正文和建议。

**架构：** DeepSeek 兼容 LLM 仅在内部 `QueryIntent` 中输出 `analysis_requested`。图编排器在 `DETAIL && !analysis_requested` 时选择无正文的表格分支；安全查询、商家隔离、行数截断和 CSV 导出保持不变。响应模型、历史持久化和前端 Adapter 以同一条件保证空正文不会变成空白消息或不完整数据。

**技术栈：** FastAPI、Pydantic v2、SQLAlchemy Async、pytest、Vue 3、TypeScript、Zod、Vitest、Vue Test Utils。

**执行状态（2026-08-12）：** ✅ 已完成。后端全量 737 passed，前端全量 253 passed；OpenAPI、生成类型与 fixture 一致。仅保留既有 LangGraph 第三方弃用警告和 Vite 的 ECharts chunk 体积提示，均非失败条件。

## 全局约束

- 面向用户的文案、日志与文档使用中文；代码标识符保持英文。
- LLM 只生成结构化意图，绝不生成或执行 SQL；查询仍由既有白名单和绑定参数模板完成。
- 所有测试使用 `FakeLlmClient` 或已有 Stub；禁止真实 DeepSeek 调用，费用为 0。
- `merchant_id` 隔离、截断、受保护导出和降级可见性不得弱化。
- 参考目录 `yshopping-merchant-ai 4/` 只读；不要修改 `docs/project-progress.md` 的用户现有改动。
- 生成的 OpenAPI、前端类型和 fixture 必须通过既有脚本生成，禁止手改。

---

## 文件与接口边界

| 层 | 文件 | 责任 |
| --- | --- | --- |
| 意图 | `backend/app/intent/models.py`、`prompts.py`、`whitelist.py` | 接收并保留 `analysis_requested: bool`，不影响安全查询字段。 |
| 编排 | `backend/app/agent/graph.py` | 计算 `is_table_only_detail`；复用相同查询结果，阻止纯明细进入回答生成、Reviewer 和建议兜底。 |
| API | `backend/app/schemas/chat.py`、会话详情装配 | 仅允许 `DETAIL` 使用 `answer == ""`，此时不要求建议；其他模式仍拒绝空白正文。 |
| 持久化 | `backend/app/services/chat_service.py` | 空正文响应保存 Answer payload 与 `ASSISTANT` message，确保会话详情可装配历史结果。 |
| 前端 | `frontend/src/api/adapters/chat.ts`、`stores/chat.ts`、`ChatMessage.vue`、`DetailTable.vue` | Adapter 接受合法空 DETAIL；视图不渲染空正文容器，仍显示表格、总行数、截断提示和导出。 |

### 统一判定

```python
is_table_only_detail = (
    intent.answer_mode is AnswerMode.DETAIL
    and not intent.analysis_requested
)
```

`analysis_requested` 仅是内部意图字段，不向外部 `ChatResponse` 增加模型原始决策字段。外部契约以 `answer_mode == DETAIL and answer == ""` 表示纯明细；在该形态下 `recommendations` 必须为 `None` 或空列表，非空正文的 DETAIL 仍至少有两条建议。

### 兼容与失败语义

- 旧 Fake LLM / fixture 未提供该字段时，内部模型默认 `True`，保持既有 DETAIL 分析行为；正式提示词要求每次明确输出该字段。
- 对 `DETAIL` 且 `analysis_requested=false`，即使回答模型或兜底逻辑产出文字，最终响应必须清为 `""`；不得以降级说明替代正文。
- 成功纯明细的 `answers.response_payload` 与空正文助手消息均完整保存并可幂等重放；详情 API 能装配历史表格，而前端不展示空白正文卡片。
- 分析型 DETAIL 和所有非 DETAIL 模式维持既有非空正文不变量。

---

### Task 1: 后端契约与意图字段

**Files:**

- Modify: `backend/app/intent/models.py`
- Modify: `backend/app/intent/prompts.py`
- Modify: `backend/app/intent/whitelist.py`
- Modify: `backend/app/schemas/chat.py`
- Test: `backend/tests/unit/intent/test_whitelist.py`
- Test: `backend/tests/unit/schemas/test_chat.py`

**Consumes:** 设计文档 `docs/specs/2026-08-09-r9-intent-contract-design.md` §1。

**Produces:** `QueryIntent.analysis_requested: bool` 与可验证的纯明细 API 形态。

- [ ] **Step 1: 写失败的模型测试。**

在 `test_chat.py` 构造完整的 DETAIL 响应，使 `answer=""`、`recommendations=[]`、表格和 export 均存在；断言当前模型拒绝。再构造 METRIC 或 RULE 的同样空正文，断言必须拒绝；构造 DETAIL 的非空正文且建议不足两条，断言仍拒绝。

- [ ] **Step 2: 运行失败测试。**

Run: `uv run pytest tests/unit/schemas/test_chat.py -q`

Expected: 纯明细样例因 `answer` 的 `min_length=1` 失败；这证明测试覆盖的是缺失契约而非夹具错误。

- [ ] **Step 3: 写失败的意图测试。**

在 `test_whitelist.py` 传入 `analysis_requested=False` 的 DETAIL JSON，断言 `validate_intent(...).intent.analysis_requested is False`；再传入省略字段的既有 DETAIL JSON，断言默认值为 `True`。

- [ ] **Step 4: 运行意图失败测试。**

Run: `uv run pytest tests/unit/intent/test_whitelist.py -q`

Expected: 第一条因 `QueryIntent` 禁止未知字段失败。

- [ ] **Step 5: 最小实现。**

为 `QueryIntent` 增加 `analysis_requested: bool = True`，提示词要求输出 `analysis_requested` 并说明它只能表达“用户是否明确要分析”。保持 `validate_intent()` 用 `model_dump()` / `model_validate()` 传递此字段。将 `ChatResponse.answer` 改为允许空字符串，并在 `validate_cross_field_contract()` 中实现：只有 DETAIL 可以为空；空 DETAIL 不得有建议；非空 DETAIL 必须调用现有 `_require_recommendations()`；任何其他模式 `answer.strip()` 为空都抛出 `ValueError`。

- [ ] **Step 6: 运行聚焦测试并检查格式。**

Run: `uv run pytest tests/unit/intent/test_whitelist.py tests/unit/schemas/test_chat.py -q; uv run ruff check app/intent app/schemas tests/unit/intent/test_whitelist.py tests/unit/schemas/test_chat.py`

Expected: 全绿。

- [ ] **Step 7: 提交该可验证切片。**

```powershell
git add backend/app/intent/models.py backend/app/intent/prompts.py backend/app/intent/whitelist.py backend/app/schemas/chat.py backend/tests/unit/intent/test_whitelist.py backend/tests/unit/schemas/test_chat.py
git commit -m "feat: add table-only detail contract"
```

### Task 2: Graph 分流与无空白历史消息

**Files:**

- Modify: `backend/app/agent/graph.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/unit/agent/test_graph_query_data.py`
- Test: `backend/tests/unit/agent/test_graph_review.py`
- Test: `backend/tests/unit/services/test_chat_service.py`
- Test: `backend/tests/api/test_conversations.py`

**Consumes:** Task 1 的 `analysis_requested` 和条件空正文契约。

**Produces:** 相同 DETAIL 查询、不同回答组合；纯明细幂等回放和历史详情无空助手消息。

- [ ] **Step 1: 写 Graph 的失败测试。**

在 `test_graph_query_data.py` 用两个完整 `FakeLlmClient` 序列分别输出相同的 DETAIL 查询计划，仅将 `analysis_requested` 设为 `false` / `true`。断言两者都调用既有安全查询并返回同列、同数据、同总行数和同 export 条件；前者 `answer == ""`、`recommendations == []`，后者正文非空且至少两条建议。测试不得断言 Fake 的调用次数，而应断言响应可观察行为。

- [ ] **Step 2: 写 Reviewer 跳过的失败测试。**

在 `test_graph_review.py` 为纯明细提供会产生文本的回答 / Reviewer Fake；断言最终正文仍为空、质量轨迹不把空正文判成失败，且返回结果没有模型生成建议。

- [ ] **Step 3: 运行 Graph 测试确认失败。**

Run: `uv run pytest tests/unit/agent/test_graph_query_data.py tests/unit/agent/test_graph_review.py -q`

Expected: 当前实现两种 DETAIL 都产生正文与建议。

- [ ] **Step 4: 最小实现 Graph 分支。**

在 `graph.py` 增加私有 `is_table_only_detail(intent)`。`_compose_answer()` 在该条件下不构造 `AnswerFacts`、不调用回答模型，写入空 `candidate_answer` 和空建议；`_review_answer()` 对该条件只记录步骤并跳过 Reviewer；`_response()` 对纯明细保留 `query_plan/data_rows/total_rows/truncated/export`，显式传入 `recommendations=[]`。分析型 DETAIL 保留现有 Compose/Review/建议路径。

- [ ] **Step 5: 写持久化和详情失败测试。**

在 `test_chat_service.py` 提供返回合法空 DETAIL 的 Agent，提交后断言 Answer 进入 `SUCCEEDED` 且 `response_payload.answer == ""`，但 conversation messages 只有用户消息。在 `test_conversations.py` 请求该会话详情，断言没有 `role == "ASSISTANT" and content == ""` 的记录。

- [ ] **Step 6: 运行持久化失败测试。**

Run: `uv run pytest tests/unit/services/test_chat_service.py tests/api/test_conversations.py -q`

Expected: 当前 `create_message(..., "ASSISTANT", response.answer)` 会写入空助手记录。

- [ ] **Step 7: 最小实现持久化分支。**

在 `ChatService._run_agent()` 中只在 `response.answer.strip()` 非空时创建 `ASSISTANT` message；无论正文是否为空都 touch conversation、保存 Answer payload、提交事务。不要删除用户消息，不要跳过 answer 记录或 export 创建。

- [ ] **Step 8: 运行后端聚焦回归。**

Run: `uv run pytest tests/unit/agent/test_graph_query_data.py tests/unit/agent/test_graph_review.py tests/unit/services/test_chat_service.py tests/api/test_conversations.py -q`

Expected: 全绿。

- [ ] **Step 9: 提交该可验证切片。**

```powershell
git add backend/app/agent/graph.py backend/app/services/chat_service.py backend/tests/unit/agent/test_graph_query_data.py backend/tests/unit/agent/test_graph_review.py backend/tests/unit/services/test_chat_service.py backend/tests/api/test_conversations.py
git commit -m "feat: return table-only detail responses"
```

### Task 3: 前端 Adapter、Store 与表格渲染

**Files:**

- Modify: `frontend/src/api/adapters/chat.ts`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/components/chat/ChatMessage.vue`
- Modify: `frontend/src/components/insights/DetailTable.vue`（仅在现有语义测试揭示需要时）
- Test: `frontend/src/api/adapters/chat.spec.ts`
- Test: `frontend/src/stores/chat.spec.ts`
- Test: `frontend/src/components/chat/ChatMessage.spec.ts`
- Test: `frontend/src/components/insights/DetailTable.spec.ts`

**Consumes:** Task 1 的 API 契约与 Task 2 的不写空助手历史记录语义。

**Produces:** 仅表格的即时明细 UI；前端不把合法空 DETAIL 误报为协议错误。

- [ ] **Step 1: 写 Adapter 失败测试。**

在 `chat.spec.ts` 基于完整 DETAIL fixture 构造 `answer: ""`、`recommendations: []`，断言 `toChatAnswer()` 成功、`answer.text === ""`、数据和 export 原样保留。另断言空 RULE 与空 METRIC 抛出中文协议错误。

- [ ] **Step 2: 运行 Adapter 测试确认失败。**

Run: `npm run test -- src/api/adapters/chat.spec.ts`

Expected: `semanticGuard` 的 `min(1)` 拒绝合法纯明细。

- [ ] **Step 3: 最小实现 Adapter 守卫。**

把通用 `answer` Zod 规则改为可接受字符串；在现有 `superRefine` / 语义守卫中镜像后端规则：空白正文只允许 DETAIL，空 DETAIL 的建议必须为空，其他模式正文必须有非空白字符。领域模型保持 `text: parsed.answer`，不在 Adapter 注入替代文案。

- [ ] **Step 4: 写 Store 与组件失败测试。**

在 `chat.spec.ts` 通过真实 Adapter 注入纯明细完成响应，断言 live assistant round 保留 `answer.data` 和 `answer.export`。在 `ChatMessage.spec.ts` 挂载该 round，断言 `detail-table`、总行数、截断提示/下载入口存在，且没有空正文 `<button class="chat-message__select">` 或空文本主体容器。历史详情中仅有用户消息时断言不渲染空 assistant 卡片。

- [ ] **Step 5: 运行前端失败测试。**

Run: `npm run test -- src/stores/chat.spec.ts src/components/chat/ChatMessage.spec.ts src/components/insights/DetailTable.spec.ts`

Expected: 现有组件把可选轮次无条件渲染为选择按钮，空正文会产生空白容器。

- [ ] **Step 6: 最小实现渲染分支。**

在 `ChatMessage.vue` 增加 `hasAnswerText`，只有该值为真时渲染正文选择按钮；DETAIL 表格继续独立于正文显示。保持质量、降级、步骤、总行数、截断和 export 现有可见性。Store 不把空文本筛掉或替换，历史由后端不创建空助手消息保证。仅在 `DetailTable` 现有测试不能展示总行数、截断或导出时作最小修正。

- [ ] **Step 7: 运行前端聚焦回归。**

Run: `npm run typecheck; npm run test -- src/api/adapters/chat.spec.ts src/stores/chat.spec.ts src/components/chat/ChatMessage.spec.ts src/components/insights/DetailTable.spec.ts`

Expected: 全绿。

- [ ] **Step 8: 提交该可验证切片。**

```powershell
git add frontend/src/api/adapters/chat.ts frontend/src/stores/chat.ts frontend/src/components/chat/ChatMessage.vue frontend/src/components/insights/DetailTable.vue frontend/src/api/adapters/chat.spec.ts frontend/src/stores/chat.spec.ts frontend/src/components/chat/ChatMessage.spec.ts frontend/src/components/insights/DetailTable.spec.ts
git commit -m "feat: render table-only detail responses"
```

### Task 4: 契约生成、审计与全量验证

**Files:**

- Modify: `docs/PRD.md`
- Modify: `docs/backend-development-plan.md`
- Modify: `docs/frontend-development-plan.md`
- Modify: `docs/yshopping-parity-audit.md`
- Modify: `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`
- Generated: `docs/api.md`、`frontend/src/api/generated.ts`、chat fixture 文件

**Consumes:** 前三项的已验证实现。

**Produces:** 同步的公开契约、前端生成物与审计 §3.4 的已修复记录。

- [ ] **Step 1: 更新文档语义。**

PRD 明确“查看最近 20 笔订单”只显示表格，而“分析最近 20 笔订单”显示正文与至少两条建议。后端计划写清内部字段与 API 条件空正文；前端计划写清不渲染空正文容器；审计 §3.4 标为已修复并列出测试入口。勾选主整改计划的 Task 10，不改 `docs/project-progress.md`。

- [ ] **Step 2: 重新生成契约产物。**

Run: `uv run python ../scripts/export_openapi.py; npm run codegen; uv run python ../scripts/export_chat_fixtures.py; npm run fixtures`

Expected: 仅脚本生成的 OpenAPI、TypeScript 和 fixture 变更；禁止手改生成文件。

- [ ] **Step 3: 全量后端验证。**

Run: `uv run ruff check app tests migrations; uv run ruff format --check app tests migrations; uv run mypy app; $env:REQUIRE_INTEGRATION_DB='1'; $env:TEST_DATABASE_URL='postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_stage0_20260812_test'; uv run pytest -q`

Expected: 全绿；允许既有 LangGraph 第三方弃用警告。不会调用真实 LLM。

- [ ] **Step 4: 全量前端验证。**

Run: `npm run codegen:check; npm run fixtures:check; npm run typecheck; npm run lint; npm run format:check; npm run test; npm run build; npm run firstpaint:check; npm run secrets:check; npm run mock:check`

Expected: 全绿；ECharts 既有 chunk-size 提示单独记录为非阻塞 Vite warning。

- [ ] **Step 5: 最终检查并提交。**

Run: `git diff --check; git status --short`

Expected: 不含参考目录、密钥、测试数据库地址或用户的 `docs/project-progress.md`。

```powershell
git add docs/PRD.md docs/backend-development-plan.md docs/frontend-development-plan.md docs/yshopping-parity-audit.md plans/2026-08-09-b7-f4-integration-and-r9-remediation.md docs/api.md docs/fixtures/chat frontend/src/api/generated.ts frontend/src/api/mock/fixtures.generated.ts
git commit -m "docs: close table-only detail parity"
```

## 自检

- [ ] 纯明细非空正文会在模型层失败；其它模式空正文也会失败。
- [ ] 同一受控 DETAIL 查询在“查看”和“分析”措辞下复用查询路径，只有回答组合不同。
- [ ] 纯明细不调用回答 / Reviewer 生成路径，不生成建议，不以降级文本替代正文。
- [ ] 纯明细照常返回表格、总行数、截断和 CSV 导出。
- [ ] Answer payload 可重放；会话详情不存在空白助手消息。
- [ ] Adapter、Store 和组件对空正文 DETAIL 一致，且历史不会渲染空卡片。
- [ ] 文档、OpenAPI、生成类型、fixture 与全量门禁均已同步。
