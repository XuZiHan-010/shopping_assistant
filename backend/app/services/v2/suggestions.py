"""v2「猜你想问」候选（PRD M13，契约 §8.7.10）。

候选**全部由后端生成**，不由模型创造：每条问题标注回答它的工具，测试逐条核对该工具确实在当前角色的
工具面上——推荐一个 Agent 答不了的问题，用户一点就撞 INVALID（与 v1 `suggested_questions.py` 同理）。

顾客端只推荐现有四个顾客工具答得了的问题（找商品、比商品、看详情、查店铺规则、调购物车）。订单与售后问题
在 N2 由页面而不是对话回答，对话里没有对应工具，所以**不进候选**；N3 补上工具时再加。

模型只允许对候选重排，且必须仍落在本角色的候选集合里（`constrain_rewrite`），越界一律回退原候选。
N2 尚未把任何模型接到这里，避免每轮多一次 LLM 调用；文案是人工维护的固定词典，走本地词典而非 LLM。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from app.core.session import SessionRole
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import MAX_SUGGESTION_ALTERNATE_GROUPS
from app.schemas.v2.merchant_session import MerchantAnswerMode
from app.schemas.v2.shop_session import ShopAnswerMode


@dataclass(frozen=True)
class Suggestion:
    text: str
    text_en: str
    #: 回答这条问题所依赖的工具名；必须在对应角色的工具面上。
    tool: str

    def localized(self, locale: SupportedLocale) -> str:
        return self.text_en if locale is SupportedLocale.EN_US else self.text


@dataclass(frozen=True)
class SuggestionSet:
    current: list[str] = field(default_factory=list)
    alternates: list[list[str]] = field(default_factory=list)


Group = tuple[Suggestion, Suggestion, Suggestion]
Pools = tuple[Group, ...]

SHOP_ENTRY_POOLS: Final[Pools] = (
    (
        Suggestion(
            "帮我看看店里有什么热销商品",
            "What are the popular products in this shop?",
            "search_products",
        ),
        Suggestion(
            "有没有适合送人的商品？", "Do you have anything suitable as a gift?", "search_products"
        ),
        Suggestion(
            "这家店的退换货规则是什么？",
            "What is this shop's return and exchange policy?",
            "get_shop_policy",
        ),
    ),
    (
        Suggestion(
            "预算 200 元以内有什么推荐？",
            "What do you recommend under 200 yuan?",
            "search_products",
        ),
        Suggestion("这家店的运费怎么算？", "How is shipping calculated here?", "get_shop_policy"),
        Suggestion("可以开发票吗？", "Can I get an invoice?", "get_shop_policy"),
    ),
)

SHOP_FOLLOWUP_POOLS: Final[Pools] = (
    (
        Suggestion(
            "这两款商品有什么区别？",
            "What is the difference between these two products?",
            "get_product",
        ),
        Suggestion(
            "还有更便宜的类似商品吗？", "Is there a cheaper similar product?", "search_products"
        ),
        Suggestion("把这个商品加入购物车", "Add this product to my cart", "set_cart_item"),
    ),
    (
        Suggestion("这个商品现在有货吗？", "Is this product in stock right now?", "get_product"),
        Suggestion(
            "这款商品的详细参数是什么？", "What are this product's detailed specs?", "get_product"
        ),
        Suggestion(
            "把购物车里这个商品改成 2 件",
            "Change this item's quantity in my cart to 2",
            "set_cart_item",
        ),
    ),
    (
        Suggestion(
            "这个商品支持退换货吗？",
            "Can this product be returned or exchanged?",
            "get_shop_policy",
        ),
        Suggestion(
            "有类似风格的商品吗？", "Are there products in a similar style?", "search_products"
        ),
        Suggestion(
            "这家店的发票政策是什么？", "What is this shop's invoice policy?", "get_shop_policy"
        ),
    ),
)

MERCHANT_ENTRY_POOLS: Final[Pools] = (
    (
        Suggestion(
            "哪些商品库存偏低？", "Which products are running low on stock?", "get_inventory_alerts"
        ),
        Suggestion(
            "今天有哪些库存告警？", "What inventory alerts do I have today?", "get_inventory_alerts"
        ),
        Suggestion(
            "帮我为低库存商品起草补货", "Draft a restock for my low-stock products", "draft_restock"
        ),
    ),
    (
        Suggestion("有没有已经售罄的商品？", "Are any products sold out?", "get_inventory_alerts"),
        Suggestion(
            "哪些商品最需要优先补货？",
            "Which products most need restocking first?",
            "get_inventory_alerts",
        ),
        Suggestion(
            "生成一份补货草稿供我审批", "Create a restock draft for my approval", "draft_restock"
        ),
    ),
)

MERCHANT_FOLLOWUP_POOLS: Final[Pools] = (
    (
        Suggestion(
            "把这些告警商品各补货一批", "Restock each of these alerted products", "draft_restock"
        ),
        Suggestion(
            "还有哪些商品接近告警线？",
            "Which other products are close to the alert threshold?",
            "get_inventory_alerts",
        ),
        Suggestion(
            "查看当前的库存告警明细",
            "Show the current inventory alert details",
            "get_inventory_alerts",
        ),
    ),
    (
        Suggestion(
            "先只补货库存最低的那个商品",
            "Only restock the lowest-stock product for now",
            "draft_restock",
        ),
        Suggestion(
            "现在还有哪些告警没有处理？",
            "Which alerts are still unhandled?",
            "get_inventory_alerts",
        ),
        Suggestion(
            "重新检查一下最新库存告警",
            "Recheck the latest inventory alerts",
            "get_inventory_alerts",
        ),
    ),
)

_ROLE_POOLS: Final[dict[SessionRole, tuple[Pools, Pools]]] = {
    SessionRole.CUSTOMER: (SHOP_ENTRY_POOLS, SHOP_FOLLOWUP_POOLS),
    SessionRole.MERCHANT: (MERCHANT_ENTRY_POOLS, MERCHANT_FOLLOWUP_POOLS),
}


def _texts(group: Sequence[Suggestion], locale: SupportedLocale) -> list[str]:
    return [item.localized(locale) for item in group]


def _select(pools: Pools, locale: SupportedLocale) -> SuggestionSet:
    """当前组取池首，其余组供「换一换」；备选组不与当前组重复，数量受契约上限约束。"""

    current = _texts(pools[0], locale)
    alternates = [_texts(group, locale) for group in pools if _texts(group, locale) != current]
    return SuggestionSet(current=current, alternates=alternates[:MAX_SUGGESTION_ALTERNATE_GROUPS])


def shop_suggestions(mode: ShopAnswerMode, locale: SupportedLocale) -> SuggestionSet:
    """闲聊与拒答给入口问题；已经在导购的回合给追问。"""

    conversational = mode in {ShopAnswerMode.CHAT, ShopAnswerMode.INVALID}
    return _select(SHOP_ENTRY_POOLS if conversational else SHOP_FOLLOWUP_POOLS, locale)


def merchant_suggestions(mode: MerchantAnswerMode, locale: SupportedLocale) -> SuggestionSet:
    conversational = mode in {MerchantAnswerMode.CHAT, MerchantAnswerMode.INVALID}
    return _select(MERCHANT_ENTRY_POOLS if conversational else MERCHANT_FOLLOWUP_POOLS, locale)


def constrain_rewrite(
    role: SessionRole,
    candidates: Sequence[str],
    proposed: Sequence[str],
    locale: SupportedLocale,
) -> list[str]:
    """模型排序或改写后的结果必须仍是本角色候选集合里的问题，否则回退原候选。

    条数必须与原候选一致、互不重复；借用另一角色的问题、编造新问题都算越界。
    """

    allowed = {
        text for pools in _ROLE_POOLS[role] for group in pools for text in _texts(group, locale)
    }
    valid = (
        len(proposed) == len(candidates)
        and len(set(proposed)) == len(proposed)
        and all(text in allowed for text in proposed)
    )
    return list(proposed) if valid else list(candidates)
