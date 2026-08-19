"""指标口径三级检索：正式目录、字段注释（B4）和 LLM 候选。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Final, Protocol

from app.analytics.contract import metric_spec
from app.intent.models import QueryIntent
from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmUnavailableError,
)
from app.metrics.field_comments import find_field_comment
from app.schemas.chat import AnswerMode, MetricDefinitionSource

GENERATED_NOTICE: Final[str] = (
    "该指标口径未命中正式指标目录或字段注释，"
    "以下内容由大模型根据当前问题生成，仅供参考，请以正式指标口径为准。"
)
_SYSTEM_PROMPT = "你是 Borough 商家 AI 助手的指标口径助理，只输出 JSON。"
#: 只报字段名不给形状，模型就会自造嵌套结构——2026-08-17 的 understand 事故正是如此。
#: 示例与下游真正读取的字段由 `tests/unit/prompts/test_structured_prompts.py` 钉在一起。
METRIC_CATALOG_EXAMPLE = (
    '{"display_name":"退货量","unit":"件","definition":"统计周期内发起退货的商品件数。"}'
)
METRIC_CATALOG_FIELDS = ("display_name", "unit", "definition")


@dataclass(frozen=True)
class MetricPayload:
    metric_code: str
    display_name: str
    unit: str
    definition: str
    source: str
    owner: str
    status: str
    generated: bool
    notice: str | None
    sql_definition: str = ""
    dimensions: tuple[str, ...] = ()
    source_database: str = ""
    source_table: str = ""
    report_url: str | None = None


class _MetricRowLike(Protocol):
    metric_code: str
    display_name: str
    unit: str
    business_definition: str
    sql_definition: str
    source: str
    owner: str
    status: str


class _MetricRepositoryLike(Protocol):
    async def get_by_code(self, metric_code: str) -> _MetricRowLike | None: ...


class MetricCatalog:
    def __init__(self, repository: _MetricRepositoryLike, llm: LlmClient) -> None:
        self._repository, self._llm = repository, llm

    async def resolve(
        self, intent: QueryIntent, knowledge_text: str, budget: LlmBudget
    ) -> MetricPayload | None:
        if intent.answer_mode is not AnswerMode.METRIC or intent.metric is None:
            return None
        if (row := await self._repository.get_by_code(intent.metric)) is not None:
            return MetricPayload(
                metric_code=row.metric_code,
                display_name=row.display_name,
                unit=row.unit,
                definition=row.business_definition,
                source=MetricDefinitionSource.METRIC_CATALOG.value,
                owner=row.owner,
                status=row.status,
                generated=False,
                notice=None,
                sql_definition=getattr(row, "sql_definition", ""),
                dimensions=tuple(getattr(row, "dimensions", ())),
                source_database=getattr(row, "source_database", ""),
                source_table=getattr(row, "source_table", ""),
                report_url=getattr(row, "report_url", None),
            )
        if (comment := find_field_comment(intent.metric)) is not None:
            spec = metric_spec(intent.metric)
            return MetricPayload(
                metric_code=intent.metric,
                display_name=spec.label,
                unit=spec.unit,
                definition=comment.business_definition,
                source=MetricDefinitionSource.FIELD_COMMENT.value,
                owner="字段注释",
                status="UNVERIFIED",
                generated=False,
                notice=None,
                sql_definition=comment.sql_definition,
                dimensions=comment.dimensions,
                source_database=comment.source_database,
                source_table=comment.source_table,
            )
        try:
            result = await self._llm.complete(
                system=_SYSTEM_PROMPT,
                user=(
                    f"指标标识：{intent.metric}\n可用知识：\n{knowledge_text}\n"
                    "只输出 JSON 对象，不要围栏和解释文字。输出示例："
                    f"{METRIC_CATALOG_EXAMPLE}"
                ),
                fallback="",
                budget=budget,
                options=STRUCTURED_CALL_OPTIONS,
            )
            data = json.loads(result.text)
        except (json.JSONDecodeError, LlmBudgetError, LlmUnavailableError):
            return None
        if not isinstance(data, dict):
            return None
        generated = MetricPayload(
            intent.metric,
            str(data.get("display_name", intent.metric)),
            str(data.get("unit", "")),
            str(data.get("definition", "")),
            "大模型生成",
            "待认领",
            "UNVERIFIED",
            True,
            GENERATED_NOTICE,
        )
        return replace(generated, source=MetricDefinitionSource.AI_GENERATED.value)
