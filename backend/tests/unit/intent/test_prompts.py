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

import json
from datetime import date

from app.intent.models import QueryIntent
from app.intent.prompts import (
    CLASSIFY_SYSTEM,
    UNDERSTAND_SYSTEM,
    classify_user_prompt,
    understand_user_prompt,
)
from app.schemas.chat import AnswerMode, QuestionCategory

_TODAY = date(2026, 8, 17)


EXAMPLE_MARKER = "输出示例："


def _sole_json_object(prompt: str) -> dict[str, object]:
    """取出提示词里 `输出示例：` 之后那段 JSON。

    参考项目 `LlmIntentAnalysisService.buildPrompt` 用「完整 JSON 示例」而不是字段表
    来传达契约（R9）。示例一旦和真实 schema 脱节就是在教模型输出错的东西，所以这里
    把它抠出来交给下面的用例真正校验，而不是只断言「提示词里有个大括号」。
    """

    assert EXAMPLE_MARKER in prompt, f"提示词缺少「{EXAMPLE_MARKER}」段"
    tail = prompt.split(EXAMPLE_MARKER, 1)[1].lstrip()
    value, _ = json.JSONDecoder().raw_decode(tail)
    assert isinstance(value, dict)
    return value


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


def test_understand_prompt_carries_a_json_example_that_matches_the_schema() -> None:
    """示例必须真的能过 `QueryIntent` 校验，否则就是在教模型输出错的形状。"""

    QueryIntent.model_validate(_sole_json_object(_prompt()))


def test_classify_prompt_lists_allowed_values_for_both_enums() -> None:
    """分类阶段是整条链路的闸门：它一失败，`understand` 根本不会执行。

    2026-08-17 线上实测：提示词只说「输出 answer_mode、category、intent_keywords
    JSON」，真实模型返回 answer_mode="trend_query"、category="退款退货域"。
    `_answer_mode` / `_category` 遇到非法值静默回落成 CHAT / UNKNOWN，不报错，
    于是整轮问答退化成兜底文案却没有任何异常信号。

    参考项目 `LlmIntentAnalysisService.buildPrompt` 逐个列出了 category 与
    answerMode 的可选值（R9），移植时丢了这一段。
    """

    prompt = classify_user_prompt("最近7天的退货量趋势", "（业务索引）")
    missing = [
        value
        for enum in (AnswerMode, QuestionCategory)
        for value in (member.value for member in enum)
        if value not in prompt
    ]
    assert missing == [], f"分类提示词未列出这些枚举取值：{missing}"


def test_classify_prompt_can_route_core_business_questions_without_knowledge_index() -> None:
    """知识库为空时，分类器仍必须知道核心业务域，不能把所有问题判成 UNKNOWN。"""

    prompt = classify_user_prompt("最近七天成交额趋势如何？", "")

    assert "成交额、GMV、订单、交易" in prompt
    assert "退款、退货" in prompt
    assert "规则、平台规则" in prompt


def test_classify_prompt_example_uses_only_legal_enum_values() -> None:
    example = _sole_json_object(classify_user_prompt("最近7天的退货量趋势", "（业务索引）"))
    assert set(example) == {"answer_mode", "category", "intent_keywords"}
    AnswerMode(example["answer_mode"])
    QuestionCategory(example["category"])
    assert isinstance(example["intent_keywords"], list)


def test_both_system_prompts_forbid_markdown_fences() -> None:
    """参考项目的系统提示词写明「必须只输出 JSON 对象，不要输出 Markdown」。

    裸 `json.loads` 遇到 ```json 围栏直接失败，而失败表现是静默降级。
    """

    for name, system in (("classify", CLASSIFY_SYSTEM), ("understand", UNDERSTAND_SYSTEM)):
        assert "Markdown" in system or "markdown" in system, f"{name} 系统提示词未禁止 Markdown"


def test_understand_prompt_states_today_so_relative_dates_resolve() -> None:
    """模型不知道今天几号，`date_range` 就只能瞎猜。

    2026-08-17 实测：问「最近 7 天」，模型返回 2025-03-14~2025-03-20。那是个合法的
    7 天窗口，`validate_intent` 只钳制「结束日不超今天」和「跨度不超 180 天」，不会
    纠正它，于是查询打在没有数据的历史区间上，用户看到的是空结果而不是错误。
    """

    assert _TODAY.isoformat() in _prompt()
