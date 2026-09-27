"""S1 浏览器验收的确定性后端入口（`n2-shop-nextjs-app` Task 8）。

只把「模型决定调哪个工具」固定成脚本；顾客工具注册表、四类闸门、购物车、结账占库、支付与
订单事件全部走真实代码与真实 PostgreSQL，因此浏览器验收不产生 LLM 调用或费用（R3）。

与 `e2e_s3_app` 同一套路：uvicorn `--factory` 启动，导入本模块没有副作用，替换
`build_guarded_llm` 只发生在专用进程里。
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from fastapi import FastAPI

from app.api.routes.v2 import shop_chat as shop_chat_route
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

S1_MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000051a1")
S1_SHOP_SLUG = "borough-s1-e2e"
S1_WOOL_ID = UUID("00000000-0000-0000-0000-0000000051b1")
S1_CASHMERE_ID = UUID("00000000-0000-0000-0000-0000000051b2")
S1_BUYER_KEY = "s1-e2e-buyer"
S1_SHOP_ORIGIN = "http://127.0.0.1:3275"
S1_FRONTEND_ORIGIN = "http://127.0.0.1:5275"

_COMPARE_TRIGGER = "围巾"


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _call(tool: str, call_id: str, **arguments: Any) -> LlmTurn:
    return LlmTurn(
        text="",
        tool_calls=[
            LlmToolCall(
                call_id=call_id,
                tool_name=tool,
                arguments_json=json.dumps(arguments, ensure_ascii=False),
            )
        ],
        stop_reason="TOOL_USE",
        tokens=10,
    )


def _latest_turn(messages: Sequence[LlmMessage]) -> tuple[str, int]:
    """最新一条用户消息，以及它之后已经回来的工具结果条数。"""

    last_user = max(
        (index for index, message in enumerate(messages) if message.role == "user"), default=-1
    )
    if last_user < 0:
        return "", 0
    tool_results = sum(1 for message in messages[last_user + 1 :] if message.role == "tool")
    return messages[last_user].content, tool_results


class ScriptedS1Llm(FakeLlmClient):
    """含「围巾」：检索 → 逐个看详情对比 → 加购羊绒款 → 作答；其余：普通问候。"""

    async def converse(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmTurn:
        self._turns = [self._next_turn(messages)]
        return await super().converse(
            messages=messages, tools=tools, budget=budget, options=options
        )

    @staticmethod
    def _next_turn(messages: Sequence[LlmMessage]) -> LlmTurn:
        text, tool_results = _latest_turn(messages)
        if _COMPARE_TRIGGER not in text:
            return _answer("你好，我可以帮你在本店挑选商品。")
        script: tuple[tuple[str, str, dict[str, Any]], ...] = (
            ("search_products", "s1-search", {"query": "围巾"}),
            ("get_product", "s1-wool", {"product_id": str(S1_WOOL_ID), "attributes": ["材质"]}),
            (
                "get_product",
                "s1-cashmere",
                {"product_id": str(S1_CASHMERE_ID), "attributes": ["材质"]},
            ),
            ("set_cart_item", "s1-cart", {"product_id": str(S1_CASHMERE_ID), "quantity": 1}),
        )
        if tool_results < len(script):
            tool, call_id, arguments = script[tool_results]
            return _call(tool, call_id, **arguments)
        return _answer(
            "羊毛款商家没有写材质，羊绒款是 100% 羊绒；已把羊绒围巾加入购物车，"
            "请在页面上确认并提交订单。"
        )


def _scripted_llm(*_args: Any, **_kwargs: Any) -> ScriptedS1Llm:
    return ScriptedS1Llm()


def build_settings(database_url: str) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url=database_url,
        frontend_origin=S1_FRONTEND_ORIGIN,
        shop_origin=S1_SHOP_ORIGIN,
        demo_deployment_mode=True,
        demo_customer_identities={S1_SHOP_SLUG: S1_BUYER_KEY},
        buyer_alias_secret="s1-e2e-alias-secret-not-for-production-0123456789",
        admin_token="s1-e2e-admin-token",
        rate_limit_per_minute=1000,
    )


def create_app_from_env() -> FastAPI:
    """uvicorn `--factory` 入口；只在 S1 验收的专用后端进程里调用。"""

    shop_chat_route.build_guarded_llm = _scripted_llm  # type: ignore[assignment,attr-defined]
    return create_app(build_settings(os.environ["S1_E2E_DATABASE_URL"]))
