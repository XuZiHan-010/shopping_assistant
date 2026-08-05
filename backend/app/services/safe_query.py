"""受控经营查询的编排层。

它决定「查什么」，Repository 决定「怎么查」。B3 的白名单在这里被第二次执行：
拿到注册表里不存在的键就拒绝，并给出可以直接展示给用户的原因——不透出表名、
列名和任何 SQL 片段。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from app.analytics.contract import (
    DETAIL_BY_CATEGORY,
    DIMENSION_SPECS,
    REFUND_CATEGORY_REFUND_KEYWORDS,
    REFUND_CATEGORY_RETURN_KEYWORDS,
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

# 明细预览与指标预览各自独立设置：明细走 B3 的 MAX_DETAIL_LIMIT（也是导出的
# 行数上限），指标预览是本服务自己的"够画一张图/一张表"的阈值，两者取值目前
# 恰好都是 200 纯属巧合，未来任一个调整都不应该联动另一个。
_METRIC_PREVIEW_LIMIT: Final[int] = 200

#: `source_tables` 只会来自 `app.repositories.analytics._TABLES` 的键，这里
#: 穷举同一个集合，把它们翻成商家能看懂的中文说法——`plan_steps` 不允许出现
#: 英文表标识符。
_TABLE_LABELS: Final[dict[str, str]] = {
    "orders": "订单",
    "order_items": "订单明细",
    "products": "商品",
    "refunds": "退款",
    "returns": "退货",
    "support_tickets": "客服工单",
}


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
        #: 分类阶段（`app.intent.service.InitialIntent.intent_keywords`）产出的
        #: 原始关键词，仅用于 REFUND 类别内部退款/退货二次路由。可选且默认为
        #: 空——没有注入关键词的既有调用方（测试、尚未接线的路径）行为不变。
        keywords: Sequence[str] = (),
    ) -> QueryResult:
        try:
            date_range, notes = resolve_range(intent.date_range, now=now, timezone=self._timezone)
        except FutureRangeError as error:
            # 整体位于未来的区间没有合法窗口可截断——这是拒绝，不是像
            # 「结束日截到今天」那样可以静默调整后继续查的越界。
            raise UnsupportedQueryError(error.reason) from error

        if intent.answer_mode is AnswerMode.DETAIL:
            return await self._detail(context, intent, date_range, notes, keywords)
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
                dimension = dimension_spec(code)
            except UnknownFieldError as error:
                raise UnsupportedQueryError(f"维度 {code} 不在可查询范围内") from error
            if code not in allowed:
                # 用 dimension.label 而不是原始 code：好几个维度的 code 本身就
                # 等于真实列名（refund_reason、return_reason……），把它拼进
                # 「可安全展示」的拒绝原因等于泄漏了列名。
                raise UnsupportedQueryError(f"{metric.label} 不支持按「{dimension.label}」拆分")
        for code in intent.filters:
            try:
                dimension = dimension_spec(code)
            except UnknownFieldError as error:
                raise UnsupportedQueryError(f"筛选字段 {code} 不在可查询范围内") from error
            if code not in allowed:
                raise UnsupportedQueryError(f"{metric.label} 不支持按「{dimension.label}」筛选")

        sort = self._checked_sort(intent.sort, metric.code, tuple(intent.dimensions))

        # 多取一行来探测是否被截断：仓储不返回总数，"要一行、比一下" 是不改
        # AnalyticsRepository.aggregate() 签名/返回结构就能拿到截断信号的
        # 唯一办法——按 product 这类高基数维度拆分时，200 条上限很容易真的
        # 被打满，这里不能像之前那样一律汇报 truncated=False。
        result = await self._repository.aggregate(
            merchant_id=context.merchant_id,
            metric=metric,
            dimensions=tuple(intent.dimensions),
            filters=dict(intent.filters),
            start=date_range.start,
            end=date_range.end,
            limit=_METRIC_PREVIEW_LIMIT + 1,
            sort=sort,
        )
        truncated = len(result.rows) > _METRIC_PREVIEW_LIMIT
        rows = result.rows[:_METRIC_PREVIEW_LIMIT] if truncated else result.rows
        return QueryResult(
            columns=result.columns,
            rows=rows,
            total_rows=len(rows),
            truncated=truncated,
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
        keywords: Sequence[str],
    ) -> QueryResult:
        table = DETAIL_BY_CATEGORY.get(intent.category.value)
        if table == "refunds":
            # REFUND 分类本身覆盖退款（资金）与退货（货品）两件事，计划稿
            # 曾经把它写死路由到 refunds、导致 returns 表永远查不到——这里
            # 按信号可靠性从高到低再判一次，判不出来就维持原有兜底行为。
            table = self._resolve_refund_table(intent, keywords)
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

    def _resolve_refund_table(self, intent: QueryIntent, keywords: Sequence[str]) -> str:
        """REFUND 分类内部再分流到 `returns`（退货）或 `refunds`（退款）。

        PRD 明确退款是资金动作、退货是货品动作，二者可以单独发生，不能混淆；
        但 B3 的分类粒度只到 REFUND 这一级，两者都挂在同一个分类下。信号按
        可靠性从高到低取，命中就返回，不叠加判断：

        1. 维度/筛选字段落在哪张表就查哪张——用户已经明确说了要按什么筛选，
           这是最强信号，且直接复用 `DIMENSION_SPECS` 注册表，不需要新词表；
        2. 分类阶段产出的关键词（`intent_keywords`）命中"退货"或"退款"；
        3. 两种信号都没有时维持既有兜底行为（查 refunds），不去猜——猜错了
           商家会把退款明细当成退货明细看，比"查不到"更危险。
        """

        codes = (*intent.dimensions, *intent.filters)
        tables = {DIMENSION_SPECS[code].table for code in codes if code in DIMENSION_SPECS}
        if "returns" in tables:
            return "returns"
        if "refunds" in tables:
            return "refunds"

        if _keywords_mention(keywords, REFUND_CATEGORY_RETURN_KEYWORDS):
            return "returns"
        if _keywords_mention(keywords, REFUND_CATEGORY_REFUND_KEYWORDS):
            return "refunds"

        return "refunds"

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
        """查询计划只承载可安全展示的描述，不含 SQL 与数据行。

        `source_tables` 是 SQLAlchemy 的表名，不能直接拼进给商家看的中文
        句子——用 `_TABLE_LABELS` 换成业务说法。
        """

        sources = "、".join(_TABLE_LABELS.get(table, table) for table in source_tables)
        return (
            f"按商家范围检索{subject}",
            f"时间范围 {date_range.start:%Y-%m-%d} 至 {date_range.end:%Y-%m-%d}",
            f"数据来源：{sources}",
            *notes,
        )


def _keywords_mention(keywords: Sequence[str], markers: frozenset[str]) -> bool:
    """任一关键词包含任一标记子串就算命中——分类阶段产出的是自由词，不是枚举值。"""

    return any(marker in keyword for keyword in keywords for marker in markers)
