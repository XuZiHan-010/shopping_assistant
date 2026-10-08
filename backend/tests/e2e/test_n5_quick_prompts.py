"""顾客端首页六条快捷提问的工具路径（N5 E Task 3 步骤 3；PRD C1，D-N5-4）——全程脚本化 Fake LLM。

证明的是**路径**：每条提问对应的 Skill 能加载、预期工具可调用、闸门不误拒，回合以 200 结束，
而且用到的商品与规则确实存在于演示数据里（文案里的商品名取自 `app.analytics.demo_data`，
规则取自真实的知识库种子）。模型会不会自己选对工具、回答质量如何属于真实模型评测（R3），
不在这里验证。

文案与 `shop/src/i18n/messages.ts` 逐字核对：那边改了文案而这里没跟上，第一个用例就会失败。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.analytics.demo_data import _DEMO_PRODUCTS
from app.knowledge.wiki_seed import seed_wiki_documents
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.services.v2.shop_chat import GUEST_SESSION_NOTE
from tests.conftest import MERCHANT_ONE_ID
from tests.support.merchant_v2 import seed_product
from tests.support.trade import SHOP, bound_customer, database_of, set_product

pytestmark = pytest.mark.integration

JSON = {"Accept": "application/json"}
CHAT = "/api/v2/shop/chat"

QUICK = {
    "search-discovery": "想找一双通勤穿的鞋，预算 500 元以内，有推荐吗？",
    "purchase-research": "羊毛混纺高领毛衣和美利奴羊毛针织开衫有什么区别，怎么选？",
    "planning-goals": "预算 1000 元，帮我搭一套秋天周末出门的穿搭",
    "after-sales-service": "收到的商品不合适，想申请退货，该怎么操作？",
    "memory-personalization": "记住：我穿 M 码，不喜欢太亮的颜色",
    "platform-rules": "平台的退货退款要经过哪些环节？请注明规则出处",
}

_CATALOG = {product.title: product for product in _DEMO_PRODUCTS}


def _call(call_id: str, tool: str, **arguments: Any) -> LlmTurn:
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


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _script(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> FakeLlmClient:
    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(
        "app.api.routes.v2.shop_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    return fake


async def _guest(client: AsyncClient) -> dict[str, str]:
    created = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert created.status_code == 201, created.text
    return {"X-Session-Id": created.json()["session_id"]}


async def _ask(client: AsyncClient, headers: dict[str, str], message: str, crid: str) -> Any:
    response = await client.post(
        CHAT, json={"client_request_id": crid, "message": message}, headers={**headers, **JSON}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _seed(app: FastAPI, *titles: str) -> dict[str, str]:
    """把演示目录里的真实商品（名称、价格、描述）灌进测试店铺，返回名称 → 商品 ID。"""

    database = database_of(app)
    ids: dict[str, str] = {}
    for title in titles:
        demo = _CATALOG[title]
        product_id = await seed_product(database, MERCHANT_ONE_ID, title=title, on_hand=20)
        await set_product(
            database,
            product_id,
            price=Decimal(demo.price),
            short_description=demo.description,
            attributes={"材质": {"value": demo.material_or_benefit, "source": "MERCHANT"}},
        )
        ids[title] = str(product_id)
    return ids


def _tools(body: dict[str, Any]) -> list[str]:
    return [call["tool_name"] for call in body["tool_calls"]]


def _tool_messages(fake: FakeLlmClient) -> list[str]:
    return [m.content for m in fake.converse_calls[-1].messages if m.role == "tool"]


def _tool_text(fake: FakeLlmClient) -> str:
    return "\n".join(_tool_messages(fake))


def _assert_no_tool_was_refused(fake: FakeLlmClient, expected: int) -> None:
    """模型看到的每条工具结果都是成功：受信 Skill 正文，或 `ok: true` 的工具结果（闸门未误拒）。

    最终响应里的 `tool_calls` 只是「调用开始」的展示项，不带结果状态，所以看模型实际收到的内容。
    """

    messages = _tool_messages(fake)
    assert len(messages) == expected
    for message in messages:
        assert message.startswith("<skill") or '"ok": true' in message, message[:200]


def test_prompts_match_the_storefront_copy_and_name_real_demo_products() -> None:
    messages = (
        Path(__file__).resolve().parents[3] / "shop" / "src" / "i18n" / "messages.ts"
    ).read_text(encoding="utf-8")
    for text in QUICK.values():
        assert f"'{text}'" in messages, f"顾客端首页没有这条快捷提问：{text}"
    # 对比类提问点名的两件商品必须真在演示目录里，否则演示时只会得到「没有找到」。
    for title in ("羊毛混纺高领毛衣", "美利奴羊毛针织开衫"):
        assert title in _CATALOG and title in QUICK["purchase-research"]
    # 「通勤鞋、500 元以内」在演示目录里至少有两件可推荐。
    affordable_shoes = [p for p in _DEMO_PRODUCTS if "鞋" in p.title and p.price <= 500]
    assert len(affordable_shoes) >= 2


@pytest.mark.asyncio
async def test_search_discovery_prompt_finds_demo_shoes(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(postgres_app, "软底乐福鞋", "复古德训运动鞋", "手工缝线切尔西靴")
    fake = _script(
        monkeypatch,
        [
            _call("c1", "load_skill", name="search-discovery"),
            _call("c2", "search_products", query="鞋"),
            _answer("软底乐福鞋和复古德训运动鞋都在预算内，适合通勤。"),
        ],
    )

    body = await _ask(
        postgres_client, await _guest(postgres_client), QUICK["search-discovery"], "quick-1"
    )

    assert _tools(body) == ["load_skill", "search_products"]
    _assert_no_tool_was_refused(fake, 2)
    seen = _tool_text(fake)
    assert "软底乐福鞋" in seen and "复古德训运动鞋" in seen
    assert body["degraded"] is False


@pytest.mark.asyncio
async def test_purchase_research_prompt_compares_the_two_named_products(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await _seed(postgres_app, "羊毛混纺高领毛衣", "美利奴羊毛针织开衫")
    fake = _script(
        monkeypatch,
        [
            _call("c1", "load_skill", name="purchase-research"),
            _call("c2", "search_products", query="羊毛"),
            _call("c3", "get_product", product_id=ids["羊毛混纺高领毛衣"], attributes=["材质"]),
            _call("c4", "get_product", product_id=ids["美利奴羊毛针织开衫"], attributes=["材质"]),
            _answer("高领毛衣是羊毛混纺、贴身穿；针织开衫是纯美利奴羊毛、适合外搭。"),
        ],
    )

    body = await _ask(
        postgres_client, await _guest(postgres_client), QUICK["purchase-research"], "quick-2"
    )

    assert _tools(body) == ["load_skill", "search_products", "get_product", "get_product"]
    _assert_no_tool_was_refused(fake, 4)
    seen = _tool_text(fake)
    assert "70% 羊毛 30% 锦纶" in seen and "100% 美利奴羊毛" in seen


@pytest.mark.asyncio
async def test_planning_goals_prompt_assembles_an_outfit_from_demo_products(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(postgres_app, "水洗帆布工装夹克", "高腰直筒牛仔裤", "复古德训运动鞋")
    fake = _script(
        monkeypatch,
        [
            _call("c1", "load_skill", name="planning-goals"),
            _call("c2", "search_products", query="夹克"),
            _call("c3", "search_products", query="牛仔裤"),
            _call("c4", "search_products", query="运动鞋"),
            _answer("可以用工装夹克配直筒牛仔裤和德训鞋，三件加起来在预算内。"),
        ],
    )

    body = await _ask(
        postgres_client, await _guest(postgres_client), QUICK["planning-goals"], "quick-3"
    )

    assert _tools(body) == ["load_skill", "search_products", "search_products", "search_products"]
    _assert_no_tool_was_refused(fake, 4)
    assert body["degraded"] is False


@pytest.mark.asyncio
async def test_after_sales_prompt_guides_a_guest_instead_of_failing(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """访客没有订单：得到「先绑定演示顾客」的正常引导与通用退货步骤，而不是 403。"""

    await seed_wiki_documents(database_of(postgres_app))
    fake = _script(
        monkeypatch,
        [
            _call("c1", "load_skill", name="after-sales-service"),
            _call("c2", "get_shop_policy", topic="RETURN_REFUND"),
            _answer("申请退货需要先在页面上绑定演示顾客；流程是发起申请、商家审核、寄回、验收、退款。"),
        ],
    )

    body = await _ask(
        postgres_client, await _guest(postgres_client), QUICK["after-sales-service"], "quick-4"
    )

    assert _tools(body) == ["load_skill", "get_shop_policy"]
    _assert_no_tool_was_refused(fake, 2)
    system = "\n".join(m.content for m in fake.converse_calls[0].messages if m.role == "system")
    assert GUEST_SESSION_NOTE in system


@pytest.mark.asyncio
async def test_after_sales_prompt_for_a_bound_customer_has_no_guest_note(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_wiki_documents(database_of(postgres_app))
    fake = _script(
        monkeypatch,
        [
            _call("c1", "load_skill", name="after-sales-service"),
            _call("c2", "get_shop_policy", topic="RETURN_REFUND"),
            _answer("请告诉我是哪一笔订单，我先帮你核对是否可以申请退货。"),
        ],
    )
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="quick-buyer")

    body = await _ask(postgres_client, headers, QUICK["after-sales-service"], "quick-4b")

    assert _tools(body) == ["load_skill", "get_shop_policy"]
    _assert_no_tool_was_refused(fake, 2)
    system = "\n".join(m.content for m in fake.converse_calls[0].messages if m.role == "system")
    assert GUEST_SESSION_NOTE not in system


@pytest.mark.asyncio
async def test_memory_prompt_reads_preferences_for_a_bound_customer(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _script(
        monkeypatch,
        [
            _call("c1", "load_skill", name="memory-personalization"),
            _call("c2", "recall_preferences", limit=5),
            _answer("好的，之后推荐会优先考虑这些偏好。"),
        ],
    )
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="quick-memory")

    body = await _ask(postgres_client, headers, QUICK["memory-personalization"], "quick-5")

    assert _tools(body) == ["load_skill", "recall_preferences"]
    _assert_no_tool_was_refused(fake, 2)


@pytest.mark.asyncio
async def test_memory_prompt_for_a_guest_is_a_normal_turn(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _script(
        monkeypatch,
        [
            _call("c1", "recall_preferences", limit=5),
            _answer("访客身份下无法保存偏好，请先在页面上绑定演示顾客。"),
        ],
    )

    body = await _ask(
        postgres_client, await _guest(postgres_client), QUICK["memory-personalization"], "quick-5g"
    )

    assert _tools(body) == ["recall_preferences"]
    _assert_no_tool_was_refused(fake, 1)


@pytest.mark.asyncio
async def test_platform_rule_prompt_cites_the_seeded_return_flow(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规则问答走真实知识库种子：退货流程文档可被顾客端引用，回答来源标为 KNOWLEDGE。"""

    await seed_wiki_documents(database_of(postgres_app))
    fake = _script(
        monkeypatch,
        [
            _call("c1", "get_shop_policy", topic="RETURN_REFUND"),
            _answer(
                "退货退款依次是：买家发起申请、商家审核、买家寄回、商家收货验收、平台打款退回"
                "（出处：业务/退货/业务流程/退货业务流程图.md）。"
            ),
        ],
    )

    body = await _ask(
        postgres_client, await _guest(postgres_client), QUICK["platform-rules"], "quick-6"
    )

    assert _tools(body) == ["get_shop_policy"]
    _assert_no_tool_was_refused(fake, 1)
    seen = _tool_text(fake)
    assert "买家发起退货或退款申请" in seen and "平台打款退回" in seen
    assert "业务/退货/业务流程/退货业务流程图.md" in seen
    assert body["analysis_sources"][0]["source"] == "KNOWLEDGE"
