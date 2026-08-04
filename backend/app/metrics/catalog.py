"""指标口径三级检索：正式目录、字段注释（B4）和 LLM 候选。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Protocol

from app.intent.models import QueryIntent
from app.llm.client import LlmBudget, LlmBudgetExceededError, LlmClient, LlmUnavailableError
from app.schemas.chat import AnswerMode

GENERATED_NOTICE: Final[str] = (
    "该指标口径未命中正式指标目录或字段注释，"
    "以下内容由大模型根据当前问题生成，仅供参考，请以正式指标口径为准。"
)
_SYSTEM_PROMPT = "你是 Borough 商家 AI 助手的指标口径助理，只输出 JSON。"


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


class _MetricRowLike(Protocol):
    metric_code: str
    display_name: str
    unit: str
    business_definition: str
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
                row.metric_code,
                row.display_name,
                row.unit,
                row.business_definition,
                row.source,
                row.owner,
                row.status,
                False,
                None,
            )
        try:
            result = await self._llm.complete(
                system=_SYSTEM_PROMPT,
                user=(
                    f"指标标识：{intent.metric}\n可用知识：\n{knowledge_text}\n"
                    "只输出 JSON，字段为 display_name、unit、definition。"
                ),
                fallback="",
                budget=budget,
            )
            data = json.loads(result.text)
        except (json.JSONDecodeError, LlmBudgetExceededError, LlmUnavailableError):
            return None
        if not isinstance(data, dict):
            return None
        return MetricPayload(
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
