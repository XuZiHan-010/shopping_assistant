"""受签名保护的动态 CSV 导出。"""

from __future__ import annotations

import csv
import hmac
import io
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Literal, Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID

from pydantic import BaseModel

from app.analytics.contract import UnknownFieldError, detail_spec
from app.core.errors import (
    ExportLinkExpiredError,
    MerchantScopeViolationError,
    ResourceNotFoundError,
)
from app.intent.models import CrossBusinessPlan, GeneratedMetricPlan
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale
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
        locale: SupportedLocale = SupportedLocale.ZH_CN,
        now: datetime | None = None,
    ) -> ExportInfo:
        """创建阶段把 `locale` 固化进 `spec` 并纳入签名（Task 8）：
        `/api/exports/{id}` 是浏览器直接打开的签名 URL，不带 `Accept-Language`，
        导出语言只能在这里、由发起下载链接的这次请求的显示语言一次性决定。"""

        spec = replace(spec, locale=locale)
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + self._ttl
        record = await self._exports.create(
            merchant_id=merchant_id,
            answer_id=answer_id,
            export_spec=_serialize_spec(spec),
            expires_at=expires_at,
        )
        signature = self._signature(record.id, merchant_id, expires_at, locale)
        query = urlencode(
            {
                "merchant_id": str(merchant_id),
                "expires_at": str(int(expires_at.timestamp())),
                "locale": str(locale),
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
        locale: SupportedLocale = SupportedLocale.ZH_CN,
        now: datetime | None = None,
    ) -> str:
        """`locale` 只用来验证签名（防止 query 里的 locale 被篡改而不被察觉），
        真正决定渲染语言的是落库 `export_spec.locale`——两者在一条未被篡改的
        签名 URL 上必然一致，见 `create()`。旧签名（创建于本字段存在之前）不带
        `locale` 查询参数，这里的默认值 `zh-CN` 让 `_signature()` 退回三段式
        旧公式,与当年签发时使用的算法完全一致，仍可下载。"""

        expiry = datetime.fromtimestamp(expires_at, tz=UTC)
        if not hmac.compare_digest(
            signature, self._signature(export_id, merchant_id, expiry, locale)
        ):
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
            _ensure_columns_unchanged(result, spec.columns)
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
            _ensure_columns_unchanged(result, spec.columns)
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
        return _to_csv(result, spec.locale)

    async def download_from_url(self, url: str, *, now: datetime | None = None) -> str:
        parsed = urlparse(url)
        values = parse_qs(parsed.query)
        export_id = UUID(parsed.path.rsplit("/", 1)[-1])
        raw_locale = values.get("locale", [None])[0]
        locale = SupportedLocale(raw_locale) if raw_locale else SupportedLocale.ZH_CN
        return await self.download(
            export_id=export_id,
            merchant_id=UUID(values["merchant_id"][0]),
            expires_at=int(values["expires_at"][0]),
            signature=values["signature"][0],
            locale=locale,
            now=now,
        )

    def _signature(
        self,
        export_id: UUID,
        merchant_id: UUID,
        expires_at: datetime,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> str:
        """`locale` 只有在非默认语言（`en-US`）时才加入签名负载。这条不对称
        规则是向后兼容的关键：`zh-CN`（含所有从未带 `locale` 查询参数的旧
        签名 URL）始终折算成与本字段引入前完全相同的三段式负载，旧链接的
        签名因此原样有效；只有 `en-US` 导出才会得到一个只在该 locale 下才
        成立的四段式签名，篡改 query 里的 `locale` 会让两种公式互不匹配而
        被拒绝（403）。"""

        parts = [str(export_id), str(merchant_id), str(int(expires_at.timestamp()))]
        if locale is not SupportedLocale.ZH_CN:
            parts.append(str(locale))
        payload = ":".join(parts).encode()
        return hmac.new(self._secret, payload, sha256).hexdigest()


def _dump_optional(model: BaseModel | None) -> dict[str, object] | None:
    return model.model_dump() if model is not None else None


def _load_optional[ModelT: BaseModel](model_cls: type[ModelT], raw: object) -> ModelT | None:
    return model_cls.model_validate(raw) if raw is not None else None


def _ensure_columns_unchanged(result: DetailResult, expected: tuple[str, ...]) -> None:
    """签名的 `ExportSpec` 只记列名；模板改过之后旧签名重放必须拒绝，而不是
    返回一份列集合已经不一致（可能被篡改过 kind/plan/category）的 CSV。"""

    if tuple(column.key for column in result.columns) != expected:
        raise ResourceNotFoundError("导出文件")


def _serialize_spec(spec: ExportSpec) -> dict[str, object]:
    return {
        "table": spec.table,
        "columns": list(spec.columns),
        "start": spec.start.isoformat(),
        "end": spec.end.isoformat(),
        "filters": [list(item) for item in spec.filters],
        "date_filtered": spec.date_filtered,
        "kind": spec.kind,
        "cross_business_plan": _dump_optional(spec.cross_business_plan),
        "generated_metric_plan": _dump_optional(spec.generated_metric_plan),
        "generated_metric_category": (
            spec.generated_metric_category.value
            if spec.generated_metric_category is not None
            else None
        ),
        "locale": str(spec.locale),
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
    try:
        plan = _load_optional(CrossBusinessPlan, value.get("cross_business_plan"))
        generated_plan = _load_optional(GeneratedMetricPlan, value.get("generated_metric_plan"))
        raw_generated_category = value.get("generated_metric_category")
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
    raw_locale = value.get("locale")
    try:
        # Legacy signed links (created before this field existed) have no
        # "locale" key; interpret as zh-CN so they remain downloadable
        # (Task 8 Step 7 backward-compatibility requirement).
        locale = SupportedLocale(str(raw_locale)) if raw_locale else SupportedLocale.ZH_CN
    except ValueError as exc:
        raise ValueError("invalid export specification") from exc
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
        locale=locale,
    )


def _to_csv(result: DetailResult, locale: SupportedLocale) -> str:
    """列名与闭集单元格值（状态码、类目、退款/退货原因、城市等）按 `locale`
    经 `localize_catalog_value()` 渲染——零 LLM，词典未命中原样保留。导出的
    数据全部来自受控经营查询（订单号、SKU、金额、日期等），不含用户生成的
    自由文本，因此不需要为渲染 CSV 触发真实模型调用。"""

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    keys = [column.key for column in result.columns]
    writer.writerow([_localized_cell(column.label, locale) for column in result.columns])
    for row in result.rows:
        writer.writerow([_csv_value(row.get(key), locale) for key in keys])
    return "\ufeff" + output.getvalue()


def _localized_cell(value: str, locale: SupportedLocale) -> str:
    return localize_catalog_value(value, locale) or value


def _csv_value(value: object, locale: SupportedLocale) -> object:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    if value is None:
        return ""
    if isinstance(value, str):
        return _localized_cell(value, locale)
    return value
