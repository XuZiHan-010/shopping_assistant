# N1 模型客户端协议与 DeepSeek 双协议适配实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。
> **Task 6 会产生真实费用，未获 R3 授权前不得执行**；Task 1–5、7 全部使用 Fake LLM，无费用。

**目标：** 实现 PRD A1 的模型客户端抽象：把现有只能"问一句答一句"的 `LlmClient` 扩展为
能表达**工具调用**与**流式**的协议，并提供 DeepSeek 的 OpenAI 与 Anthropic 两种协议适配器，
为 N2 的工具循环（§6.10）准备好上游能力。

**架构：** 协议先行——先定 `LlmClient` 的新方法与数据类，再让两个适配器各自实现。
现有 `complete()` **保留不动**，v1 链路继续用它；新增 `converse()` 承载工具调用，
v1 与 v2 因此可以并存（§5.6）。

**技术栈：** Python 3.12、httpx、Pydantic v2、pytest。HTTP mock 用 `httpx.MockTransport`，
沿用 `tests/unit/llm/test_deepseek_client.py` 与 `DeepSeekLlmClient(transport=...)` 的既有注入方式，
**不新增 `respx` 等测试依赖**（`pyproject.toml` 与 `uv.lock` 里都没有它）。

**规格来源：**
- `docs/PRD.md` A1（模型客户端抽象）、A2（工具循环对上游的要求）、§16 风险表第 1 行
- `docs/backend-development-plan.md` §5.6（衔接表）、§6.10（循环对 `LlmClient` 的依赖）
- `AGENTS.md` R3（费用审批、DeepSeek 双协议、默认模型 `deepseek-flash`）、R6（密钥）
- `docs/specs/2026-09-18-anthropic-fusion-decisions.md` O7
- DeepSeek 官方文档（2026-09-21 查阅，实现前复核）：
  [Anthropic 兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)、
  [工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、
  [思考模式](https://api-docs.deepseek.com/guides/thinking_mode)、
  [上下文缓存](https://api-docs.deepseek.com/guides/kv_cache)

---

## 全局约束

- 中文（R1）；标识符英文。
- **不执行任何 Git 操作**（R2）。
- **Task 1–5、7 全程使用 Fake LLM 与 `httpx.MockTransport`，零费用。**
  Task 6 是唯一涉及真实调用的任务，单独授权，见该任务的 R3 说明。
- **不修改 `app/agent/graph.py`**（冻结基线，§5.6）。
- **不修改现有 `complete()` 的签名与行为**——v1 的 1128 个测试依赖它。
- `LLM_API_KEY` 只从环境变量读取，`.env.example` 只放占位符（R6）。

## 官方文档里会直接影响设计的四点

2026-09-21 审查时对照官方文档发现，下面四点只靠单轮 mock 测不出来，必须写进协议与用例：

| 事实 | 对本计划的影响 |
| --- | --- |
| 思考模式**默认开启**；带 `tools` 的请求，之前每一轮 assistant 的 `reasoning_content` 必须在后续请求里**完整回传**，否则 API 返回 400 | `LlmTurn` / `LlmMessage` 要携带并回放推理内容；多轮工具历史需要专门的序列化测试与真实冒烟 |
| OpenAI 兼容接口的缓存计量字段是 `usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` | `LlmTurn` 增加缓存字段；**未上报记为 `None`，不记为 0** |
| Anthropic 兼容接口忽略 `cache_control`，文档未列出缓存用量字段 | Anthropic 适配器的缓存字段默认 `None`，是否上报以冒烟实测为准 |
| Anthropic 兼容接口遇到**不支持的模型名会自动映射到 `deepseek-flash`** | "传非法模型名"不能作为错误分类用例，改用确定会报错的受控请求 |

这些是文档陈述，不是实测。它们决定了**要测什么**，结论仍以 Task 6 的真实冒烟为准。

---

## 为什么现有协议不够用

现有 `app/llm/client.py` 的协议是：

```python
async def complete(self, *, system: str, user: str, fallback: str,
                   budget: LlmBudget, options: LlmCallOptions) -> LlmResult: ...
```

它有三个限制，**每一个都挡住 N2 的工具循环**：

| 限制 | 后果 |
| --- | --- |
| 输入是两个字符串，不是消息列表 | 多轮工具调用无法表达——第 2 轮要带上第 1 轮的工具结果 |
| 没有工具定义入参 | 模型不知道有哪些工具可用 |
| 返回只有 `text` | 拿不到 `tool_calls`，循环无从得知该调什么 |

所以 A1 的实质工作**不是"再写一个适配器"，是扩协议**。新增 `converse()` 与之并存：

```python
async def converse(self, *, messages: list[LlmMessage], tools: list[ToolSchema],
                   budget: LlmBudget, options: LlmCallOptions) -> LlmTurn: ...
```

---

## 文件结构

| 文件 | 责任 | 操作 |
| --- | --- | --- |
| `backend/app/llm/client.py` | 新增 `LlmMessage` / `ToolSchema` / `LlmToolCall` / `LlmTurn` / `converse()` | 修改（只增不改） |
| `backend/app/llm/openai_adapter.py` | DeepSeek OpenAI 兼容协议的 `converse()` | 新建 |
| `backend/app/llm/anthropic_adapter.py` | DeepSeek Anthropic 兼容协议的 `converse()` | 新建 |
| `backend/app/llm/deepseek.py` | 保留现有 `complete()`；`converse()` 委派给选定适配器 | 修改 |
| `backend/app/llm/fake.py` | `FakeLlmClient` 补 `converse()`，可编排工具调用脚本 | 修改 |
| `backend/app/core/config.py` | `LLM_PROTOCOL` 开关；默认模型迁移 | 修改 |
| `backend/tests/unit/llm/test_converse_contract.py` | 协议层契约测试 | 新建 |
| `backend/tests/unit/llm/_transport.py` | `recording_transport()`：记录请求、按序回放 JSON 或 SSE 响应 | 新建 |
| `backend/tests/unit/llm/test_openai_adapter.py` | MockTransport，零费用 | 新建 |
| `backend/tests/unit/llm/test_anthropic_adapter.py` | MockTransport，零费用 | 新建 |
| `backend/tests/unit/llm/test_streaming.py` | 两协议的流式解析 | 新建 |
| `backend/tests/unit/llm/test_history_serialization.py` | 两协议的多轮工具历史请求体 | 新建 |
| `backend/scripts/llm_smoke.py` | **真实调用**冒烟脚本，默认不执行 | 新建 |
| `docs/backend-development-plan.md` §6.17 | Model Client 模块契约 | 新增 |

---

### Task 1：扩展 `LlmClient` 协议

**文件：**
- 修改：`backend/app/llm/client.py`（**只增不改**）
- 创建：`backend/tests/unit/llm/test_converse_contract.py`

**接口产出：**

```python
@dataclass(frozen=True)
class ReasoningReplay:
    """上一轮的推理内容，原样回放给**同一协议**。适配器之外不解读它。"""
    protocol: Literal["openai", "anthropic"]
    payload: str                         # OpenAI：reasoning_content；Anthropic：thinking 块的 JSON


@dataclass(frozen=True)
class LlmMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None      # role="tool" 时必填
    tool_calls: list[LlmToolCall] | None = None   # role="assistant" 时可能有
    reasoning: ReasoningReplay | None = None      # role="assistant" 时由上一轮 LlmTurn 带回


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, object]        # JSON Schema，由 Pydantic 模型导出


@dataclass(frozen=True)
class LlmToolCall:
    call_id: str
    tool_name: str
    arguments_json: str                  # 原始串，**由调用方用 Pydantic 校验**（R4）


@dataclass(frozen=True)
class LlmTurn:
    text: str | None
    tool_calls: list[LlmToolCall]
    stop_reason: Literal["END_TURN", "TOOL_USE", "MAX_TOKENS", "ERROR"]
    tokens: int
    input_tokens: int = 0
    output_tokens: int = 0
    degraded: bool = False
    failure_kind: LlmFailureKind | None = None
    usage_known: bool = False
    cache_hit_tokens: int | None = None   # None = 提供方未上报，不等于 0
    cache_miss_tokens: int | None = None
    reasoning: ReasoningReplay | None = None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class TurnComplete:
    turn: LlmTurn                         # 与 converse() 的返回值同构


LlmStreamEvent = TextDelta | TurnComplete
```

协议同时新增流式方法：

```python
def converse_stream(self, *, messages: list[LlmMessage], tools: list[ToolSchema],
                    budget: LlmBudget, options: LlmCallOptions) -> AsyncIterator[LlmStreamEvent]: ...
```

- 文本增量逐段产出 `TextDelta`；**工具调用不产出增量**——参数分片在适配器内拼完，只在最后的
  `TurnComplete.turn.tool_calls` 里出现。半截参数交给上层没有任何用处，还可能被误执行；
- 流以且仅以一个 `TurnComplete` 结束。中途断流时 `TurnComplete.turn` 为降级结果
  （`stop_reason="ERROR"`、`degraded=True`、`tool_calls=[]`），**已经收到的工具调用分片一律丢弃**；
- N2 的循环用 `converse()` 还是 `converse_stream()` 由 N2 决定；本计划两者都实现并测试，
  因为 PRD A1 要求验证流式。

**`arguments_json` 保持字符串是有意的。** 适配器不解析工具参数——解析与校验是
工具注册表的职责（§6.9，R4 要求参数经 Pydantic 校验）。适配器要是自作主张 `json.loads()`
并吞掉异常，畸形参数就会以"参数是空字典"的面目进入工具，而不是被闸门拦下。

- [x] **步骤 1：写协议契约测试**

```python
import pytest
from app.llm.client import LlmMessage, LlmToolCall, LlmTurn, ToolSchema


def test_tool_message_requires_call_id() -> None:
    with pytest.raises(ValueError):
        LlmMessage(role="tool", content="{}")


def test_tool_call_keeps_arguments_as_raw_string() -> None:
    """适配器不解析参数——解析与校验属于工具注册表（R4）。"""
    tc = LlmToolCall(call_id="c1", tool_name="search", arguments_json='{"q":1}')
    assert isinstance(tc.arguments_json, str)
    assert not hasattr(tc, "arguments")


def test_turn_with_tool_use_must_carry_tool_calls() -> None:
    with pytest.raises(ValueError):
        LlmTurn(text=None, tool_calls=[], stop_reason="TOOL_USE", tokens=10)


def test_turn_with_end_turn_must_carry_text() -> None:
    with pytest.raises(ValueError):
        LlmTurn(text=None, tool_calls=[], stop_reason="END_TURN", tokens=10)


def test_unreported_cache_usage_is_none_not_zero() -> None:
    """缓存未上报记 None：记成 0 会让成本估算误以为全部未命中。"""
    turn = LlmTurn(text="x", tool_calls=[], stop_reason="END_TURN", tokens=1)
    assert turn.cache_hit_tokens is None and turn.cache_miss_tokens is None


def test_existing_complete_signature_unchanged() -> None:
    """v1 的 1128 个测试依赖它，签名不得变动。"""
    import inspect
    from app.llm.client import LlmClient
    sig = inspect.signature(LlmClient.complete)
    assert set(sig.parameters) >= {"system", "user", "fallback", "budget", "options"}
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/llm/test_converse_contract.py -v
```

`__post_init__` 里做那三条一致性校验（tool 消息要 `call_id`、`TOOL_USE` 要有工具调用、
`END_TURN` 要有文本），不要留给调用方检查。

- [x] **步骤 3：v1 零回归确认**

```powershell
cd backend; uv run pytest tests/unit/llm/ tests/api/ -v
```

期望：既有用例全绿。本任务只往 `client.py` 加东西，**一行既有代码都不该改**。

---

### Task 2：OpenAI 协议适配器

DeepSeek 的 OpenAI 兼容接口，根地址 `https://api.deepseek.com`，端点 `/chat/completions`。

**文件：**
- 创建：`backend/app/llm/openai_adapter.py`
- 创建：`backend/tests/unit/llm/test_openai_adapter.py`

**接口：**
- 消费：Task 1 的全部数据类；既有 `LlmBudget`、`LlmFailureKind`、`_usage_value()`
- 产出：`OpenAiConverseAdapter.converse()`

### 规则

- **预算先扣后发**：沿用 `deepseek.py:47-51` 既有做法——先 `budget.charge_call()`，
  再把 `remaining` 作为 `max_tokens` 随请求发出。事后记账挡不住已经付过的钱；
- 工具定义按 OpenAI 格式装配 `{"type":"function","function":{...}}`；
- 响应里 `message.tool_calls` 映射为 `LlmToolCall`，`finish_reason="tool_calls"` → `TOOL_USE`；
- 失败分类复用既有 `LlmFailureKind`，**不新增枚举**（§5.6 衔接表）;
- 构造函数与 `DeepSeekLlmClient` 一样接受可选 `transport: httpx.AsyncBaseTransport`，生产不传；
- **全部测试注入 `httpx.MockTransport`，零真实请求、零费用。**

- [x] **步骤 1：写 `recording_transport()` 夹具**

```python
# tests/unit/llm/_transport.py
def recording_transport(*responses: httpx.Response) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """按序回放响应并记录请求；响应用完仍被调用即测试失败。"""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert queue, f"意外的第 {len(seen)} 次请求：{request.url}"
        return queue.pop(0)

    return httpx.MockTransport(handler), seen


def sse(*events: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content="".join(f"{e}\n\n" for e in events).encode())
```

- [x] **步骤 2：写单轮失败测试**

```python
from app.llm.openai_adapter import OpenAiConverseAdapter

URL = "https://api.deepseek.com/chat/completions"


async def test_tool_call_response_is_mapped(settings) -> None:
    transport, seen = recording_transport(httpx.Response(200, json={
        "choices": [{"finish_reason": "tool_calls", "message": {
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "search", "arguments": '{"q":"壶"}'}}],
        }}],
        "usage": {"total_tokens": 88, "prompt_tokens": 60, "completion_tokens": 28,
                  "prompt_cache_hit_tokens": 40, "prompt_cache_miss_tokens": 20},
    }))
    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=[LlmMessage(role="user", content="找个壶")],
        tools=[SEARCH_TOOL], budget=LlmBudget(max_calls=5, max_tokens=1000),
    )
    assert str(seen[0].url) == URL
    assert turn.stop_reason == "TOOL_USE"
    assert turn.tool_calls[0].tool_name == "search"
    assert turn.tool_calls[0].arguments_json == '{"q":"壶"}'
    assert turn.tokens == 88 and turn.usage_known is True
    assert (turn.cache_hit_tokens, turn.cache_miss_tokens) == (40, 20)


async def test_missing_cache_fields_stay_none(settings) -> None:
    transport, _ = recording_transport(httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": "好"}}],
        "usage": {"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 1}}))
    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(...)
    assert turn.cache_hit_tokens is None and turn.cache_miss_tokens is None


async def test_budget_charged_before_request(settings) -> None:
    """预算耗尽时不得发出请求——发出去就要付钱。"""
    transport, seen = recording_transport()
    budget = LlmBudget(max_calls=0, max_tokens=1000)
    with pytest.raises(LlmBudgetExceededError):
        await OpenAiConverseAdapter(settings, transport=transport).converse(
            messages=[LlmMessage(role="user", content="x")], tools=[], budget=budget)
    assert seen == []                     # 关键断言


async def test_malformed_arguments_are_passed_through_not_swallowed(settings) -> None:
    """畸形参数必须原样上交，由工具注册表拦下（R4）。"""
    transport, _ = recording_transport(httpx.Response(200, json={
        "choices": [{"finish_reason": "tool_calls", "message": {"content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "search", "arguments": "{not json"}}]}}],
        "usage": {}}))
    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=[LlmMessage(role="user", content="x")], tools=[SEARCH_TOOL],
        budget=LlmBudget(max_calls=5, max_tokens=1000))
    assert turn.tool_calls[0].arguments_json == "{not json"   # 不解析、不吞异常


async def test_http_429_maps_to_known_failure_kind(settings) -> None:
    transport, _ = recording_transport(httpx.Response(429))
    turn = await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=[LlmMessage(role="user", content="x")], tools=[],
        budget=LlmBudget(max_calls=5, max_tokens=1000))
    assert turn.failure_kind is LlmFailureKind.HTTP_429
    assert turn.degraded is True
```

- [x] **步骤 3：多轮工具历史的请求体**（`test_history_serialization.py`）

单轮 mock 只证明"能解析一次响应"，证明不了"第二轮请求发得对"——而思考模式下第二轮发错会直接 400。

```python
async def test_openai_second_round_replays_tool_calls_results_and_reasoning(settings) -> None:
    transport, seen = recording_transport(ok_text_response())
    history = [
        LlmMessage(role="user", content="找个壶"),
        LlmMessage(role="assistant", content="", tool_calls=[LlmToolCall("c1", "search", '{"q":"壶"}')],
                   reasoning=ReasoningReplay("openai", "先搜索商品")),
        LlmMessage(role="tool", content='{"items":[]}', tool_call_id="c1"),
    ]
    await OpenAiConverseAdapter(settings, transport=transport).converse(
        messages=history, tools=[SEARCH_TOOL], budget=LlmBudget(max_calls=5, max_tokens=1000))
    body = json.loads(seen[0].content)
    assistant = body["messages"][1]
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"q":"壶"}'   # 原串，不重新序列化
    assert assistant["reasoning_content"] == "先搜索商品"                          # 缺了会 400
    assert body["messages"][2] == {"role": "tool", "tool_call_id": "c1", "content": '{"items":[]}'}


def test_reasoning_from_other_protocol_is_rejected() -> None:
    """推理回放绑定协议；把 Anthropic 的 thinking 块塞给 OpenAI 接口只会得到 400。"""
    with pytest.raises(ValueError, match="协议"):
        serialize_openai_messages([LlmMessage(role="assistant", content="x",
                                              reasoning=ReasoningReplay("anthropic", "{}"))])
```

**同一次对话的循环只用一种协议**：`LLM_PROTOCOL` 是进程级配置，切换协议时新开对话，
不跨协议回放历史。

- [x] **步骤 4：流式**（`test_streaming.py`）

```python
async def test_openai_stream_text_deltas_and_final_usage(settings) -> None:
    transport, seen = recording_transport(sse(
        'data: {"choices":[{"delta":{"content":"你"}}]}',
        'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"total_tokens":9,"prompt_tokens":7,"completion_tokens":2,'
        '"prompt_cache_hit_tokens":5,"prompt_cache_miss_tokens":2}}',
        "data: [DONE]"))
    events = [e async for e in OpenAiConverseAdapter(settings, transport=transport).converse_stream(...)]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "你好"
    final = events[-1].turn
    assert final.text == "你好" and final.tokens == 9 and final.cache_hit_tokens == 5
    assert json.loads(seen[0].content)["stream"] is True


async def test_openai_stream_assembles_tool_call_fragments(settings) -> None:
    transport, _ = recording_transport(sse(
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"search","arguments":"{\\"q\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"壶\\"}"}}]},"finish_reason":"tool_calls"}]}',
        "data: [DONE]"))
    events = [e async for e in OpenAiConverseAdapter(settings, transport=transport).converse_stream(...)]
    assert not any(isinstance(e, TextDelta) for e in events)       # 工具调用不产出增量
    assert events[-1].turn.tool_calls[0].arguments_json == '{"q":"壶"}'


async def test_stream_cut_midway_drops_partial_tool_calls(settings) -> None:
    transport, _ = recording_transport(sse(
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"search","arguments":"{\\"q"}}]}}]}'))
    events = [e async for e in OpenAiConverseAdapter(settings, transport=transport).converse_stream(...)]
    final = events[-1].turn
    assert final.stop_reason == "ERROR" and final.degraded and final.tool_calls == []
```

流式请求是否要带 `stream_options.include_usage` 才能拿到用量、DeepSeek 是否支持，
**以 Task 6 实测为准**；mock 里的末尾用量块只是按 OpenAI 格式写的预期。

- [x] **步骤 5：确认失败 → 实现 → 确认通过**

```powershell
cd backend; uv run pytest tests/unit/llm/ -v
```

---

### Task 3：Anthropic 协议适配器

DeepSeek 的 Anthropic 兼容接口，协议地址 `https://api.deepseek.com/anthropic`。
**`LLM_BASE_URL` 仍存根地址**，`/anthropic` 由适配器内部拼接（AGENTS.md R3）。

**文件：**
- 创建：`backend/app/llm/anthropic_adapter.py`
- 创建：`backend/tests/unit/llm/test_anthropic_adapter.py`

### 与 OpenAI 协议的四处差异

适配器要吸收这些差异，**让 `LlmTurn` 在两种协议下形状完全一致**：

| | OpenAI 兼容 | Anthropic 兼容 |
| --- | --- | --- |
| 端点 | `/chat/completions` | `/anthropic/v1/messages` |
| 认证头 | `authorization: Bearer <key>` | `x-api-key: <key>` + `anthropic-version` |
| system | `messages` 里的一条 | **顶层 `system` 参数**，不在 messages 里 |
| 工具调用 | `message.tool_calls[]` | `content[]` 里 `type="tool_use"` 的块 |
| 用量字段 | `usage.total_tokens` | `usage.input_tokens` + `output_tokens`（**无 total**） |

最后一行是坑：Anthropic 格式**不返回 `total_tokens`**，要自己相加。
`usage_known` 的判定条件因此与 OpenAI 适配器不同，不能照抄 `_usage_value()` 的集合比较。

- [x] **步骤 1：写失败测试**，至少覆盖：

```python
URL = "https://api.deepseek.com/anthropic/v1/messages"


async def test_system_goes_to_top_level_not_messages(settings) -> None:
    transport, seen = recording_transport(httpx.Response(200, json={
        "content": [{"type": "text", "text": "好的"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5}}))
    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=[LlmMessage(role="system", content="你是助手"),
                  LlmMessage(role="user", content="你好")],
        tools=[], budget=LlmBudget(max_calls=5, max_tokens=1000))
    assert str(seen[0].url) == URL
    body = json.loads(seen[0].content)
    assert body["system"] == "你是助手"
    assert all(m["role"] != "system" for m in body["messages"])


async def test_total_tokens_is_summed_and_cache_defaults_to_none(settings) -> None:
    """Anthropic 格式没有 total_tokens，必须相加；文档未列缓存字段，未上报即 None。"""
    transport, _ = recording_transport(httpx.Response(200, json={
        "content": [{"type": "text", "text": "x"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5}}))
    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(...)
    assert turn.tokens == 15 and turn.usage_known is True
    assert turn.cache_hit_tokens is None


async def test_tool_use_block_is_mapped(settings) -> None:
    transport, _ = recording_transport(httpx.Response(200, json={
        "content": [{"type": "tool_use", "id": "c1", "name": "search", "input": {"q": "壶"}}],
        "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1}}))
    turn = await AnthropicConverseAdapter(settings, transport=transport).converse(...)
    assert turn.stop_reason == "TOOL_USE"
    assert json.loads(turn.tool_calls[0].arguments_json) == {"q": "壶"}


async def test_second_round_sends_tool_result_blocks_and_thinking(settings) -> None:
    """多轮：assistant 的 tool_use 块、user 的 tool_result 块、thinking 块按原样回放。"""
    transport, seen = recording_transport(ok_anthropic_text())
    await AnthropicConverseAdapter(settings, transport=transport).converse(
        messages=THREE_MESSAGE_TOOL_HISTORY_WITH_ANTHROPIC_REASONING, tools=[SEARCH_TOOL], budget=...)
    msgs = json.loads(seen[0].content)["messages"]
    assert msgs[1]["content"][0]["type"] == "thinking"
    assert any(b["type"] == "tool_use" and b["id"] == "c1" for b in msgs[1]["content"])
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "c1", "content": '{"items":[]}'}


async def test_anthropic_stream_events_are_assembled(settings) -> None:
    transport, _ = recording_transport(sse(
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":7,"output_tokens":0}}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你"}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"好"}}',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
        'event: message_stop\ndata: {"type":"message_stop"}'))
    events = [e async for e in AnthropicConverseAdapter(settings, transport=transport).converse_stream(...)]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "你好"
    assert events[-1].turn.tokens == 9
```

> 注意最后一条的不对称：Anthropic 的 `input` 本来就是对象，适配器要把它**序列化回字符串**
> 存进 `arguments_json`，以保持两种协议下 `LlmToolCall` 形状一致。这是唯一允许适配器
> 碰参数的地方，且只做序列化，不做校验。

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

- [x] **步骤 3：两适配器等价性测试**

新建 `tests/unit/llm/test_adapter_parity.py`：喂等价的 mock 响应给两个适配器，
断言产出的 `LlmTurn` **逐字段相等**（`tokens`、`stop_reason`、`tool_calls`、`usage_known`），
覆盖三种形态：单轮文本、单轮工具调用、流式文本（比较最终 `TurnComplete.turn`）。
`reasoning` 与缓存字段按协议不同，**不纳入逐字段比较**，只断言各自符合本协议的预期。

这条测试的价值在于：将来换协议时，上层循环不该察觉任何差异。**但它只证明两个适配器对
"我们以为的响应格式"解析一致，不证明两个真实接口行为等价**——尤其是多轮工具历史，
OpenAI 兼容接口在思考模式下会因缺少 `reasoning_content` 直接 400。两协议是否都能跑通
多轮工具调用，只能由 Task 6 的真实冒烟回答，未实测前不得宣称等价。

---

### Task 4：协议选择开关与客户端装配

**文件：**
- 修改：`backend/app/core/config.py`
- 修改：`backend/app/llm/deepseek.py`（补 `converse()`，委派给选定适配器）
- 修改：`backend/app/llm/fake.py`（补 `converse()`）

### 规则

- 新增配置 `LLM_PROTOCOL`，取值 `openai` | `anthropic`，**默认 `openai`**
  （现有 v1 链路已在用，切换须有 Task 6 的实测依据）；
- 新增配置 `LLM_THINKING`，取值 `enabled` | `disabled`，**默认 `disabled`**，适配器**每次请求都显式发送**
  该设置，不依赖提供方默认值（官方默认开启）。开启后成本、延迟与回放要求都不同，改默认值须以
  Task 6 的实测为据；Anthropic 兼容接口对思考参数的支持情况同样以实测为准；
- `DeepSeekLlmClient.complete()` **保持原样**，`converse()` / `converse_stream()` 新增并按 `LLM_PROTOCOL` 委派；
- `FakeLlmClient.converse()` 支持编排一个**工具调用脚本**，让 N2 的循环测试可以
  在零费用下演练多轮：

```python
FakeLlmClient(turns=[
    LlmTurn(text=None, tool_calls=[LlmToolCall("c1", "search_products", '{"q":"壶"}')],
            stop_reason="TOOL_USE", tokens=20),
    LlmTurn(text="本店有 2 款…", tool_calls=[], stop_reason="END_TURN", tokens=30),
])
```

**这个脚本能力是 N2 全部循环测试的基础设施**，不是可选项——没有它，
工具循环的轮数上限、并行、致命错误终止都没法在 CI 里验证。

- [x] **步骤 1：写失败测试** — 协议开关生效、Fake 脚本按序返回、脚本耗尽后行为明确。
- [x] **步骤 2：确认失败 → 实现 → 确认通过**
- [x] **步骤 3：全量回归**（2026-09-22：`REQUIRE_INTEGRATION_DB=1 uv run pytest` **1930 passed / 2 failed / 0 errors**，2 个失败均为模块 C 新增用例——`test_n1_c_core_migrations::test_product_stock_is_derived_and_cannot_oversell`（`ck_products_reserved_le_on_hand`）与 `test_demo_determinism::test_three_merchant_seed_is_repeatable_in_postgres`，与本模块无关；v1 零回归；`ruff check .` 与 `mypy app` 全部通过。当时**全量并非全绿**，余下 2 项归模块 C。
  **✅ 2026-09-22 模块 C 收口后复核：`REQUIRE_INTEGRATION_DB=1 uv run pytest -q -rs` 2019 passed / 1 skipped（时序哨兵）/ 0 failed，上述 2 项已转绿，见文末「验证限制」**）

```powershell
cd backend; uv run pytest; uv run ruff check .; uv run mypy app
```

期望：不低于 1128 passed，**v1 零回归**。

---

### Task 5：默认模型名迁移

把退役兼容别名 `deepseek-v4-flash` 迁到 `deepseek-flash`（AGENTS.md R3）。

**文件：**

| 文件 | 位置 |
| --- | --- |
| `backend/app/core/config.py` | `llm_model` 默认值（约 55 行） |
| `.env.example` | `LLM_MODEL=`（约 8 行） |
| `backend/README.md` | 约 77、81、83 行 |
| `backend/tests/integration/test_migrations.py` | 142、193 行夹具 |
| `backend/tests/unit/llm/test_deepseek_client.py` | 170 行 |
| `backend/tests/unit/llm/test_guard.py` | 231 行 |
| `backend/tests/unit/services/test_localization_service.py` | 210、677 行 |

### 规则

- **只改默认值与夹具，不改历史记录**：`docs/project-progress.md` 里
  「2026-08-22 B7 九题验收（当时使用 `deepseek-v4-flash`）」和 2026-08 的
  `docs/specs/` 是历史事实，**保持原样**（R8 的同类原则：快照保留原样是正确状态）；
- `app/intent/service.py:197` 与 `tests/unit/intent/test_prompts.py:3` 的注释记录的是
  「2026-08-17/08-26 用某模型实测发现了什么」，属于历史观测记录，**不改**；
- 迁移后 `deepseek-chat`、`deepseek-reasoner`、`deepseek-v4-flash` 三个名字
  **不得出现在任何生效配置中**。

- [x] **步骤 1：写哨兵测试**

```python
def test_no_retired_model_in_live_config() -> None:
    from app.core.config import Settings
    assert Settings().llm_model == "deepseek-flash"


def test_env_example_uses_current_model() -> None:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[3] / ".env.example").read_text("utf-8")
    assert "LLM_MODEL=deepseek-flash" in text
    for retired in ("deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"):
        assert retired not in text
```

- [x] **步骤 2：确认失败 → 逐文件迁移 → 确认通过**

- [x] **步骤 3：确认历史记录未被误改**

```powershell
cd "d:/vscode html/merchant_assistant"
rg -n "deepseek-v4-flash" docs/ backend/app/intent/ backend/tests/unit/intent/
```

期望：**仍有命中**——那些是历史观测记录，改掉才是错的。逐条确认每一处都是
「当时用 X 实测发现 Y」这种叙述，而不是生效配置。

---

### Task 6：真实双协议冒烟测试 · **需 R3 单独授权**

> **本任务会产生真实费用。在用户明确同意前不得执行任何一步。**
> 前五个任务与 Task 7 都不依赖它——未获授权时按 PRD §15 N1 的规定，
> 该项标记为「待人工验收」，**不阻塞其余 N1 工作，但也不得宣称适配器已验证**。

**文件：** 创建 `backend/scripts/llm_smoke.py`（默认不被任何测试导入或执行）

- [x] **步骤 1：先写脚本，不运行**

脚本必须：

- 从环境变量读 `LLM_API_KEY`，未配置时立即退出并提示，**不得有任何硬编码回退**；
- 每种协议跑下表的固定用例，覆盖 PRD A1 要求验证的五项：流式、工具调用、结构化输出、
  错误分类、缓存计量；
- **每次调用前打印将要发生的调用**，并要求 `--yes` 显式确认才实际发出；
- 把结果写入 `docs/history/llm-smoke-<date>.md`：协议、模型名、思考模式、调用次数、
  token 数与缓存字段原值、每个用例的通过 / 失败与原因；
- **不打印或记录 API Key**，不记录完整请求体。

| # | 用例 | 调用次数 | 验证什么 |
| --- | --- | --- | --- |
| 1 | 普通问答 | 1 | 基本通路、用量字段 |
| 2 | 结构化 JSON 输出 | 1 | 输出可被 Pydantic 校验 |
| 3 | 单工具调用 | 1 | `tool_calls` / `tool_use` 映射 |
| 4 | 多工具并行 | 1 | 一次返回多个调用 |
| 5 | **多轮工具历史** | 2 | 第 1 轮拿到工具调用 → 回填工具结果与推理内容 → 第 2 轮成功；分别在 `LLM_THINKING=disabled` 下跑，若用户另行授权再在 `enabled` 下加跑 |
| 6 | **流式文本** | 1 | 增量拼接等于最终文本；是否返回用量 |
| 7 | **流式工具调用** | 1 | 参数分片拼接后可解析 |
| 8 | **缓存计量** | 2 | 两次请求共享同一段 ≥ 1024 token 的前缀，记录第二次的缓存字段原值；Anthropic 接口若不上报，记为"未上报"而不是 0 |
| 9 | 错误分类：认证失败 | 1 | 故意使用错误 Key，映射为既有 `LlmFailureKind`（不消耗 token） |
| 10 | 错误分类：非法请求 | 1 | 发送一条 `tool_call_id` 不存在的工具结果消息，期望 400 并可映射 |

每种协议 12 次，合计 24 次。**不用"非法模型名"做错误用例**：官方文档说明 Anthropic 兼容接口会把
不支持的模型名自动映射到 `deepseek-flash`，那条用例不会报错，只会悄悄调用默认模型并计费。
用例 10 的期望行为也是依据文档推断，若实测没有报错，如实记录并换一个确定会被拒绝的受控请求，
**不得把"没报错"记为"错误分类可映射"**。

- [x] **步骤 2：按 R3 提交审批请求**

在执行前向用户说明，**四项缺一不可**：

```text
接口：DeepSeek OpenAI 兼容 /chat/completions 与 Anthropic 兼容 /anthropic/v1/messages
模型：deepseek-flash；思考模式 disabled（enabled 加跑需另行说明次数）
次数：每种协议 12 次，合计 24 次（其中 2 次认证失败不计费），单次输出上限 512 token，
      最大单次输入约 2,000 token（缓存用例）
费用：按提交当天官方价格表计算后填入实际数字——预计 ¥__；上限 ¥__
```

费用两处**必须填实际数字**，不得保留下划线；价格表链接与查阅日期一并写明。

**取得明确同意后才能进行步骤 3。** 授权范围限于本次声明的接口、模型、思考模式与次数；
换模型、打开思考模式、加次数或扩大范围须重新取得同意。

- [x] **步骤 3：执行并记录**

```powershell
cd backend; uv run python -m scripts.llm_smoke --protocol openai --yes
cd backend; uv run python -m scripts.llm_smoke --protocol anthropic --yes
```

- [x] **步骤 4：据结果选定生产默认适配器**

把结论写入 `docs/backend-development-plan.md` §6.17，并据此决定 `LLM_PROTOCOL` 默认值。
**结论必须基于实测数据**，不得凭文档推断——PRD §16 风险表第 1 行明确写着
"DeepSeek 对蓝图式工具调用与结构化输出的适配程度未经实测"。

---

### Task 7：契约补写与自检

- [x] **步骤 1：在 `docs/backend-development-plan.md` 新增 §6.17 Model Client**

按 §6.1 的 `输入 / 输出 / 规则 / 必测` 体例写模块契约，含两种协议的差异表。
**放在 §6.16 之后、§7 之前，不改动 §7 及以后的编号。**

- [x] **步骤 2：零费用确认**

```powershell
cd backend
rg -n "api.deepseek.com" tests/
```

期望：**只在 `recording_transport()` 断言的 URL 常量里出现**，所有适配器测试都注入了
`httpx.MockTransport`，无任何真实出站调用。

```powershell
rg -n "respx" tests/ app/ pyproject.toml
```

期望：**零命中**——本计划不引入该依赖。

```powershell
rg -n "llm_smoke" tests/ app/
```

期望：**零命中**——冒烟脚本不得被任何测试或生产代码导入（R3：真实调用不加入默认测试套件）。

- [x] **步骤 3：全量回归**（2026-09-22：`REQUIRE_INTEGRATION_DB=1 uv run pytest` **1930 passed / 2 failed / 0 errors**，2 个失败均为模块 C 新增用例——`test_n1_c_core_migrations::test_product_stock_is_derived_and_cannot_oversell`（`ck_products_reserved_le_on_hand`）与 `test_demo_determinism::test_three_merchant_seed_is_repeatable_in_postgres`，与本模块无关；v1 零回归；`ruff check .` 与 `mypy app` 全部通过。当时**全量并非全绿**，余下 2 项归模块 C。
  **✅ 2026-09-22 模块 C 收口后复核：`REQUIRE_INTEGRATION_DB=1 uv run pytest -q -rs` 2019 passed / 1 skipped（时序哨兵）/ 0 failed，上述 2 项已转绿，见文末「验证限制」**）

```powershell
cd backend; uv run pytest; uv run ruff check .; uv run mypy app
```

- [x] **步骤 4：更新进度快照**

在 `docs/project-progress.md` 记录：协议扩展与两个适配器的完成情况、
**Task 6 是否已授权执行**（未授权则明确写「待人工验收，适配器未经真实验证；流式、多轮工具历史、
缓存计量均只有 mock 证据」）、
未执行 Git 操作。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 工具调用循环本身 | N2（§6.10）；本计划只提供 `converse()` 这个上游能力 |
| 流式（SSE）输出 | v2 Chat 路由实现任务；`converse()` 先做非流式 |
| 提示词缓存与稳定前缀（A9） | N3 |
| 三级预算与成本看板 | N5 |
| 选定生产适配器 | Task 6 授权执行后才有依据 |

---

## 执行期记录（2026-09-22）

**进度：25 / 25。** 全部步骤已勾选（2026-09-22）。两步「全量回归」在 Docker 恢复后重跑：1930 passed / 2 failed，
2 个失败均属模块 C，见各步勾选处的说明。**✅ 2026-09-22 模块 C 收口后复核，两处全量回归已转绿**
（`REQUIRE_INTEGRATION_DB=1 uv run pytest -q -rs` 2019 passed / 1 skipped / 0 failed，`ruff`/`mypy` 全绿），
本模块被 C 阻塞的验收条件已解除。另按
`plans/2026-09-22-astra-checklist.md`，B1–B3【必审】、B4【抽审】尚待 Astra 审查——
这是本模块当前**唯一**剩余的收尾项，不再受模块 C 阻塞。

**追加真实调用（R3 追加授权，2026-09-22）：** 用户授权 6 次：Anthropic 原始 `usage` 诊断 2 次（一次性脚本，未入库，
只打印 `usage` 对象）、`--thinking enabled` 多轮工具历史每协议 2 次。**实际 6 / 6 次，未超范围**；本模块真实调用累计 30 次，
估算约 $0.004。结果：Anthropic 的 `input_tokens` 不含缓存命中部分（证实，已修复，见 B11）；两协议在思考模式下都拿到
推理内容并原样回放成功。

**第三次授权（2026-09-22，12 次，实际 12 / 12）：** `--suite extended`（思考 `enabled`，单次输出上限 1024，授权时已声明），
OpenAI 5 次、Anthropic 7 次；累计 42 次，估算约 $0.006。结果见 B14–B15 与后端计划 §6.17。

**R3 授权与执行（Task 6，2026-09-22）：** 用户在看过「每协议 12 次、合计 24 次、`deepseek-flash`、思考 `disabled`」的说明后明确授权；
执行前补足费用数字——价格表取自 `https://api-docs.deepseek.com/quick_start/pricing`（2026-09-22 查阅，页面无发布日期，
USD / 百万 token；`deepseek-flash` 输入未命中 $0.15（高峰 $0.30）、命中 $0.003（高峰 $0.006）、输出 $0.60（高峰 $1.20）），
按高峰价与全部未命中估算约 $0.02，上限 $0.05。**实际执行 24 / 24 次，未超范围，未跑思考模式 `enabled`**；
按报告里的真实 token 数估算约 $0.003（估算值，非平台账单）。用一次性环境变量 `LLM_MODEL=deepseek-flash` 覆盖
本地 `.env` 里的退役别名，**未修改用户的 `.env`**。结果与结论见后端计划 §6.17「真实冒烟实测」与
`docs/history/llm-smoke-2026-09-22.md`：**两协议功能全部通过，`LLM_PROTOCOL` 默认保持 `openai`。**

以下是**计划文字没写、由执行者裁定**的事项，可被用户推翻：

| # | 事项 | 裁定与理由 |
| --- | --- | --- |
| B1 | Task 1 写「扩展 `LlmClient` 协议」 | **`LlmClient` 本身不加方法**，新增子协议 `ConversationalLlmClient(LlmClient)` 承载 `converse` / `converse_stream`。`LlmCostGuard` 等 v1 实现按结构满足 `LlmClient`，直接给它加方法会让它们与所有传入它们的调用点在 mypy 下集体失格；改 guard 属于 N5 三级预算，不在本计划内。仍是「只增不改」，v1 零风险；已用 mypy 验证 `DeepSeekLlmClient` / `FakeLlmClient` 满足子协议、`LlmCostGuard` 仍满足 `LlmClient`（一次性检查文件，未入库） |
| B2 | 计划文件表没有 `adapter_support.py` | 新增 `backend/app/llm/adapter_support.py`：两适配器**完全相同**的预算先扣后发、失败分类、用量解析、SSE 行解析放这里，避免两份复制；随协议而异的留在各自适配器 |
| B3 | Task 4 的配置字段被 Task 2/3 依赖 | 适配器读 `settings.llm_thinking`，故 `LLM_PROTOCOL` / `LLM_THINKING` 两个配置字段在 Task 2 之前先落地（先写测试）；任务内容不变，只是顺序前移 |
| B4 | `LLM_THINKING` 与 `LlmCallOptions.thinking` 的关系计划没写 | `LLM_THINKING` 是**上限**：两者都为 `enabled` 才开启，单次调用只能收紧、不能越过配置放开。已有 `LlmCallOptions.thinking` 默认 `enabled`，若以调用方为准，默认就会与「配置默认 disabled」冲突 |
| B5 | 计划的 `settings` fixture 不存在 | 新增 `tests/unit/llm/conftest.py`（`settings` fixture）与 `_transport.py` 里的 `make_settings()` |
| B6 | Task 5 哨兵要求 `.env.example` **全文**不含 `deepseek-v4-flash`，与「历史观测记录不改」冲突 | `.env.example` 第 41 行注释「按 2026-08-17 真实 deepseek-v4-flash 实测（每题约 6000 token）」是历史事实。哨兵改为只检查**非注释行**（生效配置），该注释与 `config.py` 里同类注释保持原样。计划里 `parents[3]` 也不对（应为 `parents[4]`），已更正 |
| B7 | Task 5 文件表漏了根目录 `README.md`、`README.en.md` 与 `docs/deployment.md` | 二者有生效的 `LLM_MODEL=deepseek-v4-flash` 示例与「默认 `deepseek-v4-flash`」表述，同属「生效配置」，一并迁移并纳入哨兵；`deployment.md` 补 `LLM_PROTOCOL` / `LLM_THINKING` 两行并提示既有部署须手动改旧值 |
| B8 | 计划「不做」表写「流式（SSE）输出…`converse()` 先做非流式」 | 与正文冲突。理解为该行指**向客户端**输出 SSE（v2 Chat 路由的事），而 LLM 侧流式 `converse_stream()` 因 PRD A1 要求验证流式已实现并测试 |
| B9 | 后端计划没有 §6.16 | §6.17 仍按计划编号，插在 §6.15 之后、§7 之前；§6.16 留给模块 D（Session Identity） |
| B11 | 实测发现 Anthropic 用量口径与计划假设不同 | 计划写「`usage.input_tokens` + `output_tokens`」。实测原始 `usage` 中 `input_tokens` 只含未命中部分，命中在 `cache_read_input_tokens`、写入在 `cache_creation_input_tokens`。适配器改为三者相加计总输入，`cache_hit_tokens = cache_read_input_tokens`，写入归入未命中；先写 6 条红灯测试（数值取自真实响应）再修，另加变异检验 8 / 8 杀死 |
| B12 | 两个「日志不含 Key」用例在全量下失败、单独通过 | 根因：`migrations/env.py` 的 `fileConfig` 默认 `disable_existing_loggers=True`，任何用例触发 alembic 后已存在的 logger 被全局禁用。已复现并在 `tests/unit/llm/conftest.py` 加 autouse 夹具重置 `app.llm.*` logger（与 `test_prefilter_logging.py` 的既有做法一致）；不改迁移配置，那属于模块 C / 基础设施 |
| B13 | Astra 清单 B1 要求「每种协议一轮多个工具调用」的流式用例 | OpenAI 已有；Anthropic 补一条两个 `tool_use` 块输入分片**交错到达**、按 index 归并的用例 |
| B14 | 本计划正文多处写「思考模式下缺推理内容会直接 400」 | 实测 `deepseek-flash` 两协议省略推理内容都返回 200。正文是当时的规格，保持原文；代码、测试注释与 §6.17 已改为「文档要求回传，实测未被拒，仍回传以防上游收紧」。回放实现与断言请求体的测试不变 |
| B15 | 冒烟脚本扩展 | 新增 `--suite extended`（用例 11–15）；传输层包一层 `StatusRecordingTransport` 记录真实状态码与上游错误说明（`LlmFailureKind` 把 400 与 500 都折叠为 `HTTP_OTHER`，答不了「是否真的 400」）；报告的「实际发出」改为按传输层记录计数，不再按计划数。实测的 Anthropic 流式 `message_delta` 带**完整** usage，已补按真实事件构造的单测 |
| B10 | 冒烟脚本的安全边界 | 代码层强制而非只靠文档：默认（无 `--yes`）只展示计划、不联网；`--yes` 时校验 `LLM_BASE_URL` 与 `LLM_MODEL` 必须等于授权值，否则拒绝运行；总调用次数硬上限；`--thinking enabled` 只跑多轮用例（另行授权的加跑） |

### 验证结果

- `tests/unit/llm`：**227 passed**（基线 34，新增 193）；`tests/unit` 全量 **1522 passed**；mypy 对 `app/llm` 与 `config.py` 无报错；
  ruff 对本模块全部文件通过；
- **连真实 PostgreSQL 的 `tests/unit` + `tests/api`：1729 passed / 0 failed**（`REQUIRE_INTEGRATION_DB=1`）。这一范围会触发
  alembic，因此也证明 B12 的日志用例跑序问题已修复，且 v1 API 零回归；
- **变异检验 22 / 22 + 8 / 8 杀死**（后 8 个针对 B11 的缓存用量折算与 B13 的流式 index 归并；前 22 个逐个破坏：预算先扣后发、思考模式收紧、缓存 `None`、推理回放、跨协议拒绝、
  截断丢弃工具调用、断流判降级、Anthropic 用量相加与合并工具结果、协议开关、Fake 快照与脚本耗尽、数据类不变量）；
  变异脚本不入库，文件已逐个核对恢复；
- 冒烟脚本**离线演练**：用一个假的 DeepSeek 服务器（`MockTransport`）跑完 10 个用例，两协议各发出计划内的 12 次
  请求，报告不含 Key，缓存未上报记为「未上报」而非 0，畸形的围栏 JSON 如实记为 FAIL；零网络、零费用；
- 零费用自检：`api.deepseek.com` 在 `tests/` 里只出现在 `_transport.py` 的 URL 断言常量与一处文档字符串；
  `respx` 零命中；`llm_smoke` 在 `app/`、`tests/` 零命中。

### 验证限制（如实记录）

- **✅ 2026-09-22 已解除：全量回归现已转绿，阻塞方（模块 C）已自行收口。** 此前记录的「1852 passed / 54 failed /
  11 errors」「挂死」均是模块 C 迁移与种子代码尚未收口时的中间状态，**不是本模块引入的问题**，本模块文件当时即无改动、
  无报错。2026-09-22 在模块 C 完成收口后的工作树上重新独占测试库跑
  `REQUIRE_INTEGRATION_DB=1 uv run pytest -q -rs`：**2019 passed / 1 skipped（该 1 skip 是需要
  `REQUIRE_SECURITY_TIMING=1` 单独运行的时序哨兵，非本模块相关）/ 0 failed**；此前归咎于模块 C 的两个失败
  `test_n1_c_core_migrations.py::test_product_stock_is_derived_and_cannot_oversell` 与
  `test_demo_determinism.py::test_three_merchant_seed_is_repeatable_in_postgres` 单独复测与全量中均已通过；
  `uv run ruff check .` 与 `uv run mypy app`（165 个源文件）全绿。**本模块 Task 4 步骤 3、Task 7 步骤 3 的「全量回归」
  验收条件已满足**，此前标注的「全量并非全绿」不再成立；
- **思考模式已实测**：推理回放、省略推理内容（未被拒）、流式文本、流式工具调用、并行工具均有真实证据（两协议一致）；
  仍无真实样本的只有「推理耗尽 `max_tokens`」与「写入缓存非零」两种情形；
- **Anthropic 流式缓存字段已直接观察**：`message_start` 与 `message_delta` 都带完整 usage，适配器折算与 OpenAI 逐项相同。

### 遗留风险

- **`LlmCostGuard` 尚未包装 `converse*`**：每日全局预算熔断目前只挡 `complete()`。N2 工具循环接入 `converse()`
  之前必须补齐，否则 v2 路径会绕过每日预算——它是公开部署的上线前置条件（AGENTS.md 十一），属 N5 三级预算；
- **本地 `backend/.env`（已被 `.gitignore`）里仍是 `LLM_MODEL=deepseek-v4-flash`**：环境变量会覆盖新默认值，
  本地后端与冒烟脚本都会读到退役别名（冒烟脚本会因此**拒绝运行**）。这是用户私有文件，未改动，需手动改成
  `deepseek-flash`；Railway 上的 `LLM_MODEL` 变量同理，本会话无法查看。
