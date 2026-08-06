"""B5 回答编排的内部结构化契约。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.chat import Recommendation


class AnswerDraft(BaseModel):
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
    recommendations: list[Recommendation] = Field(min_length=2, max_length=5)


class ReviewVerdict(BaseModel):
    passed: bool
    issues: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    ] = Field(
        default_factory=list,
        max_length=5,
    )
