# 后端 B2：Chat API 与 Fake Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付文档约定的 B2 Chat API：可信商家隔离、Fake Agent、会话持久化、SSE/JSON 双路径、预置推荐问题和幂等处理。

**Architecture:** 路由只负责认证、参数和传输协商；`ChatService` 处理幂等、会话和事务；`FakeAgent` 提供确定性 B2 场景与步骤；Repository 封装消息和回答读写。SSE 与普通 JSON 复用同一份已持久化 `ChatResponse`，从而保持契约一致。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy Async、PostgreSQL、pytest、httpx、Ruff、mypy。

## Global Constraints

- 所有外部可见文案、错误说明和文档使用中文；代码标识符使用英文。
- 商家身份只来自 Bearer Token；请求体、查询参数与自定义头的 `merchant_id` 不得影响数据范围。
- 不调用真实 LLM、网络服务或经营数据查询；Fake 回答使用 `analysis_sources=["FALLBACK"]`、`degraded=true` 和可见原因。
- SSE 只允许 `step`、`done`、`error`；`done` 与 JSON 响应逐字段相同。
- 按 `docs/backend-development-plan.md` §8.1–§8.5 实现；不提前实现 B3–B9 功能。
- 集成测试只用 PostgreSQL；本地库不可用时按现有夹具跳过，CI 用 `REQUIRE_INTEGRATION_DB=1` 硬失败。
- 不执行 Git commit/push/tag/PR；当前目录不是 Git 仓库。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `app/schemas/chat.py` | Chat、会话、步骤及所有 B2 响应模型与跨字段校验 |
| `app/agent/fake_agent.py` | Prototype 四类预置场景的确定性回应和步骤 |
| `app/services/suggested_questions.py` | 纯数据推荐题库与候选组选择 |
| `app/repositories/conversation.py` | 扩展消息、回答及商家范围的会话详情数据访问 |
| `app/services/chat_service.py` | 幂等状态机、事务、持久化和 Agent 编排 |
| `app/api/routes/chat.py` | Chat、会话列表/详情/删除，JSON/SSE 协商 |
| `app/api/router.py` | 注册 B2 路由 |
| `app/core/errors.py` | B2 幂等冲突错误码及安全错误响应 |
| `tests/unit/...` | Schema、题库、Fake Agent 与服务状态机 |
| `tests/api/...` | 路由、认证、JSON/SSE 与传输错误 |
| `tests/integration/...` | PostgreSQL 下持久化、隔离、幂等与会话删除 |
| `scripts/export_openapi.py` | 受控导出 FastAPI OpenAPI 到 `docs/api.md` |

## Task 1: 定义 B2 Schema 与错误码

**Files:**
- Create: `backend/app/schemas/chat.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/tests/unit/core/test_error_codes.py`
- Create: `backend/tests/unit/schemas/test_chat.py`

**Interfaces:**
- Produces `ChatRequest`, `ChatResponse`, `ThinkingStep`, `ConversationListResponse`, `ConversationDetailResponse`, `AnswerMode`, `QualityStatus`, `AnalysisSource`。
- Produces `IdempotencyKeyReusedError` (`409 IDEMPOTENCY_KEY_REUSED`) 与 `RequestInProgressError` (`409 REQUEST_IN_PROGRESS`, `retryable=true`)。

- [ ] **Step 1: 写失败的 Schema 与错误码测试**

```python
def test_chat_mode_accepts_none_source_without_degradation() -> None:
    response = ChatResponse.build_chat(answer="你好")
    assert response.analysis_sources == [AnalysisSource.NONE]
    assert response.degraded is False

def test_metric_requires_metric_owner() -> None:
    with pytest.raises(ValidationError, match="metric_owner"):
        ChatResponse(answer_mode=AnswerMode.METRIC, **metric_without_owner)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/schemas/test_chat.py tests/unit/core/test_error_codes.py -v`

Expected: FAIL，因为 `app.schemas.chat`、B2 枚举或 B2 错误码尚不存在。

- [ ] **Step 3: 实现最小的 Pydantic 契约**

```python
class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    session_id: UUID | None = None
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=0)
    client_request_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]

class ChatResponse(BaseModel):
    id: UUID
    session_id: UUID
    answer: str
    answer_mode: AnswerMode
    # 始终字段、按模式 Optional 字段和 model_validator(mode="after")
```

在模型级校验中落实：来源非空、`NONE` 独占、`CHAT`/`INVALID` 必为 `NONE`、`FALLBACK` 必须降级、`quality_attempts` 在 0–2、METRIC/DETAIL/IDENTITY 的按模式字段要求。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/schemas/test_chat.py tests/unit/core/test_error_codes.py -v`

Expected: PASS；新增 `IDEMPOTENCY_KEY_REUSED` 和 `REQUEST_IN_PROGRESS` 已与文档错误码表对齐。

- [ ] **Step 5: 静态检查本任务文件**

Run: `uv run ruff check app/schemas/chat.py app/core/errors.py tests/unit/schemas/test_chat.py && uv run mypy app/schemas/chat.py app/core/errors.py`

Expected: PASS。

## Task 2: 实现服务端预置推荐问题

**Files:**
- Create: `backend/app/services/suggested_questions.py`
- Create: `backend/tests/unit/services/test_suggested_questions.py`

**Interfaces:**
- Consumes `AnswerMode` 与 `category: str | None`。
- Produces `SuggestedQuestions(current: list[str], alternates: list[list[str]])` 以及 `pick(mode, category)`。

- [ ] **Step 1: 写失败的题库测试**

```python
def test_chat_uses_introductory_question_group() -> None:
    result = pick(AnswerMode.CHAT, None)
    assert result.current == ["昨天总 GMV 是多少？", "最近7天退货量趋势", "我要货品上架，具体规则有吗？"]

def test_alternates_do_not_repeat_current_group() -> None:
    result = pick(AnswerMode.METRIC, "TRADE")
    assert result.current not in result.alternates
    assert all(len(group) == 3 for group in [result.current, *result.alternates])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/services/test_suggested_questions.py -v`

Expected: FAIL，因为题库与 `pick` 尚不存在。

- [ ] **Step 3: 用纯数据配置实现选择器**

```python
QUESTION_GROUPS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "CHAT": (...至少两组入门题...),
    "TRADE": (...至少两组交易追问题...),
    "RETURN": (...至少两组退货追问题...),
    "PRODUCT": (...至少两组商品追问题...),
    "SUPPORT": (...至少两组客服追问题...),
}

def pick(mode: AnswerMode, category: str | None) -> SuggestedQuestions:
    key = "CHAT" if mode is AnswerMode.CHAT else category or "TRADE"
    groups = QUESTION_GROUPS[key]
    return SuggestedQuestions(current=list(groups[0]), alternates=[list(group) for group in groups[1:]])
```

题目复用 Prototype 的 GMV、退货、订单明细、上架规则场景，并新增同域的可追问候选；不做 B3 白名单校验。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/services/test_suggested_questions.py -v`

Expected: PASS。

- [ ] **Step 5: 静态检查**

Run: `uv run ruff check app/services/suggested_questions.py tests/unit/services/test_suggested_questions.py && uv run mypy app/services/suggested_questions.py`

Expected: PASS。

## Task 3: 实现确定性的 Fake Agent

**Files:**
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/fake_agent.py`
- Create: `backend/tests/unit/agent/__init__.py`
- Create: `backend/tests/unit/agent/test_fake_agent.py`

**Interfaces:**
- Consumes `message: str` 和 `session_id: UUID`。
- Produces `FakeAgentResult(response: ChatResponse, steps: list[ThinkingStep])`，由 `FakeAgent.run(...)` 返回。

- [ ] **Step 1: 写失败的场景与降级标记测试**

```python
async def test_refund_question_returns_safe_fallback_metric() -> None:
    result = await FakeAgent().run("最近7天退货量趋势", session_id)
    assert result.response.answer_mode is AnswerMode.METRIC
    assert result.response.category == "RETURN"
    assert result.response.analysis_sources == [AnalysisSource.FALLBACK]
    assert result.response.degraded is True
    assert [step.node for step in result.steps] == ["classify", "compose", "suggest_questions"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/agent/test_fake_agent.py -v`

Expected: FAIL，因为 `FakeAgent` 尚不存在。

- [ ] **Step 3: 实现 Prototype 四种预置场景与安全默认路径**

```python
class FakeAgent:
    async def run(self, message: str, session_id: UUID) -> FakeAgentResult:
        scenario = self._select_scenario(message)
        response = scenario.to_response(session_id=session_id)
        return FakeAgentResult(response=response, steps=[
            ThinkingStep(label="正在识别问题", node="classify"),
            ThinkingStep(label="正在整理演示回答", node="compose"),
            ThinkingStep(label="正在准备推荐问题", node="suggest_questions"),
        ])
```

覆盖 `refund`、`gmv`、`detail`、`rule`；普通问候返回 `CHAT` + `NONE`，危险写操作或未知问题返回 `INVALID` + `NONE`。任何 FALLBACK 场景标注“当前为演示规则结果，未查询经营数据库”。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/agent/test_fake_agent.py -v`

Expected: PASS；测试同时断言无步骤携带 SQL、Prompt 或数据行。

- [ ] **Step 5: 静态检查**

Run: `uv run ruff check app/agent/fake_agent.py tests/unit/agent/test_fake_agent.py && uv run mypy app/agent/fake_agent.py`

Expected: PASS。

## Task 4: 扩展 Repository，完成消息、回答与会话详情查询

**Files:**
- Modify: `backend/app/repositories/conversation.py`
- Create: `backend/tests/integration/repositories/test_chat_repository.py`

**Interfaces:**
- Produces `create_message`, `get_answer_by_client_request`, `create_processing_answer`, `mark_answer_succeeded`, `mark_answer_failed`, `list_messages_for_conversation`, `get_conversation_detail_for_merchant`。
- Every public data-access method accepts `merchant_id: UUID` or derives it from an owned conversation fetched with `merchant_id`.

- [ ] **Step 1: 写 PostgreSQL 失败测试**

```python
async def test_answer_idempotency_lookup_is_scoped_to_merchant(db_session: AsyncSession) -> None:
    repository = ConversationRepository(db_session)
    answer = await repository.create_processing_answer(merchant_one, conversation_one, "request-1", digest)
    assert await repository.get_answer_by_client_request(merchant_two, "request-1") is None
    assert (await repository.get_answer_by_client_request(merchant_one, "request-1")).id == answer.id
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/repositories/test_chat_repository.py -v`

Expected: FAIL，因为回答与消息 Repository 方法尚不存在。

- [ ] **Step 3: 用 ORM 与参数化查询实现最小数据访问层**

```python
async def get_answer_by_client_request(self, merchant_id: UUID, client_request_id: str) -> Answer | None:
    return await self._session.scalar(
        select(Answer).where(
            Answer.merchant_id == merchant_id,
            Answer.client_request_id == client_request_id,
        )
    )
```

成功回答写入 `response_payload`，失败写入安全 `error_payload`，并更新 `processing_status`。会话详情按创建顺序返回消息与回答，不从另一个商家读取任何行。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/integration/repositories/test_chat_repository.py tests/integration/repositories/test_conversation_repository.py -v`

Expected: PASS。

- [ ] **Step 5: 静态检查**

Run: `uv run ruff check app/repositories/conversation.py tests/integration/repositories/test_chat_repository.py && uv run mypy app/repositories/conversation.py`

Expected: PASS。

## Task 5: 实现 ChatService 与幂等状态机

**Files:**
- Create: `backend/app/services/chat_service.py`
- Create: `backend/tests/unit/services/test_chat_service.py`
- Create: `backend/tests/integration/services/test_chat_service.py`

**Interfaces:**
- Consumes `MerchantContext`, `ChatRequest`, `request_id`、`ConversationRepository` 和 `FakeAgent`。
- Produces `ChatExecution(response: ChatResponse, steps: list[ThinkingStep], replayed: bool)`。

- [ ] **Step 1: 写失败的状态机测试**

```python
async def test_succeeded_request_replays_saved_response_without_running_agent() -> None:
    result = await service.submit(context, request, request_id="r1")
    replay = await service.submit(context, request, request_id="r2")
    assert replay.response == result.response
    assert fake_agent.calls == 1

async def test_reused_key_with_different_digest_is_conflict() -> None:
    await service.submit(context, request_with_message("昨天GMV"), request_id="r1")
    with pytest.raises(IdempotencyKeyReusedError):
        await service.submit(context, request_with_message("最近订单"), request_id="r2")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/services/test_chat_service.py tests/integration/services/test_chat_service.py -v`

Expected: FAIL，因为 `ChatService.submit` 尚不存在。

- [ ] **Step 3: 实现会话、事务和五分支幂等逻辑**

```python
digest = sha256(canonical_message_and_attachment_ids(request)).hexdigest()
existing = await repository.get_answer_by_client_request(context.merchant_id, request.client_request_id)
if existing and existing.request_digest != digest:
    raise IdempotencyKeyReusedError()
if existing and existing.processing_status == "SUCCEEDED":
    return ChatExecution.from_saved(existing)
if existing and existing.processing_status == "PROCESSING":
    raise RequestInProgressError()
```

对 `FAILED_RETRYABLE` 将同一行恢复为 `PROCESSING` 后执行；对 `FAILED_FINAL` 重建并抛出已保存的安全错误。新请求创建/校验所属 session，保存 USER message，先创建 PROCESSING Answer，提交其可见状态，运行 Fake Agent，最后在同一事务中保存 ASSISTANT message 和成功 payload。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/services/test_chat_service.py tests/integration/services/test_chat_service.py -v`

Expected: PASS；涵盖摘要冲突、处理中、成功重放、可重试失败、终态失败、连续 session 和商家隔离。

- [ ] **Step 5: 静态检查**

Run: `uv run ruff check app/services/chat_service.py tests/unit/services/test_chat_service.py tests/integration/services/test_chat_service.py && uv run mypy app/services/chat_service.py`

Expected: PASS。

## Task 6: 实现 Chat 与会话 HTTP/SSE 路由

**Files:**
- Create: `backend/app/api/routes/chat.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/dependencies.py`
- Create: `backend/tests/api/test_chat.py`
- Create: `backend/tests/api/test_conversations.py`

**Interfaces:**
- Produces `POST /api/chat`, `GET /api/conversations`, `GET /api/conversations/{id}`, `DELETE /api/conversations/{id}`。
- `POST /api/chat` returns `application/json` only for an `Accept` header containing `application/json`; otherwise returns `text/event-stream; charset=utf-8`.

- [ ] **Step 1: 写失败的 API 契约测试**

```python
async def test_json_chat_equals_sse_done_payload(client: AsyncClient) -> None:
    json_response = await client.post("/api/chat", headers={**auth, "Accept": "application/json"}, json=payload)
    sse_response = await client.post("/api/chat", headers=auth, json={**payload, "client_request_id": "new-id"})
    assert json_response.headers["content-type"].startswith("application/json")
    assert parse_sse(sse_response.text)[-1] == ("done", json_response.json())

async def test_cross_merchant_conversation_returns_audited_scope_error(...) -> None:
    response = await client_two.get(f"/api/conversations/{conversation_one}")
    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_chat.py tests/api/test_conversations.py -v`

Expected: FAIL，路由尚未注册。

- [ ] **Step 3: 实现依赖、路由和 SSE 编码器**

```python
def encode_sse(event: str, payload: BaseModel | dict[str, object]) -> bytes:
    data = json.dumps(model_or_dict, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\\ndata: {data}\\n\\n".encode()

async def event_stream() -> AsyncIterator[bytes]:
    execution = await chat_service.submit(context, request, request_id=request.state.request_id)
    for step in execution.steps:
        yield encode_sse("step", step)
    yield encode_sse("done", execution.response)
```

设置 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`，每 15 秒插入 `: keep-alive\n\n`。已发送响应后的服务异常转换为 `event: error`；认证和请求校验在开始流前由全局 JSON 错误处理器返回。会话详情和删除用 `MerchantScopeService`，删除成功返回 `204`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/api/test_chat.py tests/api/test_conversations.py -v`

Expected: PASS；至少一个 `step`，最后仅有 `done` 或 `error`，JSON 与 done 同构，跨商家操作为 403 且 B1 审计写入。

- [ ] **Step 5: 静态检查**

Run: `uv run ruff check app/api/routes/chat.py app/api/router.py app/api/dependencies.py tests/api/test_chat.py tests/api/test_conversations.py && uv run mypy app/api`

Expected: PASS。

## Task 7: 完成集成回归与 OpenAPI 契约快照

**Files:**
- Create: `backend/tests/api/test_openapi_chat_contract.py`
- Modify: `backend/tests/integration/conftest.py`（仅在新增表时；预期无需迁移）
- Create: `scripts/export_openapi.py`
- Create: `docs/api.md`（由 FastAPI OpenAPI 导出；若项目已有同名文件则更新）

**Interfaces:**
- Verifies FastAPI exposes the exact B2 paths and response schemas as the source for frontend type generation.

- [ ] **Step 1: 写失败的 OpenAPI 路径与模型测试**

```python
def test_openapi_exposes_b2_chat_and_conversation_contract(app: FastAPI) -> None:
    schema = app.openapi()
    assert set(schema["paths"]) >= {
        "/api/chat", "/api/conversations", "/api/conversations/{id}",
    }
    assert schema["components"]["schemas"]["ChatResponse"]["properties"]["session_id"]
    assert "conversation_id" not in schema["components"]["schemas"]["ChatResponse"]["properties"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_openapi_chat_contract.py -v`

Expected: FAIL，直至 Task 6 路由及 Chat schema 的 OpenAPI 暴露完整。

- [ ] **Step 3: 创建受控导出脚本并生成 API 文档**

```python
def main() -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )
    schema = create_app(settings).openapi()
    output = Path(__file__).resolve().parents[1] / "docs" / "api.md"
    output.write_text(render_openapi_markdown(schema), encoding="utf-8")
```

脚本仅导出 FastAPI 已生成的 OpenAPI；不手写或更改 schema 内容。随后运行：`uv run python ../scripts/export_openapi.py`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/api/test_openapi_chat_contract.py -v`

Expected: PASS；文档、路径和 `ChatResponse` 字段一致。

- [ ] **Step 5: 运行 B2 全量验证**

Run: `uv run ruff check .; uv run ruff format --check .; uv run mypy app; uv run pytest`

Expected: 全部 PASS；集成库未启动时仅现有集成夹具跳过，不能出现其他失败或网络调用。
