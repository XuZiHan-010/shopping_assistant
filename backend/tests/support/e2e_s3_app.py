"""S3 浏览器验收的确定性后端入口（`n2-merchant-vue-v2-migration` Task 7）。

只把「模型决定调哪个工具」固定成脚本；工具注册表、四类闸门（含 `draft_restock` 的来源闸门）、
草稿、审批证据、应用事务、库存告警与最小简报全部走真实代码与真实 PostgreSQL。
因此浏览器验收不产生 LLM 调用或费用（R3）。

用 uvicorn 的 `--factory` 启动（`create_app_from_env`），导入本模块本身没有副作用——
替换 `build_guarded_llm` 只发生在工厂被调用的那个专用进程里。
"""

from __future__ import annotations

import json
import os
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

S3_MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000053a1")
S3_MERCHANT_TOKEN = "s3-e2e-merchant-token"
S3_PRODUCT_ID = UUID("00000000-0000-0000-0000-0000000053b1")
S3_PRODUCT_TITLE = "S3 验收商品"
S3_RESTOCK_DELTA = 60
S3_FRONTEND_ORIGIN = "http://127.0.0.1:5275"

_DRAFT_TRIGGER = "起草"
_APPROVE_TRIGGER = "批准"


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


class ScriptedS3Llm(FakeLlmClient):
    """按最新一条用户消息决定下一步的替身模型。

    - 含「起草」：先 `get_inventory_alerts`（来源闸门要求商品由它产出），再
      `draft_restock` 种子商品，最后作答；
    - 含「批准」：**只**口头声称已批准，不调任何工具——反例要证明这句话没有效果；
    - 其余：普通问候。
    """

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
        if _DRAFT_TRIGGER in text:
            if tool_results == 0:
                return _call("get_inventory_alerts", "s3-alerts")
            if tool_results == 1:
                return _call(
                    "draft_restock",
                    "s3-restock",
                    product_id=str(S3_PRODUCT_ID),
                    delta=S3_RESTOCK_DELTA,
                )
            return _answer("已为你起草补货草稿，请到审批界面核对后批准。")
        if _APPROVE_TRIGGER in text:
            return _answer("好的，已为你批准并应用。")
        return _answer("你好，我可以帮你看库存和起草补货。")


def _scripted_llm(*_args: Any, **_kwargs: Any) -> ScriptedS3Llm:
    return ScriptedS3Llm()


def build_settings(database_url: str) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url=database_url,
        frontend_origin=S3_FRONTEND_ORIGIN,
        demo_merchant_tokens={S3_MERCHANT_TOKEN: S3_MERCHANT_ID},
        admin_token="s3-e2e-admin-token",
        rate_limit_per_minute=1000,
    )


def create_app_from_env() -> FastAPI:
    """uvicorn `--factory` 入口；只在 S3 验收的专用后端进程里调用。"""

    merchant_chat_route.build_guarded_llm = _scripted_llm  # type: ignore[assignment]
    return create_app(build_settings(os.environ["S3_E2E_DATABASE_URL"]))
