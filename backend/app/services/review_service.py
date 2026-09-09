"""独立审核候选回答；Reviewer 从不改写回答。"""

from __future__ import annotations

from typing import Final

from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmUnavailableError,
)
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale
from app.prompts.reviewer import build_reviewer_system_prompt
from app.schemas.answer import AnswerDraft, ReviewVerdict
from app.services.answer_service import extract_json_object
from app.services.quality_types import AttemptFailureKind, ReviewAttempt

# Task 5：与 quality_loop.py 同理——命名常量与
# `app.localization.catalog._REVIEW_SERVICE_MESSAGES` 的词典 key 必须保持字面
# 一致，`tests/unit/services/test_quality_loop.py` 有一条测试直接断言这一点。
_MSG_REVIEWER_UNAVAILABLE: Final = "Reviewer 暂不可用"
_MSG_REVIEWER_EMPTY_OUTPUT: Final = "Reviewer 输出为空，请只输出完整 JSON"
_MSG_REVIEWER_UNPARSEABLE: Final = "Reviewer 输出无法解析为约定 JSON"


def _localized(message: str, locale: SupportedLocale) -> str:
    """Task 6：把 §来源 catalog.py 已登记的固定中文整句渲染成目标语言，
    与 `quality_loop.py::_localized()` 同一原则——`zh-CN` 原样返回，
    `en-US` 查不到时兜底原句而不是抛异常。这两个 issue 文案最终会流进
    `QualityLoop._REJECT_NOTE_TEMPLATES[locale].format(..., issues=...)`
    拼进 `quality_notes`，不本地化就会在英文响应里混入一句中文。
    """

    if locale is SupportedLocale.ZH_CN:
        return message
    return localize_catalog_value(message, locale) or message


class ReviewService:
    async def review_once(
        self,
        draft: AnswerDraft,
        facts_json: str,
        llm: LlmClient,
        budget: LlmBudget,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> ReviewAttempt:
        try:
            result = await llm.complete(
                system=build_reviewer_system_prompt(locale),
                user=('{"facts":' + facts_json + ',"candidate":' + draft.model_dump_json() + "}"),
                fallback=f'{{"passed":false,"issues":["{_MSG_REVIEWER_UNAVAILABLE}"]}}',
                budget=budget,
                options=STRUCTURED_CALL_OPTIONS,
            )
        except LlmBudgetError:
            return ReviewAttempt(None, "", (), AttemptFailureKind.BUDGET)
        except LlmUnavailableError:
            return ReviewAttempt(None, "", (), AttemptFailureKind.UPSTREAM)
        if result.degraded:
            return ReviewAttempt(None, result.text, (), AttemptFailureKind.UPSTREAM)
        if not result.text:
            return ReviewAttempt(None, "", (_localized(_MSG_REVIEWER_EMPTY_OUTPUT, locale),), None)
        try:
            verdict = ReviewVerdict.model_validate_json(extract_json_object(result.text))
        except ValueError:
            return ReviewAttempt(
                None, result.text, (_localized(_MSG_REVIEWER_UNPARSEABLE, locale),), None
            )
        return ReviewAttempt(verdict, result.text, tuple(verdict.issues), None)
