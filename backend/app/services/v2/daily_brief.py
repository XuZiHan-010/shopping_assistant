"""最小当日简报（PRD §15 N2 裁定，契约 §8.12.1、§8.12.2）。

**不调用 LLM**：条目只来自两个确定性来源——库存告警与待批准草稿。因此
`analysis_sources` 只填 `DATABASE`，`quality_status` 是 `NOT_RUN`，`degraded=false`。
把规则兜底说成模型分析是 R7 明令禁止的，这里宁可信息少也不加修饰。

N3 的 `n3-merchant-skills` 在同一个响应结构上扩展为完整 M2（多来源、金额排序、
LLM 叙述、限流重新生成），字段不变，只是来源与条目变多。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

from app.models.drafts import Draft
from app.models.memory_v2 import CustomerSignal as SignalRow
from app.schemas.chat import QualityStatus
from app.schemas.v2.common import AnalysisSourceEntry
from app.schemas.v2.merchant_ops import (
    MAX_BRIEF_ITEMS,
    DailyBriefItem,
    DailyBriefItemKind,
    DailyBriefResponse,
    InventoryAlert,
    InventoryAlertKind,
)

#: 演示商家的营业时区；N3 接入按商家配置的时区后从商家资料读取。
DEFAULT_BUSINESS_TIMEZONE: Final = "Asia/Shanghai"
#: 最小简报没有版本替换（不重新生成），恒为第 1 版。
MINIMAL_BRIEF_VERSION: Final = 1
#: D18⑨：重新生成冷却窗口——同一商家同一营业日两次重新生成之间至少间隔这么多秒；
#: 冷却期内的请求返回 429，不产生新版本，也不调用任何工具或模型（重试不产生副作用）。
REGENERATE_COOLDOWN_SECONDS: Final = 60

_ALERT_TITLE: Final = {
    InventoryAlertKind.OUT_OF_STOCK: "已售罄：{name}",
    InventoryAlertKind.LOW_STOCK: "库存偏低：{name}",
    InventoryAlertKind.SLOW_MOVING: "动销缓慢：{name}",
}


def build_minimal_brief(
    *,
    alerts: list[InventoryAlert],
    drafts: list[Draft],
    now: datetime,
    timezone: str = DEFAULT_BUSINESS_TIMEZONE,
) -> DailyBriefResponse:
    items = [*_alert_items(alerts), *_draft_items(drafts)]
    visible = items[:MAX_BRIEF_ITEMS]
    return DailyBriefResponse(
        analysis_sources=[
            AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None)
        ],
        thinking_steps=[],
        quality_status=QualityStatus.NOT_RUN,
        quality_attempts=0,
        quality_notes=[],
        degraded=False,
        degraded_reason=None,
        brief_version=MINIMAL_BRIEF_VERSION,
        business_date=_business_date(now, timezone),
        business_timezone=timezone,
        # 条目全部由本次请求现算，数据截至时间就是本次查询时刻。
        data_as_of=now,
        generated_at=now,
        trigger="SCHEDULED",
        items=[item.model_copy(update={"rank": index}) for index, item in enumerate(visible, 1)],
        collapsed_count=max(0, len(items) - len(visible)),
    )


def _business_date(now: datetime, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def business_date_for(now: datetime, *, timezone: str = DEFAULT_BUSINESS_TIMEZONE) -> date:
    """读写简报统一使用的营业日键。"""

    return _business_date(now, timezone)


def is_in_regenerate_cooldown(last_generated_at: datetime | None, *, now: datetime) -> bool:
    """D18⑨：距上次生成不足 `REGENERATE_COOLDOWN_SECONDS` 秒时在冷却期内。

    从未生成过（`None`）不算冷却——冷却限制的是"重复"重新生成，不是首次生成。
    冷却窗口边界本身（恰好等于 `REGENERATE_COOLDOWN_SECONDS` 秒）算冷却已经结束，
    不算仍在冷却内，避免因为时钟精度差 1 毫秒就被多算一次拒绝。
    """

    if last_generated_at is None:
        return False
    elapsed = (now - last_generated_at).total_seconds()
    return elapsed < REGENERATE_COOLDOWN_SECONDS


@dataclass(frozen=True)
class BriefCandidate:
    """排序前的简报候选条目；比 `DailyBriefItem` 多一个 `deadline`（排序用，不进最终响应）。"""

    kind: str
    title: str
    evidence: str
    amount_cents: int | None
    next_action_prompt: str | None
    deadline: datetime | None = None


def rank_brief_items(candidates: list[BriefCandidate], *, now: datetime) -> list[DailyBriefItem]:
    """D18③：金额为主排序；硬时限可置顶；金额未知不自动排到末尾。

    三组，依次排列：① 有硬时限的，按紧急程度排（距 `now` 的剩余时间，已过期视为最紧急，
    排在最前）；② 金额未知的，保持原始相对顺序（不参与金额竞争，也不被沉底——
    紧跟在有时限的条目之后）；③ 金额已知的，按金额降序排在最后。
    """

    with_deadline = sorted(
        (c for c in candidates if c.deadline is not None), key=lambda c: c.deadline  # type: ignore[arg-type,return-value]
    )
    unknown_amount = [c for c in candidates if c.deadline is None and c.amount_cents is None]
    known_amount = sorted(
        (c for c in candidates if c.deadline is None and c.amount_cents is not None),
        key=lambda c: c.amount_cents,  # type: ignore[arg-type,return-value]
        reverse=True,
    )
    ordered = [*with_deadline, *unknown_amount, *known_amount]
    return [
        DailyBriefItem(
            rank=index, kind=DailyBriefItemKind(c.kind), title=c.title, evidence=c.evidence,
            amount_cents=c.amount_cents, next_action_prompt=c.next_action_prompt,
        )
        for index, c in enumerate(ordered, 1)
    ]


def _alert_items(alerts: list[InventoryAlert]) -> list[DailyBriefItem]:
    return [
        DailyBriefItem(
            rank=1,  # 排名在汇总时统一重排，这里只占位。
            kind=DailyBriefItemKind.INVENTORY_ALERT,
            title=_ALERT_TITLE[alert.kind].format(name=alert.product_name),
            evidence=_alert_evidence(alert),
            amount_cents=None,  # 库存告警本身不涉及金额，不编造一个数字来排序。
            next_action_prompt=f"给「{alert.product_name}」起草一份补货草稿",
        )
        for alert in alerts
    ]


def _alert_evidence(alert: InventoryAlert) -> str:
    supply = (
        "近 30 天无销量，可售天数未知"
        if alert.days_of_supply is None
        else f"近 30 天售出 {alert.sold_last_30d} 件，约可支撑 {alert.days_of_supply} 天"
    )
    return (
        f"商品 {alert.product_id}：在库 {alert.stock_on_hand}、占用 {alert.stock_reserved}、"
        f"可售 {alert.stock_available}（阈值 {alert.low_stock_threshold}）；{supply}"
    )


_SIGNAL_TITLE: Final = {
    "RETURN_REQUESTS": "退货申请较多：{name}",
    "REFUND_REQUESTS": "仅退款申请较多：{name}",
    "SUPPORT_TICKETS": "客服工单较多：{name}",
    "CONTENT_GAP": "商品资料有缺口：{name}",
}


def build_full_brief(
    *,
    alerts: list[InventoryAlert],
    drafts: list[Draft],
    signals: list[SignalRow],
    now: datetime,
    timezone: str = DEFAULT_BUSINESS_TIMEZONE,
    brief_version: int = MINIMAL_BRIEF_VERSION,
    trigger: Literal["SCHEDULED", "REGENERATED"] = "SCHEDULED",
) -> DailyBriefResponse:
    """完整简报（PRD M2、D18）：库存告警 + 待批草稿 + 顾客信号三源汇总。

    **不含 `METRIC_CHANGE`**（指标异常变化）——需要新设计异常阈值规则，本次不实现
    （2026-09-26 裁定，见本模块单测文件头部说明）。正文完全由确定性文本拼接组织，
    不引入任何真实或模拟 LLM 调用（同 N2 最小简报的方法一致，避免把规则兜底包装成
    模型分析，R7）。

    `trigger` 由调用方（路由层）决定：首次生成传 `"SCHEDULED"`，
    经 `regenerate` 端点重新生成传 `"REGENERATED"`。
    """

    candidates = [
        *_alert_candidates(alerts), *_draft_candidates(drafts), *_signal_candidates(signals),
    ]
    items = rank_brief_items(candidates, now=now)
    visible = items[:MAX_BRIEF_ITEMS]
    return DailyBriefResponse(
        analysis_sources=[
            AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None)
        ],
        thinking_steps=[],
        quality_status=QualityStatus.NOT_RUN,
        quality_attempts=0,
        quality_notes=[],
        degraded=False,
        degraded_reason=None,
        brief_version=brief_version,
        business_date=_business_date(now, timezone),
        business_timezone=timezone,
        data_as_of=now,
        generated_at=now,
        trigger=trigger,
        items=[item.model_copy(update={"rank": index}) for index, item in enumerate(visible, 1)],
        collapsed_count=max(0, len(items) - len(visible)),
    )


def _alert_candidates(alerts: list[InventoryAlert]) -> list[BriefCandidate]:
    return [
        BriefCandidate(
            kind=DailyBriefItemKind.INVENTORY_ALERT.value,
            title=_ALERT_TITLE[alert.kind].format(name=alert.product_name),
            evidence=_alert_evidence(alert),
            amount_cents=None,  # 库存告警本身不涉及金额，不编造一个数字来排序。
            next_action_prompt=f"给「{alert.product_name}」起草一份补货草稿",
            deadline=None,  # 库存本身没有硬时限；紧急程度已体现在告警种类里。
        )
        for alert in alerts
    ]


def _draft_candidates(drafts: list[Draft]) -> list[BriefCandidate]:
    return [
        BriefCandidate(
            kind=DailyBriefItemKind.PENDING_DRAFT.value,
            title=f"待批准：{draft.title}",
            evidence=(
                f"草稿 {draft.id}：{draft.kind}，"
                f"第 {draft.draft_version} 版，"
                f"{draft.expires_at.astimezone(UTC).date().isoformat()} 过期"
            ),
            amount_cents=None,
            next_action_prompt="到审批界面查看这份草稿的改动明细",
            deadline=draft.expires_at,  # 草稿过期即失效，天然的硬时限（D18③）。
        )
        for draft in drafts
    ]


def _signal_candidates(signals: list[SignalRow]) -> list[BriefCandidate]:
    return [
        BriefCandidate(
            kind=DailyBriefItemKind.CUSTOMER_SIGNAL.value,
            title=_SIGNAL_TITLE[signal.kind].format(name=signal.product_name or "多个商品"),
            # 只报聚合计数，不带顾客标识或提问原文（D18⑦）。
            evidence=f"近期累计 {signal.count} 次，最近一次 {signal.signal_date.isoformat()}",
            amount_cents=None,
            next_action_prompt=(
                f"看看「{signal.product_name}」的信号详情，需要的话让 Agent 处理"
                if signal.product_name
                else "看看信号列表，需要的话让 Agent 处理"
            ),
            deadline=None,
        )
        for signal in signals
    ]


def _draft_items(drafts: list[Draft]) -> list[DailyBriefItem]:
    return [
        DailyBriefItem(
            rank=1,
            kind=DailyBriefItemKind.PENDING_DRAFT,
            title=f"待批准：{draft.title}",
            evidence=(
                f"草稿 {draft.id}：{draft.kind}，"
                f"第 {draft.draft_version} 版，"
                f"{draft.expires_at.astimezone(UTC).date().isoformat()} 过期"
            ),
            amount_cents=None,
            # 只指向已有能力：审批在工作台完成，这里不引导「让我批准」。
            next_action_prompt="到审批界面查看这份草稿的改动明细",
        )
        for draft in drafts
    ]
