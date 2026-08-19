"""结构化调用的提示词必须自带可校验的输出契约。

`FakeLlmClient` 永远返回预写好的合法 JSON，所以「提示词有没有告诉模型该输出什么」
在自动化测试里完全不可见——2026-08-17 的 understand 与 classify 两次线上事故都是
这么漏出去的。这里把提示词里的 JSON 示例抠出来真正校验，而不是断言某段措辞。

另一条同样重要：这四处都以 `STRUCTURED_CALL_OPTIONS` 请求 `json_object`，而
DeepSeek 要求消息里出现 "JSON" 字样，否则整条调用直接被上游拒绝。
"""

from __future__ import annotations

import json
import re

import pytest

from app.intent.prompts import CLASSIFY_SYSTEM, UNDERSTAND_SYSTEM
from app.metrics.catalog import METRIC_CATALOG_EXAMPLE, METRIC_CATALOG_FIELDS
from app.prompts.reviewer import REVIEWER_SYSTEM_PROMPT
from app.schemas.answer import ReviewVerdict

_JSON_OBJECT = re.compile(r"\{[^{}]*\}")


@pytest.mark.parametrize(
    "prompt",
    [CLASSIFY_SYSTEM, UNDERSTAND_SYSTEM, REVIEWER_SYSTEM_PROMPT],
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


def test_metric_catalog_prompt_example_matches_the_fields_we_actually_read() -> None:
    example = json.loads(METRIC_CATALOG_EXAMPLE)

    assert set(example) == set(METRIC_CATALOG_FIELDS)
    assert all(isinstance(value, str) and value for value in example.values())
