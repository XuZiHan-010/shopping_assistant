"""适配器测试的共用夹具：记录请求、按序回放 JSON 或 SSE 响应。

全部走 ``httpx.MockTransport``，不发出任何真实请求、不产生费用（R3）。
本模块里的 URL 常量是测试对适配器**应当访问哪里**的断言，不会被真实访问。
"""

from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.llm.client import LlmBudget, LlmMessage, ToolSchema

OPENAI_URL = "https://api.deepseek.com/chat/completions"
ANTHROPIC_URL = "https://api.deepseek.com/anthropic/v1/messages"

SEARCH_TOOL = ToolSchema(
    name="search",
    description="搜索商品",
    parameters={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "frontend_origin": "http://localhost:5173",
        "llm_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def budget(max_calls: int = 5, max_tokens: int = 1_000) -> LlmBudget:
    return LlmBudget(max_calls=max_calls, max_tokens=max_tokens)


def hello() -> list[LlmMessage]:
    return [LlmMessage(role="user", content="你好")]


def recording_transport(
    *responses: httpx.Response | Exception,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """按序回放响应并记录请求；响应用完仍被调用即测试失败。

    队列里放异常实例时，对应那次请求会抛出它，用来模拟超时与网络故障。
    """

    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert queue, f"意外的第 {len(seen)} 次请求：{request.url}"
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler), seen


def sse(*events: str) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(f"{e}\n\n" for e in events).encode(),
    )


def request_body(request: httpx.Request) -> dict[str, object]:
    body = json.loads(request.content)
    assert isinstance(body, dict)
    return body
