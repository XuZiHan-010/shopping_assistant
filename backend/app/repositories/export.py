"""导出记录数据访问；所有读取都显式绑定商家范围。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import ExportFile


class ExportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        merchant_id: UUID,
        answer_id: UUID,
        export_spec: dict[str, Any],
        expires_at: datetime,
    ) -> ExportFile:
        record = ExportFile(
            merchant_id=merchant_id,
            answer_id=answer_id,
            export_spec=export_spec,
            expires_at=expires_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_for_signed_download(
        self,
        export_id: UUID,
        merchant_id: UUID,
    ) -> ExportFile | None:
        return cast(
            ExportFile | None,
            await self._session.scalar(
                select(ExportFile).where(
                    ExportFile.id == export_id,
                    ExportFile.merchant_id == merchant_id,
                )
            ),
        )
