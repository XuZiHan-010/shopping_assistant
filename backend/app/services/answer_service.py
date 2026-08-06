"""把受控查询事实组织成回答草稿，并在使用前作本地校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.llm.client import (
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmUnavailableError,
)
from app.metrics.catalog import MetricPayload
from app.prompts.answer import ANSWER_SYSTEM_PROMPT
from app.schemas.answer import AnswerDraft
from app.schemas.chat import Recommendation
from app.services.safe_query import QueryResult

_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2}|Z)?)?\b")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# 非加和指标（QueryResult.non_additive）按业务日拆成多行时，模型只被允许原样引用
# 行内数值，不能自己把它们合计/平均成一个新结论——那类结论既不在 allowed_numbers
# 里（如果是新算出的数字会被数字校验拦住），也可能只是复述某一行却贴上「合计」
# 类字眼，看起来像是对全部区间下了结论。见 docs/backend-development-plan.md 的
# B5 本地校验清单第 6 条。
_ADDITIVE_CLAIM_PHRASES = ("合计", "总计", "累计", "总和", "加总", "汇总")


@dataclass(frozen=True)
class AnswerFacts:
    question: str
    metric: MetricPayload | None
    query_result: QueryResult


@dataclass(frozen=True)
class AnswerDraftResult:
    draft: AnswerDraft
    degraded: bool
    notes: list[str]


class AnswerService:
    """模型只能在事实包内起草；失败时退化为同一事实包的确定性摘要。"""

    async def compose(
        self,
        facts: AnswerFacts,
        llm: LlmClient,
        budget: LlmBudget,
    ) -> AnswerDraftResult:
        fallback = self._fallback(facts)
        try:
            result = await llm.complete(
                system=ANSWER_SYSTEM_PROMPT,
                user=_facts_json(facts),
                fallback=fallback.model_dump_json(),
                budget=budget,
            )
            if result.degraded:
                return _degraded(fallback)
            draft = AnswerDraft.model_validate_json(result.text)
            self._validate(draft, facts)
        except LlmDailyBudgetExceededError:
            return AnswerDraftResult(
                draft=fallback,
                degraded=True,
                notes=["今日模型用量已达上限，本次只提供受控数据摘要"],
            )
        except (ValueError, LlmUnavailableError, LlmBudgetError):
            return _degraded(fallback)
        return AnswerDraftResult(draft=draft, degraded=False, notes=[])

    def facts_json(self, facts: AnswerFacts) -> str:
        return _facts_json(facts)

    def _fallback(self, facts: AnswerFacts) -> AnswerDraft:
        metric = facts.metric
        result = facts.query_result
        metric_label = metric.display_name if metric is not None else "经营指标"
        unit = metric.unit if metric is not None else ""
        value = _first_metric_value(result, metric.metric_code if metric is not None else None)
        if value is None:
            answer = (
                f"本次查询返回 {result.total_rows} 行数据，暂未形成可汇总的{metric_label}数值。"
            )
        else:
            answer = f"本次查询的{metric_label}为 {value}{unit}。"
        return AnswerDraft(
            answer=answer,
            recommendations=[
                Recommendation(
                    title="核对查询范围",
                    evidence=f"本次查询返回 {result.total_rows} 行数据。",
                    action="确认日期范围和筛选条件是否覆盖要分析的业务。",
                ),
                Recommendation(
                    title="持续观察指标",
                    evidence=answer,
                    action="结合后续周期数据判断变化是否持续。",
                ),
            ],
        )

    def _validate(self, draft: AnswerDraft, facts: AnswerFacts) -> None:
        allowed_numbers = _allowed_numbers(facts.query_result)
        raw_text = "\n".join(
            [
                draft.answer,
                *(item.evidence for item in draft.recommendations),
            ]
        )
        if _UUID.search(raw_text):
            raise ValueError("回答含有内部标识符，不得出现在对商家的回答里")
        result = facts.query_result
        if (
            result.non_additive
            and len(result.rows) > 1
            and any(phrase in raw_text for phrase in _ADDITIVE_CLAIM_PHRASES)
        ):
            raise ValueError("非加和指标不能被回答草稿合计或汇总")
        # 日期是维度值，不是要与聚合结果逐项比对的业务数字；否则 2026-08-05
        # 会被拆成三个数字并把一份完全基于事实的草稿误判为幻觉。
        text = _ISO_DATE.sub("", raw_text)
        unexpected = {number for number in _NUMBER.findall(text) if number not in allowed_numbers}
        if unexpected:
            raise ValueError("回答含有查询结果外的数字")


def _degraded(fallback: AnswerDraft) -> AnswerDraftResult:
    return AnswerDraftResult(
        draft=fallback,
        degraded=True,
        notes=["回答生成已降级为受控数据摘要。"],
    )


def _facts_json(facts: AnswerFacts) -> str:
    metric = facts.metric
    non_additive = "true" if facts.query_result.non_additive else "false"
    return (
        '{"question":'
        + _json_string(facts.question)
        + ',"metric":'
        + _json_string(metric.display_name if metric is not None else "")
        + ',"unit":'
        + _json_string(metric.unit if metric is not None else "")
        + ',"rows":'
        + _json_rows(facts.query_result.rows)
        + f',"total_rows":{facts.query_result.total_rows}'
        + f',"non_additive":{non_additive}'
        + "}"
    )


def _json_rows(rows: list[dict[str, object]]) -> str:
    import json

    return json.dumps(
        [{key: _json_value(value) for key, value in row.items()} for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def _first_metric_value(result: QueryResult, metric_code: str | None) -> str | None:
    if metric_code is None or not result.rows:
        return None
    value = result.rows[0].get(metric_code)
    return None if value is None else _display_value(value)


def _allowed_numbers(result: QueryResult) -> set[str]:
    values = {str(result.total_rows)}
    for row in result.rows:
        for value in row.values():
            if isinstance(value, Decimal | int | float):
                values.add(_display_value(value))
    return values


def _display_value(value: object) -> str:
    return str(value)
