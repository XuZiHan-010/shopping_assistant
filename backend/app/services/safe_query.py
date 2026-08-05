"""受控经营查询的编排层。

它决定「查什么」，Repository 决定「怎么查」。B3 的白名单在这里被第二次执行：
拿到注册表里不存在的键就拒绝，并给出可以直接展示给用户的原因——不透出表名、
列名和任何 SQL 片段。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from app.analytics.contract import (
    DETAIL_BY_CATEGORY,
    DetailSpec,
    UnknownFieldError,
    compatible_dimensions,
    detail_spec,
    dimension_spec,
    metric_spec,
)
from app.analytics.dates import FutureRangeError, resolve_range
from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.intent.whitelist import MAX_DETAIL_LIMIT
from app.repositories.analytics import AnalyticsRepository, ResultColumn
from app.schemas.chat import CATEGORY_DISPLAY_NAMES, AnswerMode

_METRIC_PREVIEW_LIMIT: Final[int] = 200


class UnsupportedQueryError(Exception):
    """请求超出受控查询范围。`reason` 可以安全展示给用户。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExportSpec:
    table: str
    columns: tuple[str, ...]
    start: date
    end: date


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[ResultColumn, ...]
    rows: list[dict[str, object]]
    total_rows: int
    truncated: bool
    source_tables: tuple[str, ...]
    plan_steps: tuple[str, ...]
    export_spec: ExportSpec | None
    notes: tuple[str, ...]
    #: True 表示结果里的指标不可跨行相加（去重计数、比例）。B5 据此避免错误求和。
    non_additive: bool


class SafeQueryService:
    def __init__(self, repository: AnalyticsRepository, *, business_timezone: str) -> None:
        self._repository = repository
        self._timezone = business_timezone

    async def execute(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        *,
        now: datetime,
    ) -> QueryResult:
        try:
            date_range, notes = resolve_range(intent.date_range, now=now, timezone=self._timezone)
        except FutureRangeError as error:
            # 整体位于未来的区间没有合法窗口可截断——这是拒绝，不是像
            # 「结束日截到今天」那样可以静默调整后继续查的越界。
            raise UnsupportedQueryError(error.reason) from error

        if intent.answer_mode is AnswerMode.DETAIL:
            return await self._detail(context, intent, date_range, notes)
        if intent.answer_mode is AnswerMode.METRIC:
            return await self._metric(context, intent, date_range, notes)
        raise UnsupportedQueryError(f"{intent.answer_mode.value} 模式不执行经营数据查询")

    async def _metric(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        date_range: DateRange,
        notes: tuple[str, ...],
    ) -> QueryResult:
        if intent.metric is None:
            raise UnsupportedQueryError("问题没有指向具体指标，无法执行经营数据查询")
        try:
            metric = metric_spec(intent.metric)
        except UnknownFieldError as error:
            raise UnsupportedQueryError(f"指标 {intent.metric} 不在可查询范围内") from error

        allowed = compatible_dimensions(metric)
        for code in intent.dimensions:
            try:
                dimension_spec(code)
            except UnknownFieldError as error:
                raise UnsupportedQueryError(f"维度 {code} 不在可查询范围内") from error
            if code not in allowed:
                raise UnsupportedQueryError(f"{metric.label} 不支持按「{code}」拆分")
        for code in intent.filters:
            if code not in allowed:
                raise UnsupportedQueryError(f"{metric.label} 不支持按「{code}」筛选")

        sort = self._checked_sort(intent.sort, metric.code, tuple(intent.dimensions))

        result = await self._repository.aggregate(
            merchant_id=context.merchant_id,
            metric=metric,
            dimensions=tuple(intent.dimensions),
            filters=dict(intent.filters),
            start=date_range.start,
            end=date_range.end,
            limit=_METRIC_PREVIEW_LIMIT,
            sort=sort,
        )
        return QueryResult(
            columns=result.columns,
            rows=result.rows,
            total_rows=len(result.rows),
            truncated=False,
            source_tables=result.source_tables,
            plan_steps=self._plan_steps(metric.label, result.source_tables, date_range, notes),
            export_spec=None,
            notes=notes,
            non_additive=not metric.additive,
        )

    async def _detail(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        date_range: DateRange,
        notes: tuple[str, ...],
    ) -> QueryResult:
        table = DETAIL_BY_CATEGORY.get(intent.category.value)
        if table is None:
            # 展示中文业务名而不是枚举码：枚举码（如 "SCM"）对商家不友好，
            # 但仍然是公开分类值，不属于表名/列名——只是可读性问题。
            category_label = CATEGORY_DISPLAY_NAMES.get(intent.category, intent.category.value)
            raise UnsupportedQueryError(f"「{category_label}」暂无可查询的经营明细")
        spec = detail_spec(table)
        self._check_detail_filters(spec, intent.filters)
        limit = min(intent.limit or MAX_DETAIL_LIMIT, MAX_DETAIL_LIMIT)

        result = await self._repository.detail(
            merchant_id=context.merchant_id,
            spec=spec,
            filters=dict(intent.filters),
            start=date_range.start,
            end=date_range.end,
            limit=limit,
        )
        return QueryResult(
            columns=result.columns,
            rows=result.rows,
            total_rows=result.total_rows,
            truncated=result.truncated,
            source_tables=result.source_tables,
            plan_steps=self._plan_steps(spec.label, result.source_tables, date_range, notes),
            export_spec=ExportSpec(
                table=spec.table,
                columns=tuple(name for name, _ in spec.columns),
                start=date_range.start,
                end=date_range.end,
            ),
            notes=notes,
            non_additive=False,
        )

    def _check_detail_filters(self, spec: DetailSpec, filters: Mapping[str, str]) -> None:
        """仓储层的 `detail()` 只对落在 `spec.table` 上的筛选生效，其余静默丢弃。

        用户加了筛选却拿到未经筛选的全量明细、还以为筛过了，比直接拒绝更危险——
        这里必须在调用仓储之前把「查不到对应字段」和「字段所属表对不上」都
        显式拦下来，不能让它们悄悄流失在仓储层。
        """

        for code in filters:
            try:
                dimension = dimension_spec(code)
            except UnknownFieldError as error:
                raise UnsupportedQueryError(f"筛选字段 {code} 不在可查询范围内") from error
            if dimension.table != spec.table:
                raise UnsupportedQueryError(f"{spec.label}不支持按「{dimension.label}」筛选")

    def _checked_sort(
        self,
        sort: str | None,
        metric_code: str,
        dimensions: tuple[str, ...],
    ) -> str | None:
        """排序键会进 ORDER BY 的标识符位置，和指标、维度是同一类风险。

        只接受本次查询已经产出的列码，前缀 `-` 表示降序。不认识的一律拒绝，
        不做「忽略掉继续查」——那样用户拿到的顺序和他要的不一样却没有提示。

        `sort` 与 `metric`/`dimensions`/`filters` 不同：B3 白名单
        （`app.intent.whitelist.validate_intent`）没有对它做任何校验，
        它可能是模型直接透传的任意字符串。拒绝原因绝不能把这个原始值
        回显出来——那样「可安全展示的拒绝原因」本身就会带着攻击者写入的
        SQL 片段和表名。
        """

        if not sort:
            return None
        key = sort.lstrip("-")
        if key != metric_code and key not in dimensions:
            raise UnsupportedQueryError("排序字段不在本次查询范围内")
        return sort

    def _plan_steps(
        self,
        subject: str,
        source_tables: tuple[str, ...],
        date_range: DateRange,
        notes: tuple[str, ...],
    ) -> tuple[str, ...]:
        """查询计划只承载可安全展示的描述，不含 SQL 与数据行。"""

        return (
            f"按商家范围检索{subject}",
            f"时间范围 {date_range.start:%Y-%m-%d} 至 {date_range.end:%Y-%m-%d}",
            f"数据来源：{'、'.join(source_tables)}",
            *notes,
        )
