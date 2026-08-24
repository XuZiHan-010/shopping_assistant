"""Chat BI 看板端点：全平台聚合，仅限管理员令牌访问。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_app_settings, get_database, require_admin_token
from app.core.config import Settings
from app.core.errors import error_responses
from app.db.session import Database
from app.repositories.chatbi import ChatBiRepository
from app.schemas.analytics import (
    ChatBiCategoriesResponse,
    ChatBiCategoryItem,
    ChatBiDailyPoint,
    ChatBiOverviewResponse,
    ChatBiRollupResponse,
    ChatBiWindow,
)
from app.schemas.chat import CATEGORY_DISPLAY_NAMES, QuestionCategory
from app.services.chatbi_service import ChatBiService

router = APIRouter(prefix="/admin/analytics/chatbi", tags=["admin"])


def _service(settings: Settings, database: Database) -> ChatBiService:
    return ChatBiService(ChatBiRepository(database, business_timezone=settings.business_timezone))


@router.get(
    "/overview",
    response_model=ChatBiOverviewResponse,
    responses=error_responses(401, 403, 422),
)
async def chatbi_overview(
    window: Annotated[ChatBiWindow, Query()],
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> ChatBiOverviewResponse:
    overview = await _service(settings, database).overview(
        start_date=window.start_date, end_date=window.end_date
    )
    counters = overview.counters
    metrics = overview.metrics
    return ChatBiOverviewResponse(
        start_date=overview.start_date,
        end_date=overview.end_date,
        answer_total=counters.answer_total,
        business_question_total=counters.business_question_total,
        feedback_total=counters.like_count + counters.dislike_count,
        thinking_sample_count=counters.thinking_sample_count,
        adoption_rate=metrics.adoption_rate,
        user_accuracy_rate=metrics.user_accuracy_rate,
        system_accuracy_rate=metrics.system_accuracy_rate,
        avg_thinking_ms=metrics.avg_thinking_ms,
        hit_rate=metrics.hit_rate,
        failure_rate=metrics.failure_rate,
        daily=[
            ChatBiDailyPoint(
                stat_date=point.stat_date,
                answer_total=point.answer_total,
                adoption_rate=point.metrics.adoption_rate,
                user_accuracy_rate=point.metrics.user_accuracy_rate,
                system_accuracy_rate=point.metrics.system_accuracy_rate,
                avg_thinking_ms=point.metrics.avg_thinking_ms,
                hit_rate=point.metrics.hit_rate,
                failure_rate=point.metrics.failure_rate,
            )
            for point in overview.daily
        ],
    )


@router.get(
    "/categories",
    response_model=ChatBiCategoriesResponse,
    responses=error_responses(401, 403, 422),
)
async def chatbi_categories(
    window: Annotated[ChatBiWindow, Query()],
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> ChatBiCategoriesResponse:
    breakdown = await _service(settings, database).categories(
        start_date=window.start_date, end_date=window.end_date
    )
    return ChatBiCategoriesResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        items=[
            ChatBiCategoryItem(
                category=item.category,
                category_display_name=_display_name(item.category),
                answer_total=item.counters.answer_total,
                adoption_rate=item.metrics.adoption_rate,
                user_accuracy_rate=item.metrics.user_accuracy_rate,
                system_accuracy_rate=item.metrics.system_accuracy_rate,
                avg_thinking_ms=item.metrics.avg_thinking_ms,
                hit_rate=item.metrics.hit_rate,
                failure_rate=item.metrics.failure_rate,
            )
            for item in breakdown
        ],
    )


@router.post(
    "/rollup",
    response_model=ChatBiRollupResponse,
    responses=error_responses(401, 403, 422),
)
async def chatbi_rollup(
    window: ChatBiWindow,
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> ChatBiRollupResponse:
    """手动重刷汇总。幂等，可任意重跑，用于演示与历史补数。"""
    repository = ChatBiRepository(database, business_timezone=settings.business_timezone)
    rows_written = await repository.rollup_range(
        start_date=window.start_date, end_date=window.end_date
    )
    return ChatBiRollupResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        rows_written=rows_written,
    )


def _display_name(category: str) -> str:
    try:
        return CATEGORY_DISPLAY_NAMES[QuestionCategory(category)]
    except (KeyError, ValueError):
        return category
