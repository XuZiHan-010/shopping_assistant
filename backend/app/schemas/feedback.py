from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class FeedbackReaction(StrEnum):
    LIKE = "LIKE"
    DISLIKE = "DISLIKE"


class FeedbackRequest(BaseModel):
    is_adopted: bool = False
    reaction: FeedbackReaction | None = None


class FeedbackResponse(BaseModel):
    answer_id: UUID
    is_adopted: bool
    reaction: FeedbackReaction | None
