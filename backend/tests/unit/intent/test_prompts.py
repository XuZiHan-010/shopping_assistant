"""提示词必须自带输出契约。

2026-08-17 首次用真实 `deepseek-v4-flash` 跑通线上链路时发现：`understand_user_prompt`
只列了允许的**取值**（metric/dimensions/filters 白名单），却从未告诉模型输出的**字段名和
形状**，只说了一句「输出完整 QueryIntent JSON」。模型据此自造了
`{"intent": ..., "business_domain": ..., "metrics": [...], "filters": [...]}`，
而 `QueryIntent` 是 `extra="forbid"`，于是每次都 ValidationError、三次重试全废、
回落 CHAT 模式——每问一次真实扣费却只得到兜底文案。

这些用例锁住的是「提示词里必须写明契约」，不是某段具体措辞：期望值从
`QueryIntent` 的字段定义推导，schema 变了测试跟着变，不会悄悄过期。
"""

from __future__ import annotations

from datetime import date

from app.intent.models import QueryIntent
from app.intent.prompts import understand_user_prompt
from app.schemas.chat import AnswerMode, QuestionCategory

_TODAY = date(2026, 8, 17)


def _prompt() -> str:
    return understand_user_prompt(
        "最近7天的退货量趋势怎么样", "REFUND", "（业务知识正文）", today=_TODAY
    )


def _model_visible_fields() -> list[str]:
    """模型该知道的字段。

    `exclude=True` 的 `*_rejected` 是校验器自己写的内部状态，既不参与 `model_dump`
    也不该出现在提示词里——告诉模型它们存在，等于邀请模型伪造拒绝标记。
    """

    return [name for name, field in QueryIntent.model_fields.items() if not field.exclude]


def test_understand_prompt_declares_every_model_visible_field() -> None:
    prompt = _prompt()
    missing = [name for name in _model_visible_fields() if name not in prompt]
    assert missing == [], f"提示词未声明这些字段，模型只能靠猜：{missing}"


def test_understand_prompt_never_leaks_validator_only_fields() -> None:
    prompt = _prompt()
    internal = [name for name, field in QueryIntent.model_fields.items() if field.exclude]
    assert internal, "本用例假设存在 exclude 字段；若已移除请一并删除本断言"
    leaked = [name for name in internal if name in prompt]
    assert leaked == [], f"提示词泄漏了只应由校验器写入的内部字段：{leaked}"


def test_understand_prompt_lists_allowed_values_for_required_enums() -> None:
    """`answer_mode` 与 `category` 都是必填枚举，模型猜不出取值集合。

    线上实测里 `category` 直接缺失、`answer_mode` 侥幸猜对，都是没给取值表的后果。
    """

    prompt = _prompt()
    missing = [
        value
        for enum in (AnswerMode, QuestionCategory)
        for value in (member.value for member in enum)
        if value not in prompt
    ]
    assert missing == [], f"提示词未列出这些必填枚举取值：{missing}"


def test_understand_prompt_states_today_so_relative_dates_resolve() -> None:
    """模型不知道今天几号，`date_range` 就只能瞎猜。

    2026-08-17 实测：问「最近 7 天」，模型返回 2025-03-14~2025-03-20。那是个合法的
    7 天窗口，`validate_intent` 只钳制「结束日不超今天」和「跨度不超 180 天」，不会
    纠正它，于是查询打在没有数据的历史区间上，用户看到的是空结果而不是错误。
    """

    assert _TODAY.isoformat() in _prompt()
