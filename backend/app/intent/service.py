from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Final

from pydantic import ValidationError

from app.intent.models import QueryIntent
from app.intent.prompts import (
    CLASSIFY_SYSTEM,
    UNDERSTAND_SYSTEM,
    classify_user_prompt,
    understand_user_prompt,
)
from app.intent.whitelist import IntentValidation, validate_intent
from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmUnavailableError,
)
from app.schemas.chat import AnswerMode, QuestionCategory

MAX_INTENT_RETRIES: Final[int] = 2
_BUSINESS_MARKERS: Final[tuple[str, ...]] = (
    "成交额",
    "gmv",
    "订单",
    "交易",
    "退款",
    "退货",
    "工单",
    "咨询",
    "规则",
    "平台规则",
)


@dataclass(frozen=True)
class InitialIntent:
    answer_mode: AnswerMode
    category: QuestionCategory
    intent_keywords: tuple[str, ...]
    llm_analyzed: bool
    degraded_reason: str | None = None


@dataclass(frozen=True)
class IntentOutcome:
    intent: QueryIntent
    validation: IntentValidation
    notes: tuple[str, ...]
    degraded: bool
    degraded_reason: str | None = None


class IntentService:
    def __init__(self, llm: LlmClient) -> None:
        self._llm = llm

    async def recognize(self, question: str, index_text: str, budget: LlmBudget) -> InitialIntent:
        try:
            prompt = classify_user_prompt(question, index_text)
            for attempt in range(2):
                result = await self._llm.complete(
                    system=CLASSIFY_SYSTEM,
                    user=prompt,
                    fallback="",
                    budget=budget,
                    options=STRUCTURED_CALL_OPTIONS,
                )
                value = _object(result.text)
                if value is None:
                    break
                raw_keywords = value.get("intent_keywords", [])
                keywords = raw_keywords if isinstance(raw_keywords, list) else []
                initial = InitialIntent(
                    _answer_mode(value.get("answer_mode")),
                    _category(value.get("category")),
                    tuple(str(x) for x in keywords if str(x).strip()),
                    True,
                )
                if attempt == 0 and _needs_business_classification_retry(question, initial):
                    prompt += (
                        "\n该问题包含明确业务关键词，不得返回 INVALID/UNKNOWN；"
                        "请按既定枚举重新分类。\n"
                    )
                    continue
                return initial
        except LlmDailyBudgetExceededError:
            return _unavailable_initial("今日模型用量已达上限，本次只提供受控数据摘要")
        except LlmBudgetError:
            return _unavailable_initial("单请求 LLM 调用次数或 token 已达上限")
        except LlmUnavailableError:
            return _unavailable_initial("LLM 未配置或暂不可用")
        return _unavailable_initial("LLM 分类结果无效")

    async def understand(
        self,
        question: str,
        initial: InitialIntent,
        knowledge_text: str,
        budget: LlmBudget,
        today: date,
    ) -> IntentOutcome:
        if not initial.llm_analyzed:
            reason = initial.degraded_reason or "LLM 未能完成问题分类"
            intent = QueryIntent(answer_mode=AnswerMode.CHAT, category=initial.category)
            return IntentOutcome(
                intent,
                IntentValidation(intent, (), ()),
                (f"{reason}，已返回可见降级结果。",),
                True,
                reason,
            )

        notes: list[str] = []
        degraded_reason: str | None = None
        for attempt in range(MAX_INTENT_RETRIES + 1):
            try:
                result = await self._llm.complete(
                    system=UNDERSTAND_SYSTEM,
                    user=understand_user_prompt(
                        question, initial.category.value, knowledge_text, today=today
                    ),
                    fallback="",
                    budget=budget,
                    options=STRUCTURED_CALL_OPTIONS,
                )
                value = _object(result.text)
                if value is not None:
                    intent = QueryIntent.model_validate(value)
                    validation = validate_intent(intent, today=today)
                    # 校验产生的截断与拒绝说明不在这里合并：它们由图的 validate_intent
                    # 节点统一透出，避免同一条说明在两处各写一遍。
                    return IntentOutcome(validation.intent, validation, tuple(notes), False)
                degraded_reason = "LLM 结构化输出不是有效 JSON"
            except LlmDailyBudgetExceededError:
                degraded_reason = "今日模型用量已达上限，本次只提供受控数据摘要"
                notes.append(f"{degraded_reason}，停止结构化理解重试")
                break
            except LlmBudgetError:
                degraded_reason = "单请求 LLM 调用次数或 token 已达上限"
                notes.append(f"{degraded_reason}，停止结构化理解重试")
                break
            except LlmUnavailableError:
                degraded_reason = "LLM 未配置或暂不可用"
                notes.append(f"{degraded_reason}，停止结构化理解重试")
                break
            except ValidationError:
                degraded_reason = "LLM 结构化输出未通过校验"
            notes.append(f"第 {attempt + 1} 次结构化理解解析失败")
        intent = QueryIntent(answer_mode=AnswerMode.CHAT, category=initial.category)
        return IntentOutcome(
            intent,
            IntentValidation(intent, (), ()),
            tuple(notes),
            True,
            degraded_reason or "LLM 结构化理解失败",
        )


def _unavailable_initial(reason: str) -> InitialIntent:
    return InitialIntent(AnswerMode.CHAT, QuestionCategory.UNKNOWN, (), False, reason)


def _needs_business_classification_retry(question: str, initial: InitialIntent) -> bool:
    return initial.category is QuestionCategory.UNKNOWN and any(
        marker in question.casefold() for marker in _BUSINESS_MARKERS
    )


def _object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _answer_mode(value: object) -> AnswerMode:
    try:
        return AnswerMode(value)  # type: ignore[arg-type]
    except ValueError:
        return AnswerMode.CHAT


def _category(value: object) -> QuestionCategory:
    try:
        return QuestionCategory(value)  # type: ignore[arg-type]
    except ValueError:
        return QuestionCategory.UNKNOWN
