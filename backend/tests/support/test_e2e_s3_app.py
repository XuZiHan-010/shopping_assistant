"""S3 浏览器验收入口的脚本化模型（`n2-merchant-vue-v2-migration` Task 7）。

脚本本身的错误如果留到浏览器里才暴露，排查要跨三个进程；这里先把它钉住。
"""

from __future__ import annotations

import importlib
import json
import sys

import pytest
from pytest import MonkeyPatch

from app.llm.client import LlmBudget, LlmMessage, LlmToolCall, LlmTurn

S3_DB = "postgresql+psycopg://borough:borough_local@127.0.0.1:55451/borough_s3_e2e_test"


def _module(monkeypatch: MonkeyPatch):  # type: ignore[no-untyped-def]
    from app.api.routes.v2 import merchant_chat

    # 工厂会替换路由模块里的 `build_guarded_llm`；先快照原值，用例结束由 monkeypatch 还原，
    # 否则替换会泄漏给同进程里模块 C 的商家 Chat 集成测试。
    monkeypatch.setattr(merchant_chat, "build_guarded_llm", merchant_chat.build_guarded_llm)
    sys.modules.pop("tests.support.e2e_s3_app", None)
    return importlib.import_module("tests.support.e2e_s3_app")


def test_importing_the_module_has_no_side_effects(monkeypatch: MonkeyPatch) -> None:
    from app.api.routes.v2 import merchant_chat

    original = merchant_chat.build_guarded_llm
    _module(monkeypatch)

    assert merchant_chat.build_guarded_llm is original


def _user(text: str) -> LlmMessage:
    return LlmMessage(role="user", content=text)


def _assistant_call(call_id: str, tool: str) -> LlmMessage:
    return LlmMessage(
        role="assistant",
        content="",
        tool_calls=[LlmToolCall(call_id=call_id, tool_name=tool, arguments_json="{}")],
    )


def _tool(call_id: str) -> LlmMessage:
    return LlmMessage(role="tool", content="{}", tool_call_id=call_id)


async def _turn(llm: object, messages: list[LlmMessage]) -> LlmTurn:
    return await llm.converse(  # type: ignore[attr-defined, no-any-return]
        messages=messages, tools=[], budget=LlmBudget(max_calls=10, max_tokens=100_000)
    )


@pytest.mark.asyncio
async def test_draft_request_queries_inventory_alerts_first(monkeypatch: MonkeyPatch) -> None:
    """`draft_restock` 有来源闸门：商品必须先由 `get_inventory_alerts` 产出，所以脚本先查告警。"""

    mod = _module(monkeypatch)

    turn = await _turn(mod.ScriptedS3Llm(), [_user("给 S3 验收商品起草补货")])

    assert [call.tool_name for call in turn.tool_calls] == ["get_inventory_alerts"]


@pytest.mark.asyncio
async def test_draft_request_then_drafts_restock_for_seeded_product(
    monkeypatch: MonkeyPatch,
) -> None:
    mod = _module(monkeypatch)
    messages = [
        _user("给 S3 验收商品起草补货"),
        _assistant_call("c1", "get_inventory_alerts"),
        _tool("c1"),
    ]

    turn = await _turn(mod.ScriptedS3Llm(), messages)

    assert [call.tool_name for call in turn.tool_calls] == ["draft_restock"]
    assert json.loads(turn.tool_calls[0].arguments_json) == {
        "product_id": str(mod.S3_PRODUCT_ID),
        "delta": mod.S3_RESTOCK_DELTA,
    }


@pytest.mark.asyncio
async def test_draft_request_answers_after_both_tools(monkeypatch: MonkeyPatch) -> None:
    mod = _module(monkeypatch)
    messages = [
        _user("给 S3 验收商品起草补货"),
        _assistant_call("c1", "get_inventory_alerts"),
        _tool("c1"),
        _assistant_call("c2", "draft_restock"),
        _tool("c2"),
    ]

    turn = await _turn(mod.ScriptedS3Llm(), messages)

    assert turn.tool_calls == []
    assert turn.stop_reason == "END_TURN"


@pytest.mark.asyncio
async def test_approval_request_only_claims_approval_without_any_tool(
    monkeypatch: MonkeyPatch,
) -> None:
    """反例的关键：模型自称「已批准」，但没有、也不可能调用任何写工具。"""

    mod = _module(monkeypatch)

    turn = await _turn(mod.ScriptedS3Llm(), [_user("批准那个补货")])

    assert turn.tool_calls == []
    assert "已为你批准" in (turn.text or "")


@pytest.mark.asyncio
async def test_tool_results_before_latest_user_message_are_ignored(
    monkeypatch: MonkeyPatch,
) -> None:
    """同一对话里上一轮的工具结果不能让新一轮跳过「先查告警」。"""

    mod = _module(monkeypatch)
    messages = [
        _user("给 S3 验收商品起草补货"),
        _assistant_call("c1", "get_inventory_alerts"),
        _tool("c1"),
        _user("再起草一次补货"),
    ]

    turn = await _turn(mod.ScriptedS3Llm(), messages)

    assert [call.tool_name for call in turn.tool_calls] == ["get_inventory_alerts"]


def test_s3_app_routes_merchant_chat_to_scripted_llm(monkeypatch: MonkeyPatch) -> None:
    mod = _module(monkeypatch)
    from app.api.routes.v2 import merchant_chat

    monkeypatch.setenv("S3_E2E_DATABASE_URL", S3_DB)
    mod.create_app_from_env()

    llm = merchant_chat.build_guarded_llm(
        None, None, request_id="r", merchant_id=mod.S3_MERCHANT_ID
    )
    assert isinstance(llm, mod.ScriptedS3Llm)
