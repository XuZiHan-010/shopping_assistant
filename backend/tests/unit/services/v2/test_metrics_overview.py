"""W Task 2：首页经营主指标（`services/v2/metrics_overview.py`，契约 §8.12.4）。

用真实的 `AttributionService` 驱动一个按意图作答的假 `SafeQueryService`：
周期、归因、序列都走生产代码，只把 SQL 层换成内存事实表，因此这里验证的是
「组合方式」本身——周期与 `attribute_change` 同源、Top 5 + 其余、降级取空值、
万分比换算——而不是重复验证 SQL（那在集成测试里对真库做）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.analytics.contract import METRIC_SPECS
from app.core.errors import DatabaseUnavailableError
from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.localization.locales import SupportedLocale
from app.repositories.analytics import ResultColumn
from app.schemas.v2.merchant_ops import OverviewAttributionMode
from app.services.safe_query import QueryResult, UnsupportedQueryError
from app.services.v2.attribution import AttributionService
from app.services.v2.metrics_overview import build_metrics_overview, ratio_to_bp

MERCHANT = MerchantContext(merchant_id=UUID("00000000-0000-4000-8000-000000000101"))
TZ = "Asia/Shanghai"
# 2026-09-23 为周三；04:00 UTC = 上海 12:00，UTC 日期与业务日期一致。
WEDNESDAY = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
CURRENT_START = date(2026, 9, 21)
BASELINE_START = date(2026, 9, 14)


@dataclass(frozen=True)
class Fact:
    day: date
    category: str
    gross: Decimal = Decimal("0")
    refund: Decimal = Decimal("0")


FailRule = Callable[[QueryIntent], bool]


@dataclass
class FakeSafeQuery:
    """按意图（指标、维度、区间）从内存事实表聚合出与仓储同形的结果。"""

    facts: list[Fact] = field(default_factory=list)
    #: 标量辅助指标：(指标码, 区间起始日) → 值；缺省为 None（无数据）。
    scalars: dict[tuple[str, date], Decimal | None] = field(default_factory=dict)
    #: 对某个周期（按区间起始日）的类目毛成交额加偏差，制造「类目口径 ≠ 整体口径」。
    category_skew: dict[date, Decimal] = field(default_factory=dict)
    fail_when: list[FailRule] = field(default_factory=list)
    category_ranges: list[DateRange] = field(default_factory=list)

    async def execute(
        self, context: MerchantContext, intent: QueryIntent, *, now: datetime, keywords=()
    ) -> QueryResult:
        del context, now, keywords
        if any(rule(intent) for rule in self.fail_when):
            raise UnsupportedQueryError("数据查询失败 relation \"orders\" does not exist")
        assert intent.metric is not None and intent.date_range is not None
        metric, span = intent.metric, intent.date_range
        in_range = [f for f in self.facts if span.start <= f.day <= span.end]
        if intent.dimensions == ["category"]:
            self.category_ranges.append(span)
            rows: list[dict[str, object]] = []
            for name in sorted({f.category for f in in_range}):
                total = sum(
                    (_value(f, metric) for f in in_range if f.category == name), Decimal("0")
                )
                if metric == "gross_gmv":
                    total += self.category_skew.get(span.start, Decimal("0"))
                rows.append({"category": name, metric: total})
            return _result(metric, rows)
        if intent.dimensions == ["date"]:
            rows = []
            for day in sorted({f.day for f in in_range}):
                total = sum((_value(f, metric) for f in in_range if f.day == day), Decimal("0"))
                rows.append({"date": day, metric: total})
            return _result(metric, rows)
        return _result(metric, [{metric: self.scalars.get((metric, span.start))}])


def _value(fact: Fact, metric: str) -> Decimal:
    return fact.gross if metric == "gross_gmv" else fact.refund


def _result(metric: str, rows: list[dict[str, object]]) -> QueryResult:
    return QueryResult(
        columns=(ResultColumn(key=metric, label=metric, kind="METRIC"),),
        rows=rows,
        total_rows=len(rows),
        truncated=False,
        source_tables=(METRIC_SPECS[metric].table,),
        plan_steps=(),
        export_spec=None,
        notes=(),
        non_additive=not METRIC_SPECS[metric].additive,
    )


def _scope(fake: FakeSafeQuery):
    @asynccontextmanager
    async def scope() -> AsyncIterator[AttributionService]:
        yield AttributionService(fake)

    return scope


async def _overview(
    fake: FakeSafeQuery,
    *,
    now: datetime = WEDNESDAY,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
):
    return await build_metrics_overview(
        _scope(fake), MERCHANT, now=now, business_timezone=TZ, locale=locale
    )


def _basic_facts() -> list[Fact]:
    return [
        Fact(
            CURRENT_START + timedelta(days=1),
            "茶饮",
            gross=Decimal("300.00"),
            refund=Decimal("30.00"),
        ),
        Fact(CURRENT_START, "烘焙", gross=Decimal("100.00")),
        Fact(BASELINE_START + timedelta(days=1), "茶饮", gross=Decimal("200.00")),
        Fact(BASELINE_START, "烘焙", gross=Decimal("100.00")),
    ]


def _basic_scalars() -> dict[tuple[str, date], Decimal | None]:
    return {
        ("order_count", CURRENT_START): Decimal("2"),
        ("order_count", BASELINE_START): Decimal("2"),
        ("refund_amount", CURRENT_START): Decimal("30.00"),
        ("refund_amount", BASELINE_START): None,
        ("return_rate", CURRENT_START): Decimal("0.25"),
        ("return_rate", BASELINE_START): Decimal("0"),
    }


# ---------------------------------------------------------------------------
# 周期：与 attribute_change 同源
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "current", "baseline", "label"),
    [
        # 周一当天：本期 1 天
        (
            datetime(2026, 9, 21, 4, tzinfo=UTC),
            (date(2026, 9, 21), date(2026, 9, 21)),
            (date(2026, 9, 14), date(2026, 9, 14)),
            ("本周前 1 天", "上周前 1 天"),
        ),
        # 周中（周三）：本期 3 天
        (
            WEDNESDAY,
            (date(2026, 9, 21), date(2026, 9, 23)),
            (date(2026, 9, 14), date(2026, 9, 16)),
            ("本周前 3 天", "上周前 3 天"),
        ),
        # 周日：本期满 7 天
        (
            datetime(2026, 9, 27, 4, tzinfo=UTC),
            (date(2026, 9, 21), date(2026, 9, 27)),
            (date(2026, 9, 14), date(2026, 9, 20)),
            ("本周期", "上周前 7 天"),
        ),
        # 业务时区：UTC 周日 17:00 = 上海周一 01:00，本期应从周一算起
        (
            datetime(2026, 9, 27, 17, tzinfo=UTC),
            (date(2026, 9, 28), date(2026, 9, 28)),
            (date(2026, 9, 21), date(2026, 9, 21)),
            ("本周前 1 天", "上周前 1 天"),
        ),
    ],
    ids=["monday", "midweek", "sunday", "business-timezone"],
)
async def test_periods_are_the_same_as_attribute_change(
    now: datetime,
    current: tuple[date, date],
    baseline: tuple[date, date],
    label: tuple[str, str],
) -> None:
    fake = FakeSafeQuery(facts=_basic_facts(), scalars=_basic_scalars())

    overview = await _overview(fake, now=now)

    assert (overview.current_period.start, overview.current_period.end) == current
    assert (overview.baseline_period.start, overview.baseline_period.end) == baseline
    assert (overview.current_period.label, overview.baseline_period.label) == label
    # 归因查询实际打到的两个区间，就是响应里声明的两个周期（不另写一套周期计算）。
    net_ranges = {(r.start, r.end) for r in fake.category_ranges}
    assert net_ranges == {current, baseline}
    assert len(overview.headline.current_series) == (current[1] - current[0]).days + 1


async def test_period_labels_follow_display_locale() -> None:
    fake = FakeSafeQuery(facts=_basic_facts(), scalars=_basic_scalars())

    overview = await _overview(fake, locale=SupportedLocale.EN_US)

    assert overview.current_period.label == "First 3 days this week"
    assert overview.baseline_period.label == "First 3 days last week"


# ---------------------------------------------------------------------------
# 主指标、归因与辅助指标的确定性数字
# ---------------------------------------------------------------------------


async def test_headline_attribution_and_secondary_numbers() -> None:
    fake = FakeSafeQuery(facts=_basic_facts(), scalars=_basic_scalars())

    overview = await _overview(fake)

    headline = overview.headline
    assert headline.current_cents == 37000
    assert headline.baseline_cents == 30000
    assert [p.value_cents for p in headline.current_series] == [10000, 27000, 0]
    assert [p.value_cents for p in headline.baseline_series] == [10000, 20000, 0]
    # 7000 / 30000 = 0.23333… → 2333 bp（ROUND_HALF_UP）
    assert headline.change_ratio_bp == 2333

    attribution = overview.attribution
    assert attribution.mode is OverviewAttributionMode.SHARE
    assert [(s.name, s.contribution_cents, s.share_bp) for s in attribution.segments] == [
        ("茶饮", 7000, 10000),
        ("烘焙", 0, 0),
    ]
    assert attribution.remaining_count == 0
    assert attribution.remaining_contribution_cents == 0

    assert [(m.metric_code, m.current_value, m.baseline_value) for m in overview.secondary] == [
        ("order_count", 2, 2),
        ("refund_amount", 3000, None),  # 基期无退款行：注册表给 None，不写成 0
        ("return_rate", 2500, 0),
    ]

    assert overview.degraded is False
    assert overview.degraded_reason is None
    assert [(s.source, s.degraded) for s in overview.analysis_sources] == [("DATABASE", False)]
    assert overview.quality_status == "NOT_RUN"
    assert overview.quality_attempts == 0
    assert overview.data_as_of == WEDNESDAY
    assert overview.business_timezone == TZ
    assert overview.source == "REALTIME"


async def test_more_than_five_categories_report_remaining_not_truncated() -> None:
    facts: list[Fact] = []
    # 7 个类目：贡献依次 +700、-600、+500、+400、+300、+200、-100（元）
    for index, (name, delta) in enumerate(
        [("A", 700), ("B", -600), ("C", 500), ("D", 400), ("E", 300), ("F", 200), ("G", -100)]
    ):
        base = Decimal("1000")
        facts.append(Fact(BASELINE_START, name, gross=base))
        facts.append(Fact(CURRENT_START + timedelta(days=index % 3), name, gross=base + delta))
    fake = FakeSafeQuery(facts=facts, scalars=_basic_scalars())

    overview = await _overview(fake)

    attribution = overview.attribution
    assert [s.name for s in attribution.segments] == ["A", "B", "C", "D", "E"]
    assert attribution.remaining_count == 2
    assert attribution.remaining_contribution_cents == (200 - 100) * 100
    total = sum(s.contribution_cents for s in attribution.segments)
    assert total + attribution.remaining_contribution_cents == (
        overview.headline.current_cents - (overview.headline.baseline_cents or 0)
    )


async def test_equal_contributions_are_ordered_by_name() -> None:
    facts = [
        Fact(BASELINE_START, "乙", gross=Decimal("100")),
        Fact(BASELINE_START, "甲", gross=Decimal("100")),
        Fact(CURRENT_START, "乙", gross=Decimal("200")),
        Fact(CURRENT_START, "甲", gross=Decimal("0")),
    ]
    fake = FakeSafeQuery(facts=facts, scalars=_basic_scalars())

    overview = await _overview(fake)

    assert [s.name for s in overview.attribution.segments] == sorted(["乙", "甲"])


async def test_share_outside_contract_range_falls_back_to_absolute_contribution() -> None:
    """正负大幅抵消时占比可达上百倍，超出 share_bp 契约范围就改报绝对贡献值（D19）。"""

    facts = [
        Fact(BASELINE_START, "A", gross=Decimal("500")),
        Fact(BASELINE_START, "B", gross=Decimal("500")),
        Fact(CURRENT_START, "A", gross=Decimal("10500")),
        Fact(CURRENT_START, "B", refund=Decimal("9449")),
    ]
    fake = FakeSafeQuery(facts=facts, scalars=_basic_scalars())

    overview = await _overview(fake)

    assert overview.attribution.mode is OverviewAttributionMode.ABSOLUTE_CONTRIBUTION
    assert all(s.share_bp is None for s in overview.attribution.segments)
    assert overview.degraded is False


async def test_baseline_without_data_is_null_and_attribution_stops() -> None:
    facts = [Fact(CURRENT_START, "茶饮", gross=Decimal("100"))]
    fake = FakeSafeQuery(facts=facts, scalars=_basic_scalars())

    overview = await _overview(fake)

    assert overview.headline.current_cents == 10000
    assert overview.headline.baseline_cents is None
    assert overview.headline.baseline_series == []
    assert overview.headline.change_ratio_bp is None
    assert overview.attribution.mode is OverviewAttributionMode.STOPPED
    assert overview.attribution.segments == []
    assert overview.attribution.stopped_reason
    # 基期无数据是事实，不是查询失败：不标记降级。
    assert overview.degraded is False


async def test_non_positive_baseline_has_no_ratio() -> None:
    facts = [
        Fact(BASELINE_START, "茶饮", gross=Decimal("100"), refund=Decimal("100")),
        Fact(CURRENT_START, "茶饮", gross=Decimal("100")),
    ]
    fake = FakeSafeQuery(facts=facts, scalars=_basic_scalars())

    overview = await _overview(fake)

    assert overview.headline.baseline_cents == 0
    assert overview.headline.change_ratio_bp is None


# ---------------------------------------------------------------------------
# 降级：失败项取空值，不出现示意数字
# ---------------------------------------------------------------------------


def _baseline_series(intent: QueryIntent) -> bool:
    return intent.dimensions == ["date"] and intent.date_range.start == BASELINE_START  # type: ignore[union-attr]


def _category(intent: QueryIntent) -> bool:
    return intent.dimensions == ["category"]


def _scalar(metric: str) -> FailRule:
    return lambda intent: not intent.dimensions and intent.metric == metric


async def test_baseline_series_failure_degrades_with_null_baseline() -> None:
    fake = FakeSafeQuery(
        facts=_basic_facts(), scalars=_basic_scalars(), fail_when=[_baseline_series]
    )

    overview = await _overview(fake)

    assert overview.degraded is True
    assert overview.degraded_reason
    assert overview.headline.current_cents == 37000
    assert overview.headline.baseline_cents is None
    assert overview.headline.baseline_series == []
    assert overview.headline.change_ratio_bp is None
    assert overview.analysis_sources[0].source == "DATABASE"
    assert overview.analysis_sources[0].degraded is True


async def test_attribution_failure_stops_attribution_and_nulls_baseline() -> None:
    fake = FakeSafeQuery(facts=_basic_facts(), scalars=_basic_scalars(), fail_when=[_category])

    overview = await _overview(fake)

    assert overview.degraded is True
    assert overview.attribution.mode is OverviewAttributionMode.STOPPED
    assert overview.attribution.segments == []
    assert overview.attribution.remaining_count == 0
    assert overview.attribution.remaining_contribution_cents == 0
    reason = overview.attribution.stopped_reason or ""
    assert reason and "relation" not in reason and "orders" not in reason
    # 归因失败时无法确认基期是否有可比数据：基期取空值而不是 0。
    assert overview.headline.baseline_cents is None
    assert overview.headline.baseline_series == []


@pytest.mark.parametrize("metric", ["order_count", "refund_amount", "return_rate"])
async def test_secondary_failure_nulls_only_that_metric(metric: str) -> None:
    fake = FakeSafeQuery(
        facts=_basic_facts(), scalars=_basic_scalars(), fail_when=[_scalar(metric)]
    )

    overview = await _overview(fake)

    assert overview.degraded is True
    failed = next(m for m in overview.secondary if m.metric_code == metric)
    assert failed.current_value is None
    assert failed.baseline_value is None
    others = [m for m in overview.secondary if m.metric_code != metric]
    assert all(m.current_value is not None for m in others)
    # 其他分项不受影响
    assert overview.headline.baseline_cents == 30000
    assert overview.attribution.mode is OverviewAttributionMode.SHARE


async def test_category_total_mismatch_stops_attribution_instead_of_forcing_identity() -> None:
    fake = FakeSafeQuery(
        facts=_basic_facts(),
        scalars=_basic_scalars(),
        category_skew={CURRENT_START: Decimal("1.00")},
    )

    overview = await _overview(fake)

    assert overview.attribution.mode is OverviewAttributionMode.STOPPED
    assert overview.degraded is True
    assert overview.headline.baseline_cents == 30000


async def test_current_headline_failure_is_data_source_unavailable() -> None:
    """本期主指标没有可空的合法表示：失败时整体 503，而不是用 0 冒充。"""

    def current_series(intent: QueryIntent) -> bool:
        return intent.dimensions == ["date"] and intent.date_range.start == CURRENT_START  # type: ignore[union-attr]

    fake = FakeSafeQuery(
        facts=_basic_facts(), scalars=_basic_scalars(), fail_when=[current_series]
    )

    with pytest.raises(DatabaseUnavailableError):
        await _overview(fake)


async def test_degraded_reason_is_localized() -> None:
    fake = FakeSafeQuery(
        facts=_basic_facts(), scalars=_basic_scalars(), fail_when=[_scalar("return_rate")]
    )

    overview = await _overview(fake, locale=SupportedLocale.EN_US)

    assert overview.degraded_reason is not None
    assert overview.degraded_reason.isascii()


# ---------------------------------------------------------------------------
# return_rate：[0,1] 小数 → 万分比，Decimal + ROUND_HALF_UP，禁止经过 float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("0.20"), 2000),
        (Decimal("0"), 0),
        (Decimal("1"), 10000),
        (Decimal("0.12345"), 1235),
        (Decimal("0.00005"), 1),
        (None, None),
    ],
)
def test_ratio_to_bp(raw: Decimal | None, expected: int | None) -> None:
    assert ratio_to_bp(raw) == expected


def test_ratio_to_bp_rejects_float() -> None:
    with pytest.raises(TypeError):
        ratio_to_bp(0.2)  # type: ignore[arg-type]
