"""结构化调用的提示词必须自带可校验的输出契约。

`FakeLlmClient` 永远返回预写好的合法 JSON，所以「提示词有没有告诉模型该输出什么」
在自动化测试里完全不可见——2026-08-17 的 understand 与 classify 两次线上事故都是
这么漏出去的。这里把提示词里的 JSON 示例抠出来真正校验，而不是断言某段措辞。

另一条同样重要：这五处都以 `STRUCTURED_CALL_OPTIONS` 请求 `json_object`，而
DeepSeek 要求消息里出现 "JSON" 字样，否则整条调用直接被上游拒绝。
"""

from __future__ import annotations

import json
import re

import pytest

from app.intent.prompts import CLASSIFY_SYSTEM, UNDERSTAND_SYSTEM
from app.localization.locales import SupportedLocale
from app.metrics.catalog import METRIC_CATALOG_EXAMPLE, METRIC_CATALOG_FIELDS
from app.prompts.answer import ANSWER_SYSTEM_PROMPT, build_answer_system_prompt
from app.prompts.memory import (
    build_fallback_memory,
    build_memory_prompt,
    build_memory_system_prompt,
)
from app.prompts.reviewer import REVIEWER_SYSTEM_PROMPT, build_reviewer_system_prompt
from app.schemas.answer import ReviewVerdict

_JSON_OBJECT = re.compile(r"\{[^{}]*\}")
_HAN = re.compile("[一-鿿]")


@pytest.mark.parametrize(
    "prompt",
    [
        CLASSIFY_SYSTEM,
        UNDERSTAND_SYSTEM,
        ANSWER_SYSTEM_PROMPT,
        REVIEWER_SYSTEM_PROMPT,
        build_answer_system_prompt(SupportedLocale.EN_US),
        build_reviewer_system_prompt(SupportedLocale.EN_US),
    ],
)
def test_structured_prompts_mention_json_as_json_output_requires(prompt: str) -> None:
    assert "JSON" in prompt.upper()


def test_reviewer_prompt_examples_cover_both_verdicts_and_satisfy_the_schema() -> None:
    """示例一旦与 `ReviewVerdict` 脱节，就是在教模型输出会被我们自己拒收的形状。"""

    examples = [json.loads(match) for match in _JSON_OBJECT.findall(REVIEWER_SYSTEM_PROMPT)]
    verdicts = [ReviewVerdict.model_validate(example) for example in examples]

    assert any(verdict.passed for verdict in verdicts), "缺少通过形态示例"
    rejected = [verdict for verdict in verdicts if not verdict.passed]
    assert rejected, "缺少不通过形态示例"
    assert all(verdict.issues for verdict in rejected), "不通过示例必须带 issues"


def test_english_reviewer_prompt_examples_also_cover_both_verdicts() -> None:
    """Task 6：英文版提示词必须保持与中文版相同的协议结构，只是措辞改变。"""

    prompt = build_reviewer_system_prompt(SupportedLocale.EN_US)
    examples = [json.loads(match) for match in _JSON_OBJECT.findall(prompt)]
    verdicts = [ReviewVerdict.model_validate(example) for example in examples]

    assert any(verdict.passed for verdict in verdicts)
    rejected = [verdict for verdict in verdicts if not verdict.passed]
    assert rejected
    assert all(verdict.issues for verdict in rejected)


def test_metric_catalog_prompt_example_matches_the_fields_we_actually_read() -> None:
    example = json.loads(METRIC_CATALOG_EXAMPLE)

    assert set(example) == set(METRIC_CATALOG_FIELDS)
    assert all(isinstance(value, str) and value for value in example.values())


def test_default_locale_prompt_builders_equal_the_legacy_zh_constants() -> None:
    """未显式传 `locale` 时必须与 Task 6 之前的常量逐字相同，保证零参数调用点行为不变。"""

    assert build_answer_system_prompt() == ANSWER_SYSTEM_PROMPT
    assert build_reviewer_system_prompt() == REVIEWER_SYSTEM_PROMPT


def test_english_answer_and_reviewer_prompts_contain_no_han_characters() -> None:
    assert not _HAN.search(build_answer_system_prompt(SupportedLocale.EN_US))
    assert not _HAN.search(build_reviewer_system_prompt(SupportedLocale.EN_US))


def test_english_memory_prompts_contain_no_han_characters() -> None:
    assert not _HAN.search(build_memory_system_prompt(SupportedLocale.EN_US))
    prompt = build_memory_prompt(
        merchant_display="Borough Merchant 100",
        category="TRADE",
        manual_markdown="- question: What was GMV yesterday?",
        history=[],
        locale=SupportedLocale.EN_US,
    )
    # 模板外壳（人类可读的指令文字）必须是英文；商家展示名/分类/历史数据本身
    # 允许携带任何语言的原文，不属于这条断言的覆盖范围。
    shell_only = prompt.split("Merchant:")[0]
    assert not _HAN.search(shell_only)


def test_english_fallback_memory_uses_an_english_updated_at_label() -> None:
    """`MEMORY_MARKER`（"本轮自动沉淀"）是内部协议标记，被
    `knowledge/retrieval.py::_first_line()` 按 Markdown 标题行整体跳过，不是
    直接展示给用户的自然语言正文，因此刻意不参与本条断言——协议标记本身固定
    不翻译，与 `intent.category.value`、`LLM_WIKI_SOURCE=` 等内部标记同一原则。
    """

    fallback = build_fallback_memory(
        category="TRADE", manual_markdown="notes", locale=SupportedLocale.EN_US
    )
    assert "Updated at" in fallback
    assert "更新时间" not in fallback
