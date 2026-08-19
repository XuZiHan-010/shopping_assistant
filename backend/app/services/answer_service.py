"""把受控查询事实组织成回答草稿，并在使用前作本地校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.llm.client import LlmBudget, LlmClient, LlmFailureKind
from app.metrics.catalog import MetricPayload
from app.prompts.answer import ANSWER_SYSTEM_PROMPT
from app.schemas.answer import AnswerDraft
from app.schemas.chat import Recommendation
from app.services.quality_types import AttemptFailureKind, DraftAttempt
from app.services.safe_query import QueryResult

_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2}|Z)?)?\b")
# 事实包里的日期是 ISO，但中文回答里模型自然会写成「8月11日」「2026年8月17日」，
# 甚至「8月14日至16日」这种只剩「16日」的续写。这些都是维度值，不是要与聚合结果
# 逐项比对的业务数字——不剥掉的话，一份完全基于事实的草稿会因为 8/11/16/17 被判成
# 幻觉（2026-08-17 线上实测）。分支按从长到短排列，正则取首个匹配。
_CN_DATE = re.compile(
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
    r"|\d{4}\s*年\s*\d{1,2}\s*月"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
    r"|\d{1,2}\s*月"
    r"|\d{1,2}\s*[日号]"
)
# 时长表述与日期同类：模型复述用户问的时间窗口（「最近 7 天」「完整 7 天趋势」）时，
# 7 并不是一个来自查询结果的业务数字。2026-08-17 线上实测：中文日期修好后，唯一
# 剩下的越界数字就是它。
#
# 代价是——若某个指标的单位恰好是这里的时间单位（如「平均配送时长 3 天」），
# 该指标的数值也会被一并剥掉，守卫对它失效。当前 9 个指标的单位是元/件/单/个，
# 不在此列；将来引入以天/小时为单位的指标时，这里要改成按 metric.unit 排除。
_DURATION = re.compile(r"\d+(?:\.\d+)?\s*(?:天|周|个月|个季度|季度|小时|分钟|年)")
# 模型也会把日期写成「8/12」「8/14-8/16」。刻意只认斜杠、不认连字符和点：
# `15-20` 是取值区间、`15.5` 是小数，剥掉它们会让编造的数字蒙混过关。
_SLASH_DATE = re.compile(r"\d{4}\s*/\s*\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*/\s*\d{1,2}")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# 非加和指标（QueryResult.non_additive）按业务日拆成多行时，模型只被允许原样引用
# 行内数值，不能自己把它们合计/平均成一个新结论——那类结论既不在 allowed_numbers
# 里（如果是新算出的数字会被数字校验拦住），也可能只是复述某一行却贴上「合计」
# 类字眼，看起来像是对全部区间下了结论。见 docs/backend-development-plan.md 的
# B5 本地校验清单第 6 条。
_ADDITIVE_CLAIM_PHRASES = ("合计", "总计", "累计", "总和", "加总", "汇总")


@dataclass(frozen=True)
class AnswerFacts:
    question: str
    metric: MetricPayload | None
    query_result: QueryResult


@dataclass(frozen=True)
class FactSummary:
    """后端从完整时间序列计算的可引用摘要，避免模型自行计算业务数字。"""

    total: Decimal | None = None
    latest_label: str | None = None
    latest_value: Decimal | None = None
    peak_label: str | None = None
    peak_value: Decimal | None = None
    change_pct: Decimal | None = None


class AnswerService:
    """模型只能在事实包内起草；失败时退化为同一事实包的确定性摘要。"""

    async def compose_once(
        self,
        facts: AnswerFacts,
        llm: LlmClient,
        budget: LlmBudget,
        *,
        previous: str = "",
        issues: tuple[str, ...] | list[str] = (),
    ) -> DraftAttempt:
        user = _facts_json(facts)
        if previous and issues:
            user += "\n\n上一版输出：\n" + previous + "\n校验失败原因：" + "；".join(issues)
            user += "\n请修复所有问题，并重新只输出完整 JSON。"
        result = await llm.complete(
            system=ANSWER_SYSTEM_PROMPT,
            user=user,
            fallback=self._fallback(facts).model_dump_json(),
            budget=budget,
        )
        if result.degraded and result.failure_kind is not LlmFailureKind.BAD_PAYLOAD:
            return DraftAttempt(None, result.text, AttemptFailureKind.UPSTREAM)
        if not result.text:
            return DraftAttempt(None, "", None)
        try:
            draft = AnswerDraft.model_validate_json(extract_json_object(result.text))
        except ValueError:
            return DraftAttempt(None, result.text, None)
        return DraftAttempt(draft, result.text, None)

    def validate_issues(self, draft: AnswerDraft, facts: AnswerFacts) -> list[str]:
        return self._validate(draft, facts)

    def fallback_draft(self, facts: AnswerFacts) -> AnswerDraft:
        return self._fallback(facts)

    def facts_json(self, facts: AnswerFacts) -> str:
        return _facts_json(facts)

    def _fallback(self, facts: AnswerFacts) -> AnswerDraft:
        metric = facts.metric
        result = facts.query_result
        metric_label = metric.display_name if metric is not None else "经营指标"
        unit = metric.unit if metric is not None else ""
        summary = self._derive_summary(facts)
        value = _first_metric_value(result, metric.metric_code if metric is not None else None)
        if result.truncated:
            answer = (
                f"本次仅展示部分结果，共预览 {result.total_rows} 行{metric_label}数据，"
                "不对预览行做合计。"
            )
        elif result.non_additive and len(result.rows) > 1:
            answer = f"本次查询返回 {result.total_rows} 行{metric_label}数据；该指标不做跨日合计。"
        elif (
            summary.total is not None
            and summary.latest_label is not None
            and summary.peak_label is not None
        ):
            answer = (
                f"本次查询的{metric_label}合计 {summary.total}{unit}；"
                f"最新日期 {summary.latest_label} 为 {summary.latest_value}{unit}；"
                f"峰值 {summary.peak_value}{unit} 出现在 {summary.peak_label}。"
            )
        elif value is None:
            answer = (
                f"本次查询返回 {result.total_rows} 行数据，暂未形成可汇总的{metric_label}数值。"
            )
        else:
            answer = f"本次查询的{metric_label}为 {value}{unit}。"
        return AnswerDraft(
            answer=answer,
            recommendations=[
                Recommendation(
                    title="核对查询范围",
                    evidence=f"本次查询返回 {result.total_rows} 行数据。",
                    action="确认日期范围和筛选条件是否覆盖要分析的业务。",
                ),
                Recommendation(
                    title="持续观察指标",
                    evidence=answer,
                    action="结合后续周期数据判断变化是否持续。",
                ),
            ],
        )

    def _validate(self, draft: AnswerDraft, facts: AnswerFacts) -> list[str]:
        summary = self._derive_summary(facts)
        allowed_numbers = _allowed_numbers(facts.query_result, summary)
        raw_text = _draft_text(draft)
        issues: list[str] = []
        if _UUID.search(raw_text):
            issues.append("回答含有内部标识符，不得出现在对商家的回答里")
        result = facts.query_result
        if (
            result.non_additive
            and len(result.rows) > 1
            and any(phrase in raw_text for phrase in _ADDITIVE_CLAIM_PHRASES)
        ):
            issues.append("非加和指标不能被回答草稿合计或汇总")
        # 日期是维度值，不是要与聚合结果逐项比对的业务数字；否则 2026-08-05
        # 会被拆成三个数字并把一份完全基于事实的草稿误判为幻觉。中文写法同理。
        text = _DURATION.sub("", _SLASH_DATE.sub("", _CN_DATE.sub("", _ISO_DATE.sub("", raw_text))))
        unexpected = sorted(
            {number for number in _NUMBER.findall(text) if number not in allowed_numbers}
        )
        if unexpected:
            issues.append(
                "以下数字不在查询结果或事实摘要里，不得出现在回答中：" + "、".join(unexpected)
            )
        return issues

    def _derive_summary(self, facts: AnswerFacts) -> FactSummary:
        result = facts.query_result
        metric_columns = [column.key for column in result.columns if column.kind == "METRIC"]
        if result.truncated or len(metric_columns) != 1:
            return FactSummary()

        metric_key = metric_columns[0]
        ordered_rows = _date_metric_rows(result, metric_key)
        if not ordered_rows:
            return FactSummary()

        first_day, first_label, first_value = ordered_rows[0]
        del first_day
        latest_day, latest_label, latest_value = ordered_rows[-1]
        del latest_day, first_label
        peak_day, peak_label, peak_value = max(ordered_rows, key=lambda item: item[2])
        del peak_day
        change_pct = None
        if first_value != 0:
            change_pct = ((latest_value - first_value) / first_value * Decimal("100")).quantize(
                Decimal("0.1")
            )
        return FactSummary(
            total=(
                None if result.non_additive else sum((item[2] for item in ordered_rows), Decimal())
            ),
            latest_label=latest_label,
            latest_value=latest_value,
            peak_label=peak_label,
            peak_value=peak_value,
            change_pct=change_pct,
        )


def extract_json_object(text: str) -> str:
    """截取第一个花括号至最后一个花括号，兼容模型添加的围栏和说明文字。"""

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return text
    return text[start : end + 1]


def _facts_json(facts: AnswerFacts) -> str:
    metric = facts.metric
    non_additive = "true" if facts.query_result.non_additive else "false"
    summary = AnswerService()._derive_summary(facts)
    return (
        '{"question":'
        + _json_string(facts.question)
        + ',"metric":'
        + _json_string(metric.display_name if metric is not None else "")
        + ',"unit":'
        + _json_string(metric.unit if metric is not None else "")
        + ',"rows":'
        + _json_rows(facts.query_result.rows)
        + f',"total_rows":{facts.query_result.total_rows}'
        + f',"non_additive":{non_additive}'
        + ',"summary":'
        + _summary_json(summary)
        + "}"
    )


def _json_rows(rows: list[dict[str, object]]) -> str:
    import json

    return json.dumps(
        [{key: _json_value(value) for key, value in row.items()} for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def _first_metric_value(result: QueryResult, metric_code: str | None) -> str | None:
    if metric_code is None or not result.rows:
        return None
    value = result.rows[0].get(metric_code)
    return None if value is None else _display_value(value)


def _allowed_numbers(result: QueryResult, summary: FactSummary | None = None) -> set[str]:
    values = {str(result.total_rows)}
    for row in result.rows:
        for value in row.values():
            if isinstance(value, Decimal | int | float) and not isinstance(value, bool):
                values |= _numeric_forms(value)
            else:
                values |= _date_parts(value)
    if summary is not None:
        for value in (
            summary.total,
            summary.latest_value,
            summary.peak_value,
            summary.change_pct,
        ):
            if value is not None:
                values |= _numeric_forms(value)
    return values


def _date_parts(value: object) -> set[str]:
    """日期值的成分本身就是可引用的数字。

    治本项：与其枚举模型可能采用的每种日期写法再逐一剥除（已经补过中文、斜杠两轮），
    不如承认「事实包里出现过的日期的年/月/日」本来就允许被引用——这样无论模型写成
    8月11日、8/11 还是 08-11，都不会被误判。数据里不存在的空档日期仍只能靠剥格式覆盖。
    """

    if isinstance(value, date | datetime):
        text = value.isoformat()
    elif isinstance(value, str):
        text = value.strip()
    else:
        return set()
    if not _ISO_DATE.match(text):
        return set()
    parts: set[str] = set()
    for chunk in _NUMBER.findall(text):
        parts.add(chunk)
        # 模型写「8月」而不是「08月」，两种形态都要放行。
        parts.add(chunk.lstrip("0") or "0")
    return parts


def _display_value(value: object) -> str:
    return str(value)


def _draft_text(draft: AnswerDraft) -> str:
    return "\n".join(
        [
            draft.answer,
            *(
                value
                for item in draft.recommendations
                for value in (item.title, item.evidence, item.action)
            ),
        ]
    )


def _date_metric_rows(result: QueryResult, metric_key: str) -> list[tuple[date, str, Decimal]]:
    date_keys = [column.key for column in result.columns if column.kind == "DIMENSION"]
    for date_key in date_keys:
        parsed: list[tuple[date, str, Decimal]] = []
        for row in result.rows:
            label = row.get(date_key)
            value = _decimal_value(row.get(metric_key))
            parsed_date = _parse_business_date(label)
            if value is None or parsed_date is None:
                break
            parsed.append((parsed_date, str(label), value))
        else:
            if parsed:
                return sorted(parsed, key=lambda item: item[0])
    return []


def _decimal_value(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float | str):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_business_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _numeric_forms(value: Decimal | int | float) -> set[str]:
    decimal_value = Decimal(str(value))
    fixed = format(decimal_value, "f")
    normalized = fixed.rstrip("0").rstrip(".") or "0"
    forms = {fixed, normalized, f"{decimal_value:.1f}"}
    if decimal_value == decimal_value.to_integral_value():
        forms.add(str(int(decimal_value)))
    return forms


def _summary_json(summary: FactSummary) -> str:
    import json

    return json.dumps(
        {
            "total": _json_value(summary.total),
            "latest_label": summary.latest_label,
            "latest_value": _json_value(summary.latest_value),
            "peak_label": summary.peak_label,
            "peak_value": _json_value(summary.peak_value),
            "change_pct": _json_value(summary.change_pct),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
