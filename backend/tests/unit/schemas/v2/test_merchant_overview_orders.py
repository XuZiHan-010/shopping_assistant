"""首页经营主指标与商家订单只读面的传输边界（§8.12.4），不访问数据库或模型。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2.common import MAX_MONEY_CENTS
from app.schemas.v2.merchant_ops import (
    MerchantMetricsOverviewResponse,
    OverviewAttribution,
    OverviewHeadline,
    OverviewMetricPoint,
    OverviewPeriod,
    OverviewSecondaryMetric,
)
from app.schemas.v2.trade import MerchantOrderDetailResponse, MerchantOrderSummary

T0 = "2026-09-21T00:00:00Z"


def degradation(**changes: object) -> dict[str, object]:
    return {
        "analysis_sources": [{"source": "DATABASE", "degraded": False, "degraded_reason": None}],
        "quality_status": "NOT_RUN",
        "quality_attempts": 0,
        "degraded": False,
        "degraded_reason": None,
        **changes,
    }


def period(**changes: object) -> dict[str, object]:
    return {
        "start": "2026-09-21",
        "end": "2026-09-23",
        "label": "本周前 3 天",
        **changes,
    }


def point(day: str, value: int) -> dict[str, object]:
    return {"date": day, "value_cents": value}


def headline(**changes: object) -> dict[str, object]:
    return {
        "metric_code": "net_gmv",
        "current_cents": 300,
        "baseline_cents": 200,
        "change_ratio_bp": 5000,
        "current_series": [
            point("2026-09-21", 100),
            point("2026-09-22", 100),
            point("2026-09-23", 100),
        ],
        "baseline_series": [
            point("2026-09-14", 60),
            point("2026-09-15", 70),
            point("2026-09-16", 70),
        ],
        **changes,
    }


def segment(**changes: object) -> dict[str, object]:
    return {
        "name": "生鲜",
        "current_cents": 200,
        "baseline_cents": 150,
        "contribution_cents": 50,
        "share_bp": 5000,
        **changes,
    }


def attribution(**changes: object) -> dict[str, object]:
    return {
        "dimension": "category",
        "mode": "SHARE",
        "segments": [segment()],
        "remaining_count": 0,
        "remaining_contribution_cents": 50,
        "stopped_reason": None,
        **changes,
    }


def secondary_metric(**changes: object) -> dict[str, object]:
    return {
        "metric_code": "order_count",
        "unit": "COUNT",
        "current_value": 10,
        "baseline_value": 8,
        **changes,
    }


def secondary(**changes: object) -> list[dict[str, object]]:
    metrics = [
        secondary_metric(metric_code="order_count", unit="COUNT"),
        secondary_metric(metric_code="refund_amount", unit="CENTS"),
        secondary_metric(metric_code="return_rate", unit="RATIO_BP"),
    ]
    if changes:
        metrics[0] = {**metrics[0], **changes}
    return metrics


def overview(**changes: object) -> dict[str, object]:
    return {
        **degradation(),
        "business_timezone": "Asia/Shanghai",
        "data_as_of": T0,
        "source": "REALTIME",
        "definition_version": "v1",
        "current_period": period(),
        "baseline_period": period(
            start="2026-09-14", end="2026-09-16", label="上周同期前 3 天"
        ),
        "headline": headline(),
        "attribution": attribution(),
        "secondary": secondary(),
        **changes,
    }


def lead_item(**changes: object) -> dict[str, object]:
    return {"product_id": "p1", "name": "商品", "image_url": None, **changes}


def order_summary(**changes: object) -> dict[str, object]:
    return {
        "id": "o1",
        "payment_status": "PAID",
        "fulfillment_status": "NOT_SHIPPED",
        "after_sale_status": "NONE",
        "total_cents": 100,
        "item_count": 1,
        "created_at": T0,
        "pay_by": "2026-09-21T00:30:00Z",
        "lead_item": lead_item(),
        "last_event_at": T0,
        "buyer_alias": "买家1234",
        "line_count": 1,
        **changes,
    }


def price_snapshot(**changes: object) -> dict[str, object]:
    return {
        "order_item_id": "oi1",
        "product_id": "p1",
        "name": "商品",
        "quantity": 1,
        "unit_price_cents": 100,
        "discount_cents": 0,
        "line_total_cents": 100,
        **changes,
    }


def order_detail(**changes: object) -> dict[str, object]:
    base = order_summary()
    del base["line_count"]
    return {
        **base,
        "items": [price_snapshot()],
        "subtotal_cents": 100,
        "discount_cents": 0,
        "coupon_id": None,
        "paid_at": T0,
        "closed_at": None,
        "close_reason": None,
        "is_demo": True,
        **changes,
    }


# ---------------------------------------------------------------------------
# SignedMoneyCents 上下界
# ---------------------------------------------------------------------------


class TestSignedMoneyCents:
    def test_accepts_negative_value(self) -> None:
        model = OverviewMetricPoint.model_validate(point("2026-09-21", -100))
        assert model.value_cents == -100

    def test_rejects_below_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            OverviewMetricPoint.model_validate(point("2026-09-21", -(MAX_MONEY_CENTS + 1)))

    def test_rejects_above_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            OverviewMetricPoint.model_validate(point("2026-09-21", MAX_MONEY_CENTS + 1))

    def test_accepts_exact_bounds(self) -> None:
        assert OverviewMetricPoint.model_validate(
            point("2026-09-21", MAX_MONEY_CENTS)
        ).value_cents == MAX_MONEY_CENTS
        assert OverviewMetricPoint.model_validate(
            point("2026-09-21", -MAX_MONEY_CENTS)
        ).value_cents == -MAX_MONEY_CENTS

    def test_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            OverviewMetricPoint.model_validate(point("2026-09-21", 1.5))


# ---------------------------------------------------------------------------
# headline 求和一致性与 change_ratio_bp 为 null 的条件
# ---------------------------------------------------------------------------


class TestOverviewHeadline:
    def test_valid_headline(self) -> None:
        model = OverviewHeadline.model_validate(headline())
        assert model.current_cents == 300

    def test_rejects_current_sum_mismatch(self) -> None:
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(headline(current_cents=999))

    def test_rejects_baseline_sum_mismatch(self) -> None:
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(headline(baseline_cents=999))

    def test_baseline_series_must_match_current_series_length(self) -> None:
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(
                headline(baseline_series=[point("2026-09-14", 300)])
            )

    def test_change_ratio_bp_must_be_null_when_baseline_is_null(self) -> None:
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(
                headline(
                    baseline_cents=None,
                    baseline_series=[],
                    change_ratio_bp=5000,
                )
            )

    def test_change_ratio_bp_null_when_baseline_non_positive(self) -> None:
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(
                headline(baseline_cents=0, change_ratio_bp=5000)
            )

    def test_change_ratio_bp_may_be_null_with_valid_baseline(self) -> None:
        model = OverviewHeadline.model_validate(headline(change_ratio_bp=None))
        assert model.change_ratio_bp is None

    def test_baseline_series_empty_when_baseline_cents_null(self) -> None:
        model = OverviewHeadline.model_validate(
            headline(baseline_cents=None, baseline_series=[], change_ratio_bp=None)
        )
        assert model.baseline_series == []

    def test_change_ratio_bp_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(headline(change_ratio_bp=1_000_001))
        with pytest.raises(ValidationError):
            OverviewHeadline.model_validate(headline(change_ratio_bp=-1_000_001))


# ---------------------------------------------------------------------------
# 归因：STOPPED 时 segments 为空；贡献与剩余合计恒等式；最多 5 项
# ---------------------------------------------------------------------------


class TestOverviewAttribution:
    def test_valid_attribution(self) -> None:
        model = OverviewAttribution.model_validate(attribution())
        assert model.mode == "SHARE"

    def test_stopped_requires_empty_segments(self) -> None:
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(
                attribution(mode="STOPPED", stopped_reason="数据源暂时不可用")
            )

    def test_stopped_requires_stopped_reason(self) -> None:
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(
                attribution(mode="STOPPED", segments=[], stopped_reason=None)
            )

    def test_stopped_valid(self) -> None:
        model = OverviewAttribution.model_validate(
            attribution(mode="STOPPED", segments=[], stopped_reason="数据源暂时不可用")
        )
        assert model.segments == []

    def test_non_stopped_stopped_reason_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(attribution(stopped_reason="不应出现"))

    def test_segments_max_five(self) -> None:
        segments = [
            segment(
                name=f"类目{i}",
                current_cents=20 - i,
                baseline_cents=10,
                contribution_cents=10 - i,
                share_bp=1000,
            )
            for i in range(6)
        ]
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(
                attribution(segments=segments, remaining_contribution_cents=0)
            )

    def test_segments_exactly_five_allowed(self) -> None:
        segments = [
            segment(
                name=f"类目{i}",
                current_cents=20 - i,
                baseline_cents=10,
                contribution_cents=10 - i,
                share_bp=1000,
            )
            for i in range(5)
        ]
        total_contribution = sum(s["contribution_cents"] for s in segments)
        model = OverviewAttribution.model_validate(
            attribution(segments=segments, remaining_contribution_cents=0)
        )
        assert len(model.segments) == 5
        assert sum(s.contribution_cents for s in model.segments) == total_contribution

    def test_share_bp_null_required_outside_share_mode(self) -> None:
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(
                attribution(
                    mode="ABSOLUTE_CONTRIBUTION",
                    segments=[segment(share_bp=5000)],
                )
            )

    def test_share_bp_non_null_allowed_in_absolute_contribution_when_null(self) -> None:
        model = OverviewAttribution.model_validate(
            attribution(mode="ABSOLUTE_CONTRIBUTION", segments=[segment(share_bp=None)])
        )
        assert model.segments[0].share_bp is None

    def test_share_bp_required_in_share_mode(self) -> None:
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(
                attribution(mode="SHARE", segments=[segment(share_bp=None)])
            )

    def test_remaining_count_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            OverviewAttribution.model_validate(attribution(remaining_count=-1))


# ---------------------------------------------------------------------------
# secondary 恰好 3 项，顺序与单位映射固定
# ---------------------------------------------------------------------------


class TestOverviewSecondary:
    def test_unit_mapping_fixed(self) -> None:
        assert OverviewSecondaryMetric.model_validate(
            secondary_metric(metric_code="order_count", unit="COUNT")
        )
        assert OverviewSecondaryMetric.model_validate(
            secondary_metric(metric_code="refund_amount", unit="CENTS")
        )
        assert OverviewSecondaryMetric.model_validate(
            secondary_metric(metric_code="return_rate", unit="RATIO_BP")
        )

    def test_rejects_mismatched_unit(self) -> None:
        with pytest.raises(ValidationError):
            OverviewSecondaryMetric.model_validate(
                secondary_metric(metric_code="order_count", unit="CENTS")
            )
        with pytest.raises(ValidationError):
            OverviewSecondaryMetric.model_validate(
                secondary_metric(metric_code="refund_amount", unit="RATIO_BP")
            )
        with pytest.raises(ValidationError):
            OverviewSecondaryMetric.model_validate(
                secondary_metric(metric_code="return_rate", unit="COUNT")
            )

    def test_rejects_unregistered_metric_code(self) -> None:
        with pytest.raises(ValidationError):
            OverviewSecondaryMetric.model_validate(
                secondary_metric(metric_code="average_order_value", unit="CENTS")
            )

    def test_null_means_no_data_not_zero(self) -> None:
        model = OverviewSecondaryMetric.model_validate(
            secondary_metric(current_value=None, baseline_value=None)
        )
        assert model.current_value is None
        assert model.baseline_value is None


class TestMerchantMetricsOverviewResponse:
    def test_valid_overview(self) -> None:
        model = MerchantMetricsOverviewResponse.model_validate(overview())
        assert model.headline.metric_code == "net_gmv"
        assert len(model.secondary) == 3

    def test_rejects_extra_field(self) -> None:
        with pytest.raises(ValidationError):
            MerchantMetricsOverviewResponse.model_validate(overview(extra_field="x"))

    def test_secondary_must_have_exactly_three_items(self) -> None:
        with pytest.raises(ValidationError):
            MerchantMetricsOverviewResponse.model_validate(
                overview(secondary=secondary()[:2])
            )

    def test_secondary_order_fixed(self) -> None:
        reordered = list(reversed(secondary()))
        with pytest.raises(ValidationError):
            MerchantMetricsOverviewResponse.model_validate(overview(secondary=reordered))

    def test_secondary_codes_must_not_duplicate(self) -> None:
        dup = [secondary_metric(metric_code="order_count", unit="COUNT")] * 3
        with pytest.raises(ValidationError):
            MerchantMetricsOverviewResponse.model_validate(overview(secondary=dup))

    def test_start_must_not_exceed_end(self) -> None:
        with pytest.raises(ValidationError):
            OverviewPeriod.model_validate(period(start="2026-09-23", end="2026-09-21"))

    def test_period_span_within_seven_days(self) -> None:
        with pytest.raises(ValidationError):
            OverviewPeriod.model_validate(period(start="2026-09-01", end="2026-09-10"))

    def test_attribution_identity_holds_against_headline(self) -> None:
        # headline.current(300) - headline.baseline(200) = 100；
        # 默认 attribution 的单个分项贡献 50 + remaining_contribution_cents 50 = 100，恒等式成立。
        model = MerchantMetricsOverviewResponse.model_validate(overview())
        segment_total = sum(s.contribution_cents for s in model.attribution.segments)
        assert segment_total + model.attribution.remaining_contribution_cents == (
            model.headline.current_cents - model.headline.baseline_cents
        )

    def test_attribution_identity_violation_rejected(self) -> None:
        # remaining_contribution_cents 改为 0 后，50 + 0 = 50 ≠ 100，跨对象恒等式必须拒绝。
        with pytest.raises(ValidationError):
            MerchantMetricsOverviewResponse.model_validate(
                overview(attribution=attribution(remaining_contribution_cents=0))
            )

    def test_attribution_identity_skipped_when_baseline_missing(self) -> None:
        # baseline_cents=None（非 STOPPED）时恒等式右侧无法计算，语义留给 Task 2 服务层判定，
        # schema 层不强行校验，也不应报错拒绝。
        model = MerchantMetricsOverviewResponse.model_validate(
            overview(
                headline=headline(baseline_cents=None, baseline_series=[], change_ratio_bp=None)
            )
        )
        assert model.headline.baseline_cents is None

    def test_attribution_identity_skipped_when_stopped(self) -> None:
        # mode=STOPPED 时 segments 恒为空，恒等式不适用，同样不校验。
        model = MerchantMetricsOverviewResponse.model_validate(
            overview(
                attribution=attribution(
                    mode="STOPPED",
                    segments=[],
                    remaining_contribution_cents=0,
                    stopped_reason="数据源暂时不可用",
                )
            )
        )
        assert model.attribution.mode == "STOPPED"


# ---------------------------------------------------------------------------
# MerchantOrderSummary 必须有 buyer_alias，拒绝 buyer_key 等额外字段
# ---------------------------------------------------------------------------


class TestMerchantOrderSummary:
    def test_requires_buyer_alias(self) -> None:
        payload = order_summary()
        del payload["buyer_alias"]
        with pytest.raises(ValidationError):
            MerchantOrderSummary.model_validate(payload)

    def test_valid_summary_has_buyer_alias(self) -> None:
        model = MerchantOrderSummary.model_validate(order_summary())
        assert model.buyer_alias == "买家1234"
        assert model.line_count == 1

    def test_rejects_buyer_key_field(self) -> None:
        with pytest.raises(ValidationError):
            MerchantOrderSummary.model_validate(order_summary(buyer_key="raw-buyer-key"))

    def test_rejects_arbitrary_extra_field(self) -> None:
        with pytest.raises(ValidationError):
            MerchantOrderSummary.model_validate(order_summary(first_item_name="首件商品"))

    def test_inherits_lead_item_and_last_event_at(self) -> None:
        model = MerchantOrderSummary.model_validate(order_summary())
        assert model.lead_item.product_id == "p1"
        assert model.last_event_at is not None

    def test_line_count_range(self) -> None:
        with pytest.raises(ValidationError):
            MerchantOrderSummary.model_validate(order_summary(line_count=0))
        with pytest.raises(ValidationError):
            MerchantOrderSummary.model_validate(order_summary(line_count=51))


class TestMerchantOrderDetailResponse:
    def test_requires_buyer_alias(self) -> None:
        payload = order_detail()
        del payload["buyer_alias"]
        with pytest.raises(ValidationError):
            MerchantOrderDetailResponse.model_validate(payload)

    def test_valid_detail_has_buyer_alias(self) -> None:
        model = MerchantOrderDetailResponse.model_validate(order_detail())
        assert model.buyer_alias == "买家1234"

    def test_rejects_buyer_key_field(self) -> None:
        with pytest.raises(ValidationError):
            MerchantOrderDetailResponse.model_validate(order_detail(buyer_key="raw-buyer-key"))

    def test_inherits_order_detail_invariants(self) -> None:
        with pytest.raises(ValidationError):
            MerchantOrderDetailResponse.model_validate(order_detail(subtotal_cents=999))
