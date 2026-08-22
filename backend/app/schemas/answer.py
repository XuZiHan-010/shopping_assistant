"""B5 回答编排的内部结构化契约。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

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
    advisory_notes: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    ] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_consistency(self) -> ReviewVerdict:
        if not self.passed and not self.issues:
            raise ValueError("Reviewer 打回回答时必须说明问题")
        if self.passed and self.issues:
            self.advisory_notes = [*self.advisory_notes, *self.issues]
            self.issues = []
        return self
