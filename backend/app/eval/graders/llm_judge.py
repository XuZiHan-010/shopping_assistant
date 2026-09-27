"""第二层：LLM 裁判（E2）。

固定 rubric + 版本号，且**不接受候选实现身份**作为参数——这不是靠调用方
小心不传，而是函数签名里根本没有这个位置，结构上杜绝把「这是新循环/旧基线」
之类的线索送进裁判 payload。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import LlmBudget, LlmClient


@dataclass(frozen=True)
class JudgeResult:
    rubric_id: str
    rubric_version: str
    score: float
    passed: bool
    raw_response: str


def _parse_score(text: str) -> float:
    try:
        return max(0.0, min(1.0, float(text.strip())))
    except ValueError:
        return 0.0


async def grade_with_rubric(
    *,
    client: LlmClient,
    rubric_id: str,
    version: str,
    rubric_prompt: str,
    transcript: str,
    threshold: float = 0.6,
    budget: LlmBudget | None = None,
) -> JudgeResult:
    """用固定 rubric 给一份对话记录打分；`transcript` 必须已经脱去候选身份信息。"""

    system = (
        f"你是评测裁判，使用固定评分标准 {rubric_id}@{version}。"
        "只依据下方标准与对话记录打分，输出 0 到 1 之间的一个小数，不要输出其他内容。"
    )
    user = f"{rubric_prompt}\n\n---\n对话记录：\n{transcript}"
    result = await client.complete(
        system=system,
        user=user,
        fallback="0",
        budget=budget or LlmBudget(max_calls=1, max_tokens=2000),
    )
    score = _parse_score(result.text)
    return JudgeResult(
        rubric_id=rubric_id,
        rubric_version=version,
        score=score,
        passed=score >= threshold,
        raw_response=result.text,
    )
