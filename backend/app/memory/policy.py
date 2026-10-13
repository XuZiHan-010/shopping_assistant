"""受控偏好类别/键与长期性规则；不执行模型调用或身份解析。"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.core.session import SessionRole

_CUSTOMER = {
    "color": ("appearance", ("color", "colour", "颜色", "颜色偏好")),
    "style": ("appearance", ("style", "风格", "风格偏好")),
    "fit": ("sizing", ("fit", "版型", "版型偏好")),
    "size": ("sizing", ("size", "尺码", "尺寸", "尺码偏好")),
    "material": ("purchase", ("material", "材质", "面料")),
    "packaging": ("purchase", ("packaging", "包装", "礼品包装")),
    "fragrance": ("purchase", ("fragrance", "香型", "气味")),
    "durability": ("purchase", ("durability", "耐用性")),
    "maintenance": ("usage", ("maintenance", "护理", "机洗")),
    "availability": ("purchase", ("availability", "现货")),
    "habit": ("usage", ("habit", "习惯", "使用习惯")),
    "appliance": ("usage", ("appliance", "家电", "洗碗机")),
}
_MERCHANT = {
    "tone": ("presentation", ("tone", "语气", "回复语气")),
    "detail": ("presentation", ("detail", "detail_level", "详略", "回答详略")),
    "structure": ("presentation", ("structure", "format", "结构", "回答结构")),
    "language": ("presentation", ("language", "语言", "回答语言")),
}
_CATEGORIES = frozenset(
    {
        "preference",
        "appearance",
        "sizing",
        "purchase",
        "usage",
        "presentation",
        "tone",
        "偏好",
        "颜色",
        "尺码",
        "购物",
        "选购",
        "使用",
        "呈现",
        "语气",
        "运营",
    }
)
_TASK = re.compile(
    r"这次|本次|今天|今日|这回|送人|送礼|\b(?:this\s+(?:time|order|purchase)|today|for\s+this|gift)\b",
    re.IGNORECASE,
)
_STABLE = re.compile(
    r"平时|通常|一向|一直|长期|以后|今后|习惯|\b(?:usually|always|normally|from\s+now\s+on)\b",
    re.IGNORECASE,
)
_TRANSITION = re.compile(r"从今[天日起]+|\bfrom\s+today\s+(?:on|onward)\b", re.IGNORECASE)
_BOUNDARY = re.compile(r"[，。！？；,.!?;\n]+|但是|不过|但|\b(?:but|however)\b", re.IGNORECASE)
_BUSINESS_FACT = re.compile(
    r"(?:库存|营业额|销售额|成交额|利润|退款金额|赔付金额|佣金|价格|售价|预算|"
    r"\b(?:inventory|revenue|profit|price|budget|refund amount)\b).{0,30}"
    r"(?:\d|[一二三四五六七八九十百千万])|"
    r"\d+(?:\.\d+)?\s*(?:元|美元|USD|CNY|RMB|%)",
    re.IGNORECASE,
)
_STATE_OR_RULE = re.compile(
    r"店铺规则|平台规则|所有商品|均不支持退货|不退不换|"
    r"订单.{0,30}(?:已发货|已支付|已退款|已签收)|批准草稿|扣减库存|"
    r"\b(?:store policy|platform policy|order.{0,30}(?:shipped|paid|refunded)|approve draft)\b",
    re.IGNORECASE,
)
_PRESENTATION_VALUE = {
    "tone": re.compile(
        r"语气|正式|随和|礼貌|亲切|客气|友好|tone|formal|casual|polite|friendly", re.I
    ),
    "detail": re.compile(r"简短|简洁|详细|详尽|精简|展开|啰嗦|concise|brief|detailed|detail", re.I),
    "structure": re.compile(
        r"结论|明细|要点|列表|表格|分点|分段|段落|bullet|table|summary|conclusion|format", re.I
    ),
    "language": re.compile(r"中文|英文|汉语|英语|语言|Chinese|English|language", re.I),
}


def value_matches_preference(key: str, value: str, role: SessionRole) -> bool:
    if _STATE_OR_RULE.search(value):
        return False
    if role is SessionRole.MERCHANT:
        matcher = _PRESENTATION_VALUE.get(key)
        return matcher is not None and matcher.search(value) is not None
    return True


def canonical_identity(category: str, key: str, role: SessionRole) -> tuple[str, str] | None:
    category, key = category.strip().casefold(), key.strip().casefold()
    if category not in _CATEGORIES:
        return None
    # 旧商家抽取器用 tone/style 表示语气；只在这个明确类别下映射。
    if role is SessionRole.MERCHANT and category in {"tone", "语气"} and key == "style":
        key = "tone"
    registry = _CUSTOMER if role is SessionRole.CUSTOMER else _MERCHANT
    for canonical_key, (canonical_category, aliases) in registry.items():
        if key in aliases:
            return canonical_category, canonical_key
    return None


def is_long_term(
    value: str,
    evidence: str,
    source: str,
    *,
    supports: Callable[[str, str], bool],
) -> bool:
    """在完整原话恢复限定；临时语境跨逗号继承，明确的稳定分句可独立准入。"""
    if _BUSINESS_FACT.search(value):
        return False
    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(evidence), source)]
    task = False
    start = 0
    for end, next_start in [
        *((m.start(), m.end()) for m in _BOUNDARY.finditer(source)),
        (len(source), len(source)),
    ]:
        clause = source[start:end]
        if _TASK.search(_TRANSITION.sub("", clause)):
            task = True
        elif _STABLE.search(clause):
            task = False
        for left, right in spans:
            overlap = source[max(start, left) : min(end, right)]
            if overlap and not task and supports(value, overlap) and supports(value, clause):
                return True
        start = next_start
    return False
