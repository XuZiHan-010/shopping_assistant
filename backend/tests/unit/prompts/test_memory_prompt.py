"""记忆压缩提示词的契约测试。"""

from __future__ import annotations

from app.prompts.memory import (
    MEMORY_MARKER,
    MEMORY_SYSTEM_PROMPT,
    build_fallback_memory,
    build_memory_prompt,
)


def test_prompt_carries_all_four_reference_constraints() -> None:
    prompt = build_memory_prompt(
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="## 本轮自动沉淀",
        history=[{"question": "上月成交额", "category": "TRADE"}],
    )

    assert "只沉淀当前商家" in prompt
    assert "不要编造数据库字段" in prompt
    assert "优先保留人工补充" in prompt
    assert "不得引用" in prompt and "其他商家" in prompt


def test_prompt_pins_merchant_and_category() -> None:
    prompt = build_memory_prompt(
        merchant_display="Borough商家100",
        category="REFUND",
        manual_markdown="",
        history=[],
    )

    assert "Borough商家100" in prompt
    assert "REFUND" in prompt


def test_system_prompt_declares_independent_memory_role() -> None:
    assert "记忆" in MEMORY_SYSTEM_PROMPT
    assert "独立" in MEMORY_SYSTEM_PROMPT


def test_fallback_always_carries_marker() -> None:
    fallback = build_fallback_memory(category="TRADE", manual_markdown="正文")

    assert MEMORY_MARKER in fallback
    assert "正文" in fallback


def test_brand_never_leaks_legacy_ip() -> None:
    prompt = build_memory_prompt(
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="",
        history=[],
    )

    assert "yshopping" not in prompt.lower()
    assert "Borough" in prompt
