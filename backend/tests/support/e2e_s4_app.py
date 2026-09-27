"""S4 浏览器验收专用后端：真实业务与 PostgreSQL，商家 Chat 使用脚本化模型。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from fastapi import FastAPI

from app.api.routes.v2 import merchant_chat as merchant_chat_route
from app.core.config import AppEnvironment, Settings
from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmMessage,
    LlmToolCall,
    LlmTurn,
    ToolSchema,
)
from app.llm.fake import FakeLlmClient
from app.main import create_app

S4_MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000054a1")
S4_PRODUCT_ID = UUID("00000000-0000-0000-0000-0000000054b1")
S4_ORDER_ID = UUID("00000000-0000-0000-0000-0000000054c1")
S4_SHOP_SLUG = "borough-s4-e2e"
S4_BUYER_KEY = "s4-e2e-buyer"
S4_MERCHANT_TOKEN = "s4-e2e-merchant-token"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _call(name: str, **arguments: Any) -> LlmTurn:
    return LlmTurn(
        text="", tool_calls=[LlmToolCall(
            call_id=f"s4-{name}", tool_name=name,
            arguments_json=json.dumps(arguments, ensure_ascii=False),
        )], stop_reason="TOOL_USE", tokens=10,
    )


class ScriptedS4Llm(FakeLlmClient):
    async def converse(
        self, *, messages: list[LlmMessage], tools: list[ToolSchema], budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmTurn:
        self._turns = [self._next_turn(messages)]
        return await super().converse(
            messages=messages, tools=tools, budget=budget, options=options
        )

    @staticmethod
    def _next_turn(messages: Sequence[LlmMessage]) -> LlmTurn:
        last_user = max((i for i, item in enumerate(messages) if item.role == "user"), default=-1)
        if last_user < 0:
            return _answer("请说明需要处理的售后事项。")
        question = messages[last_user].content
        tool_results = sum(item.role == "tool" for item in messages[last_user + 1:])
        match = _UUID.search(question)
        if "起草" in question and match:
            if tool_results == 0:
                return _call("list_after_sales")
            if tool_results == 1:
                return _call(
                    "draft_after_sale_decision", after_sale_id=match.group(),
                    decision="APPROVE", reply_text="已受理，请按售后详情继续操作。",
                )
            return _answer("已起草售后处理决定和回复，请在审批页面核对后批准。")
        return _answer("请先查看售后队列。")


def _scripted_llm(*_args: Any, **_kwargs: Any) -> ScriptedS4Llm:
    return ScriptedS4Llm()


def build_settings(database_url: str) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url=database_url,
        frontend_origin="http://127.0.0.1:5276",
        shop_origin="http://127.0.0.1:3276",
        demo_deployment_mode=True,
        demo_merchant_tokens={S4_MERCHANT_TOKEN: S4_MERCHANT_ID},
        demo_customer_identities={S4_SHOP_SLUG: S4_BUYER_KEY},
        buyer_alias_secret="s4-e2e-alias-secret-not-for-production-0123456789",
        admin_token="s4-e2e-admin-token",
        rate_limit_per_minute=1000,
    )


def create_app_from_env() -> FastAPI:
    merchant_chat_route.build_guarded_llm = _scripted_llm  # type: ignore[assignment]
    return create_app(build_settings(os.environ["S4_E2E_DATABASE_URL"]))
