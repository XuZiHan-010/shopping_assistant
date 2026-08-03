"""健康检查路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_database
from app.core.errors import DatabaseUnavailableError, error_responses
from app.db.session import Database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """返回进程健康状态，不访问数据库或 LLM。"""

    return HealthResponse(status="ok", version=request.app.state.settings.app_version)


@router.get("/ready", response_model=ReadyResponse, responses=error_responses(503))
async def ready(
    database: Annotated[Database, Depends(get_database)],
) -> ReadyResponse:
    """执行轻量数据库 readiness 探针。"""

    try:
        await database.ping()
    except (SQLAlchemyError, OSError):
        raise DatabaseUnavailableError from None
    return ReadyResponse(status="ready")
