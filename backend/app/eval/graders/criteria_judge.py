"""第二层裁判的逐项判定版本（E2）：每个标准单独给通过与否和理由，多票取中位数。

旧裁判（`llm_judge.py`）只输出一个小数、只判一次；2026-10-06 真实评测中，同一句
正确回答先后得到 1.0 / 0.5 / 0.4。它保留给已冻结批次复现用，新评测用这里的版本。
与旧裁判一样，签名里没有候选实现身份的位置。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from app.llm.client import STRUCTURED_CALL_OPTIONS, LlmBudget, LlmClient


@dataclass(frozen=True)
class Criterion:
    key: str
    description: str


@dataclass(frozen=True)
class CriteriaRubric:
    id: str
    version: str
    criteria: tuple[Criterion, ...]


@dataclass(frozen=True)
class JudgeVote:
    #: 通过的标准占比；裁判输出无法按约定解析时为 None，不计入中位数。
    score: float | None
    verdicts: dict[str, bool]
    reasons: dict[str, str]
    raw_response: str


@dataclass(frozen=True)
class CriteriaJudgeResult:
    rubric_id: str
    rubric_version: str
    #: 有效票的中位数；没有有效票时为 None（无结论，不算通过）。
    score: float | None
    passed: bool
    unanimous: bool
    votes: tuple[JudgeVote, ...]


def _parse_vote(text: str, criteria: Sequence[Criterion]) -> JudgeVote:
    invalid = JudgeVote(score=None, verdicts={}, reasons={}, raw_response=text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return invalid
    if not isinstance(payload, dict):
        return invalid
    verdicts: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    for criterion in criteria:
        item = payload.get(criterion.key)
        if not isinstance(item, dict) or not isinstance(item.get("passed"), bool):
            return invalid
        verdicts[criterion.key] = item["passed"]
        reasons[criterion.key] = str(item.get("reason", ""))
    return JudgeVote(
        score=sum(verdicts.values()) / len(criteria),
        verdicts=verdicts,
        reasons=reasons,
        raw_response=text,
    )


async def grade_by_criteria(
    *,
    client: LlmClient,
    rubric: CriteriaRubric,
    transcript: str,
    votes: int = 3,
) -> CriteriaJudgeResult:
    """每票独立判定全部标准；全部标准通过的票占多数（中位数为 1）才算通过。"""

    system = (
        f"你是评测裁判，使用固定评分标准 {rubric.id}@{rubric.version}。"
        "只依据下方标准与对话记录，逐条独立判定；某条标准不适用于这段对话时判通过。"
        "只输出单个 JSON 对象，不要输出 Markdown 代码围栏或其他文字。"
    )
    listed = "\n".join(f"- {item.key}：{item.description}" for item in rubric.criteria)
    shape = ", ".join(
        f'"{item.key}": {{"passed": true 或 false, "reason": "一句话理由"}}'
        for item in rubric.criteria
    )
    user = (
        f"评分标准（逐条判定）：\n{listed}\n\n"
        f"输出 JSON 形如：{{{shape}}}\n\n---\n对话记录：\n{transcript}"
    )
    cast_votes: list[JudgeVote] = []
    for _ in range(votes):
        result = await client.complete(
            system=system,
            user=user,
            fallback="",
            budget=LlmBudget(max_calls=1, max_tokens=2000),
            options=STRUCTURED_CALL_OPTIONS,
        )
        cast_votes.append(_parse_vote(result.text, rubric.criteria))
    scores = [vote.score for vote in cast_votes if vote.score is not None]
    score = median(scores) if scores else None
    return CriteriaJudgeResult(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        score=score,
        passed=score == 1.0,
        unanimous=len({value == 1.0 for value in scores}) == 1,
        votes=tuple(cast_votes),
    )
