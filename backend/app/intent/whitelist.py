"""不可变白名单与意图校验。

这些公开指标、维度和筛选字段与 B4 的受控 SQL 模板共享契约；B4 仍必须
再次执行模板级白名单校验，不能把本层当成唯一防线。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from app.intent.models import DateRange, QueryIntent
from app.schemas.chat import AnswerMode, QuestionCategory

MAX_QUERY_DAYS: Final[int] = 180
MAX_DETAIL_LIMIT: Final[int] = 200

METRIC_WHITELIST: Final[frozenset[str]] = frozenset(
    {
        "gmv",
        "order_count",
        "paying_user_count",
        "successful_order_count",
        "refund_count",
        "refund_amount",
        "return_count",
        "return_rate",
        "support_ticket_count",
    }
)
DIMENSION_WHITELIST: Final[frozenset[str]] = frozenset(
    {
        "date",
        "product",
        "category",
        "order_status",
        "refund_reason",
        "return_reason",
        "return_status",
        "ticket_status",
    }
)
FILTER_WHITELIST: Final[frozenset[str]] = DIMENSION_WHITELIST

_SQL_PATTERN = re.compile(
    r"\b(select|insert|update|delete|drop|union|from|where|join)\b", re.IGNORECASE
)
_METRIC_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class IntentValidation:
    intent: QueryIntent
    rejected: tuple[str, ...]
    adjusted: tuple[str, ...]


def validate_intent(intent: QueryIntent, *, today: date) -> IntentValidation:
    """拒绝不安全字段，并在后端强制收缩日期范围和返回行数。

    ``today`` 由调用方注入而不是在这里读时钟：业务日界按 `Asia/Shanghai` 计算，
    且跨零点行为需要冻结时钟才能测试。
    """

    rejected: list[str] = []
    adjusted: list[str] = []
    generated_plan_invalid = intent.generated_metric_plan_rejected
    if intent.cross_business_plan_rejected:
        adjusted.append("LLM 跨业务计划缺少安全路由参数，已拒绝该计划并按普通查询处理")
    if intent.generated_metric_plan_rejected:
        rejected.append("LLM 临时分组指标计划不符合受控白名单，拒绝执行")
    data = intent.model_dump()

    # 下方 `if rejected: data["answer_mode"] = AnswerMode.INVALID` 已经覆盖
    # `generated_metric_plan_rejected` 的情况，这里不重复设置 answer_mode。
    # 但两种拒绝原因都必须清空 `generated_metric_plan` 本身：结构合法只是
    # 用错了 answer_mode/category 时，若不清空，序列化后的计划字典仍会通过
    # `_recover_nested_plans` 的重新校验，让一个已判定 INVALID 的意图继续
    # 带着一个看似「已批准」的计划对象。
    if intent.generated_metric_plan is not None and (
        intent.generated_metric_plan_rejected
        or intent.answer_mode is not AnswerMode.METRIC
        or intent.category not in {QuestionCategory.TRADE, QuestionCategory.REFUND}
    ):
        generated_plan_invalid = True
        data["generated_metric_plan"] = None
        if not intent.generated_metric_plan_rejected:
            rejected.append("临时分组指标仅支持交易或退款类的指标查询，拒绝执行")

    if (metric := intent.metric) is not None:
        if _SQL_PATTERN.search(metric):
            rejected.append("指标字段含 SQL 关键字，拒绝执行")
        elif not _METRIC_CODE_PATTERN.match(metric):
            rejected.append("指标必须是英文 metric_code，不接受中文指标名")
        elif metric not in METRIC_WHITELIST:
            rejected.append(f"指标 {metric} 不在白名单内")

    for dimension in intent.dimensions:
        if dimension not in DIMENSION_WHITELIST:
            rejected.append(f"维度 {dimension} 不在白名单内")
    for field in intent.filters:
        if field not in FILTER_WHITELIST:
            rejected.append(f"筛选字段 {field} 不在白名单内")

    if (date_range := intent.date_range) is not None:
        # 顺序固定：先判起止方向，再截未来，最后截 180 天。反过来会先按未来日期
        # 算出一个 180 天窗口，再把末端截到今天，得到不足 180 天的区间。
        if date_range.start > date_range.end:
            rejected.append("日期范围起止颠倒，拒绝执行")
        elif date_range.start > today:
            rejected.append("日期范围完全位于未来，没有可查询的经营数据")
        else:
            start, end = date_range.start, date_range.end
            if end > today:
                end = today
                adjusted.append("日期范围结束日在未来，已截断到今天")
            if (end - start).days + 1 > MAX_QUERY_DAYS:
                start = end - timedelta(days=MAX_QUERY_DAYS - 1)
                adjusted.append(
                    f"日期范围超过 {MAX_QUERY_DAYS} 天，已截断为最近 {MAX_QUERY_DAYS} 天"
                )
            data["date_range"] = DateRange(start=start, end=end).model_dump()

    if intent.limit is not None and intent.limit > MAX_DETAIL_LIMIT:
        data["limit"] = MAX_DETAIL_LIMIT
        adjusted.append(f"limit 超过上限，已覆盖为 {MAX_DETAIL_LIMIT}")
    if rejected:
        data["answer_mode"] = AnswerMode.INVALID
    if generated_plan_invalid:
        data["category"] = QuestionCategory.UNKNOWN

    return IntentValidation(
        intent=QueryIntent.model_validate(data),
        rejected=tuple(rejected),
        adjusted=tuple(adjusted),
    )
