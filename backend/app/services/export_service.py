"""受签名保护的动态 CSV 导出。"""

from __future__ import annotations

import csv
import hmac
import io
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Literal, Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID

from app.analytics.contract import UnknownFieldError, detail_spec
from app.core.errors import (
    ExportLinkExpiredError,
    MerchantScopeViolationError,
    ResourceNotFoundError,
)
from app.intent.models import CrossBusinessPlan, GeneratedMetricPlan
from app.repositories.analytics import AnalyticsRepository, DetailResult
from app.repositories.export import ExportRepository
from app.schemas.chat import ExportInfo, QuestionCategory
from app.services.safe_query import ExportSpec


class _ExportRecord(Protocol):
    id: UUID
    merchant_id: UUID
    export_spec: dict[str, object]
    expires_at: datetime


class ExportService:
    def __init__(
        self,
        exports: ExportRepository,
        analytics: AnalyticsRepository,
        *,
        signing_secret: str,
        ttl_minutes: int,
    ) -> None:
        self._exports = exports
        self._analytics = analytics
        self._secret = signing_secret.encode("utf-8")
        self._ttl = timedelta(minutes=ttl_minutes)

    async def create(
        self,
        *,
        merchant_id: UUID,
        answer_id: UUID,
        spec: ExportSpec,
        now: datetime | None = None,
    ) -> ExportInfo:
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + self._ttl
        record = await self._exports.create(
            merchant_id=merchant_id,
            answer_id=answer_id,
            export_spec=_serialize_spec(spec),
            expires_at=expires_at,
        )
        signature = self._signature(record.id, merchant_id, expires_at)
        query = urlencode(
            {
                "merchant_id": str(merchant_id),
                "expires_at": str(int(expires_at.timestamp())),
                "signature": signature,
            }
        )
        return ExportInfo(
            id=record.id, url=f"/api/exports/{record.id}?{query}", expires_at=expires_at
        )

    async def download(
        self,
        *,
        export_id: UUID,
        merchant_id: UUID,
        expires_at: int,
        signature: str,
        now: datetime | None = None,
    ) -> str:
        expiry = datetime.fromtimestamp(expires_at, tz=UTC)
        if not hmac.compare_digest(signature, self._signature(export_id, merchant_id, expiry)):
            raise MerchantScopeViolationError
        current = now or datetime.now(UTC)
        if current >= expiry:
            raise ExportLinkExpiredError
        record = await self._exports.get_for_signed_download(export_id, merchant_id)
        if record is None:
            raise ResourceNotFoundError("导出文件")
        if record.expires_at <= current:
            raise ExportLinkExpiredError
        try:
            spec = _deserialize_spec(record.export_spec)
        except ValueError as exc:
            raise ResourceNotFoundError("导出文件") from exc
        if spec.kind == "cross_business":
            if spec.cross_business_plan is None:
                raise ResourceNotFoundError("导出文件")
            result = await self._analytics.export_cross_business(
                merchant_id=merchant_id,
                plan=spec.cross_business_plan,
            )
            if tuple(column.key for column in result.columns) != spec.columns:
                raise ResourceNotFoundError("导出文件")
        elif spec.kind == "generated_metric":
            if spec.generated_metric_plan is None or spec.generated_metric_category is None:
                raise ResourceNotFoundError("导出文件")
            result = await self._analytics.generated_metric(
                merchant_id=merchant_id,
                category=spec.generated_metric_category,
                plan=spec.generated_metric_plan,
                start=spec.start,
                end=spec.end,
                limit=None,
            )
            if tuple(column.key for column in result.columns) != spec.columns:
                raise ResourceNotFoundError("导出文件")
        else:
            try:
                registered = detail_spec(spec.table)
            except UnknownFieldError as exc:
                raise ResourceNotFoundError("导出文件") from exc
            if tuple(name for name, _ in registered.columns) != spec.columns:
                raise ResourceNotFoundError("导出文件")
            result = await self._analytics.export_detail(
                merchant_id=merchant_id,
                spec=registered,
                filters=dict(spec.filters),
                start=spec.start,
                end=spec.end,
            )
        return _to_csv(result)

    async def download_from_url(self, url: str, *, now: datetime | None = None) -> str:
        parsed = urlparse(url)
        values = parse_qs(parsed.query)
        export_id = UUID(parsed.path.rsplit("/", 1)[-1])
        return await self.download(
            export_id=export_id,
            merchant_id=UUID(values["merchant_id"][0]),
            expires_at=int(values["expires_at"][0]),
            signature=values["signature"][0],
            now=now,
        )

    def _signature(self, export_id: UUID, merchant_id: UUID, expires_at: datetime) -> str:
        payload = f"{export_id}:{merchant_id}:{int(expires_at.timestamp())}".encode()
        return hmac.new(self._secret, payload, sha256).hexdigest()


def _serialize_spec(spec: ExportSpec) -> dict[str, object]:
    return {
        "table": spec.table,
        "columns": list(spec.columns),
        "start": spec.start.isoformat(),
        "end": spec.end.isoformat(),
        "filters": [list(item) for item in spec.filters],
        "date_filtered": spec.date_filtered,
        "kind": spec.kind,
        "cross_business_plan": (
            spec.cross_business_plan.model_dump() if spec.cross_business_plan is not None else None
        ),
        "generated_metric_plan": (
            spec.generated_metric_plan.model_dump()
            if spec.generated_metric_plan is not None
            else None
        ),
        "generated_metric_category": (
            spec.generated_metric_category.value
            if spec.generated_metric_category is not None
            else None
        ),
    }


def _deserialize_spec(value: dict[str, object]) -> ExportSpec:
    columns = value.get("columns")
    filters = value.get("filters", [])
    table = value.get("table")
    kind = value.get("kind", "detail")
    if (
        not isinstance(table, str)
        or not isinstance(columns, list)
        or not isinstance(filters, list)
        or kind not in {"detail", "cross_business", "generated_metric"}
    ):
        raise ValueError("invalid export specification")
    raw_plan = value.get("cross_business_plan")
    raw_generated_plan = value.get("generated_metric_plan")
    raw_generated_category = value.get("generated_metric_category")
    try:
        plan = CrossBusinessPlan.model_validate(raw_plan) if raw_plan is not None else None
        generated_plan = (
            GeneratedMetricPlan.model_validate(raw_generated_plan)
            if raw_generated_plan is not None
            else None
        )
        generated_category = (
            QuestionCategory(str(raw_generated_category))
            if raw_generated_category is not None
            else None
        )
    except ValueError as exc:
        raise ValueError("invalid export specification") from exc
    if kind == "cross_business" and plan is None:
        raise ValueError("invalid export specification")
    if kind == "generated_metric" and (
        table != "generated_metric"
        or generated_plan is None
        or generated_category not in {QuestionCategory.TRADE, QuestionCategory.REFUND}
    ):
        raise ValueError("invalid export specification")
    return ExportSpec(
        table=table,
        columns=tuple(str(column) for column in columns),
        start=date.fromisoformat(str(value["start"])),
        end=date.fromisoformat(str(value["end"])),
        filters=tuple(
            (str(item[0]), str(item[1]))
            for item in filters
            if isinstance(item, list) and len(item) == 2
        ),
        date_filtered=bool(value.get("date_filtered", True)),
        kind=cast(Literal["detail", "cross_business", "generated_metric"], kind),
        cross_business_plan=plan,
        generated_metric_plan=generated_plan,
        generated_metric_category=generated_category,
    )


def _to_csv(result: DetailResult) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    keys = [column.key for column in result.columns]
    writer.writerow([column.label for column in result.columns])
    for row in result.rows:
        writer.writerow([_csv_value(row.get(key)) for key in keys])
    return "\ufeff" + output.getvalue()


def _csv_value(value: object) -> object:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return "" if value is None else value
