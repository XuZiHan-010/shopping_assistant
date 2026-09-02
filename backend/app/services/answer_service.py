"""把受控查询事实组织成回答草稿，并在使用前作本地校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Final

from app.llm.client import STRUCTURED_CALL_OPTIONS, LlmBudget, LlmClient
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale
from app.metrics.catalog import MetricPayload
from app.prompts.answer import build_answer_system_prompt
from app.schemas.answer import AnswerDraft
from app.schemas.chat import Recommendation
from app.services.quality_types import AttemptFailureKind, DraftAttempt
from app.services.safe_query import ComparisonResult, QueryResult

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
#
# Task 5（双语化）：这份关键词过去只有中文，模型改说英文后（"totalled"/
# "combined"……）完全绕过检查——不是文案缺陷，是校验本身对英文回答失效。
# 中英文关键词统一从 `app.localization.catalog` 取（词表 > 正则），不再各写
# 一套：中文短语走 `_ADDITIVE_CLAIM_PHRASES_ZH`，英文形式通过
# `localize_catalog_value` 反查得到。
#
# 中文短语沿用原有的子串匹配（CJK 文本没有"词边界"这个概念，子串匹配本来
# 就是正确做法，不改）；英文形式改用**词边界正则**而不是子串匹配——子串
# 匹配曾经把 "totally"（"total" 的无关前缀）也判成合计断言，"summary"/
# "consumer" 同理会误伤 "sum" 这种短词。词边界正则从根上关掉这一整类误判，
# 而不是逐词挑"安全"的译文防守。
_ADDITIVE_CLAIM_PHRASES_ZH = ("合计", "总计", "累计", "总和", "加总", "汇总")
_ADDITIVE_CLAIM_PHRASES_EN: tuple[str, ...] = tuple(
    dict.fromkeys(
        phrase
        for phrase in (
            localize_catalog_value(zh_phrase, SupportedLocale.EN_US)
            for zh_phrase in _ADDITIVE_CLAIM_PHRASES_ZH
        )
        if phrase
    )
)


def _en_inflection_alternative(word: str) -> str:
    """把英文词根展开成保守的屈折形式匹配组：只覆盖名词复数（-s）、动词过去式/
    现在分词（-ed/-ing，含英式双写 -led/-ling）这几种规则变化，不追求覆盖全部
    不规则英语语法——够用的目标是让 "totalled" 这类自然写法仍能触发，同时因为
    要求整词匹配到词边界，"totally" 的 "-ly" 后缀不在允许的屈折形式里，不会
    被误伤。
    """

    if word.endswith("e"):
        stem = re.escape(word[:-1])
        return rf"{re.escape(word)}s?|{stem}(?:ed|ing)"
    return rf"{re.escape(word)}(?:s|ed|ing|led|ling)?"


_ADDITIVE_CLAIM_EN_PATTERN: re.Pattern[str] | None = (
    re.compile(
        r"\b(?:"
        + "|".join(_en_inflection_alternative(word) for word in _ADDITIVE_CLAIM_PHRASES_EN)
        + r")\b",
        re.IGNORECASE,
    )
    if _ADDITIVE_CLAIM_PHRASES_EN
    else None
)

# Task 5：日期区间一致性校验。过去的日期/时长正则只负责「剥掉看起来像日期的
# 数字，避免被数字校验误判成幻觉」，从不核对模型陈述的日期区间是否真的落在
# 本次查询范围内——中英文都有这个缺口。这里新增两道独立检查：
#
# 1. 显式区间：从回答文本里抽取「起始日期 至/到/~/-/through/to 结束日期」
#    这类表述（ISO、中文纪年、斜杠、英文月份写法都认），解析成 `date` 对象后
#    与事实包里能确定的实际查询区间比对，区间以外即判定为编造范围；
# 2. 相对时长：抽取「最近 N 天」/「last N days」这类表述，以事实包里最近的
#    实际日期为锚点向前推 N 天，超出实际覆盖范围同样判定为编造窗口——这是
#    计划 §Task 5 明确点名的目标（"日期/时长校验改为先抽取归一化时间区间
#    （ISO 日期、`last N days`、`最近 N 天`）再与查询区间比对"），过去完全
#    没有任何代码路径处理这类相对时长断言。
_ISO_DATE_CAPTURE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_CN_DATE_CAPTURE = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_SLASH_DATE_CAPTURE = re.compile(r"(?:(\d{4})\s*/\s*)?(\d{1,2})\s*/\s*(\d{1,2})\b")
_EN_MONTH_DATE_CAPTURE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_EN_MONTH_NUMBERS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
# 只在两个已识别的日期 token 之间、且中间**只有**这个连接词（允许两侧空白）时，
# 才认定为一个显式区间；避免把文本里恰好相邻但语义无关的两个日期误判成区间。
_RANGE_JOINER = re.compile(r"^\s*(?:至|到|~|-|through|to)\s*$", re.IGNORECASE)
# 相对时长表述：只认「最近/过去 N 天」「last/past N days」这两种计划里点名的
# 写法，不追求覆盖「周」「月」等更多单位——够用即可，不做成通用日期解析器。
_EN_DURATION_CAPTURE = re.compile(r"\b(?:last|past)\s+(\d+)\s*days?\b", re.IGNORECASE)
_CN_DURATION_CAPTURE = re.compile(r"(?:最近|过去)\s*(\d+)\s*天")
# 两种语言共用同一条 issue 文案（同一个 issue 码的唯一渲染），不按草稿语言分叉；
# 显式区间与相对时长两道检查也共用同一条文案——对用户来说都是「陈述的时间范围
# 与实际查询不一致」，不需要按触发路径拆成两句话。
_DATE_RANGE_ISSUE = "回答陈述的日期区间超出了本次查询的实际范围"


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
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> DraftAttempt:
        user = _facts_json(facts)
        if previous and issues:
            user += "\n\n上一版输出：\n" + previous + "\n校验失败原因：" + "；".join(issues)
            user += "\n请修复所有问题，并重新只输出完整 JSON。"
        result = await llm.complete(
            system=build_answer_system_prompt(locale),
            user=user,
            fallback=self._fallback(facts).model_dump_json(),
            budget=budget,
            options=STRUCTURED_CALL_OPTIONS,
        )
        if result.degraded:
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
        if result.comparison is not None:
            answer = _comparison_answer(result.comparison, metric_label, unit)
        elif result.truncated:
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
            and (
                any(phrase in raw_text for phrase in _ADDITIVE_CLAIM_PHRASES_ZH)
                or (
                    _ADDITIVE_CLAIM_EN_PATTERN is not None
                    and _ADDITIVE_CLAIM_EN_PATTERN.search(raw_text) is not None
                )
            )
        ):
            issues.append("非加和指标不能被回答草稿合计或汇总")
        range_issue = _date_range_issue(raw_text, facts) or _duration_range_issue(raw_text, facts)
        if range_issue is not None:
            issues.append(range_issue)
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


def _comparison_answer(comparison: ComparisonResult, metric_label: str, unit: str) -> str:
    """D3 裁定：兜底文案必须如实说明环比/同比，基期算不出比例时不得省略说明（R7）。"""

    if comparison.current_value is None:
        return f"本次查询未取得可汇总的{metric_label}数值，无法进行对比。"
    if comparison.change_ratio is not None:
        return (
            f"本次查询的{metric_label}为 {comparison.current_value}{unit}，"
            f"对比周期为 {comparison.baseline_value}{unit}，变化 {comparison.change_ratio}%。"
        )
    return (
        f"本次查询的{metric_label}为 {comparison.current_value}{unit}；"
        "对比基期无数据或为零，无法计算变化率。"
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
        + ',"comparison":'
        + _comparison_json(facts.query_result.comparison)
        + "}"
    )


def _comparison_json(comparison: ComparisonResult | None) -> str:
    import json

    if comparison is None:
        return "null"
    return json.dumps(
        {
            "mode": comparison.mode.value,
            "current_range": {
                "start": comparison.current_range.start.isoformat(),
                "end": comparison.current_range.end.isoformat(),
            },
            "baseline_range": {
                "start": comparison.baseline_range.start.isoformat(),
                "end": comparison.baseline_range.end.isoformat(),
            },
            "current_value": _json_value(comparison.current_value),
            "baseline_value": _json_value(comparison.baseline_value),
            "change_ratio": _json_value(comparison.change_ratio),
        },
        ensure_ascii=False,
        separators=(",", ":"),
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
    comparison = result.comparison
    if comparison is not None:
        for value in (comparison.current_value, comparison.baseline_value, comparison.change_ratio):
            if value is not None:
                values |= _numeric_forms(value)
        values |= _date_parts(comparison.current_range.start)
        values |= _date_parts(comparison.current_range.end)
        values |= _date_parts(comparison.baseline_range.start)
        values |= _date_parts(comparison.baseline_range.end)
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


@dataclass(frozen=True)
class _DateToken:
    """回答文本里一个已识别日期片段的位置与拆解成分（年可能缺失）。"""

    start: int
    end: int
    year: int | None
    month: int
    day: int


def _find_date_tokens(text: str) -> list[_DateToken]:
    """扫描文本里全部可识别的日期片段（ISO / 中文 / 斜杠 / 英文月份），按出现
    位置排序——语言无关，四种写法用同一套逻辑并列扫描，不偏向任何一种。
    """

    tokens: list[_DateToken] = []
    for match in _ISO_DATE_CAPTURE.finditer(text):
        tokens.append(
            _DateToken(match.start(), match.end(), int(match[1]), int(match[2]), int(match[3]))
        )
    for match in _EN_MONTH_DATE_CAPTURE.finditer(text):
        month = _EN_MONTH_NUMBERS.get(match[1].lower())
        if month is None:
            continue
        tokens.append(_DateToken(match.start(), match.end(), None, month, int(match[2])))
    for match in _CN_DATE_CAPTURE.finditer(text):
        year = int(match[1]) if match[1] else None
        tokens.append(_DateToken(match.start(), match.end(), year, int(match[2]), int(match[3])))
    for match in _SLASH_DATE_CAPTURE.finditer(text):
        year = int(match[1]) if match[1] else None
        tokens.append(_DateToken(match.start(), match.end(), year, int(match[2]), int(match[3])))
    return sorted(tokens, key=lambda token: token.start)


def _extract_stated_ranges(text: str) -> list[tuple[_DateToken, _DateToken]]:
    """只把「两个日期 token 之间除了一个区间连接词外没有别的内容」视为显式区间。

    要求两个 token 紧邻（中间只隔着 `_RANGE_JOINER` 认识的连接词）是刻意收紧的
    条件：草稿里散落提到的两个不相关日期（如「8月11日为 3 件，8月17日为
    15 件」）绝不能被当成「模型宣称的区间」，那只是在分别引用两个真实数据点。
    """

    tokens = _find_date_tokens(text)
    ranges: list[tuple[_DateToken, _DateToken]] = []
    for first, second in pairwise(tokens):
        gap = text[first.end : second.start]
        if _RANGE_JOINER.match(gap):
            ranges.append((first, second))
    return ranges


def _resolve_date(token: _DateToken, fallback_year: int) -> date | None:
    year = token.year if token.year is not None else fallback_year
    try:
        return date(year, token.month, token.day)
    except ValueError:
        return None


def _reference_range(facts: AnswerFacts) -> tuple[date, date] | None:
    """事实包里能确定的实际查询区间；确定不了（没有对比期、也没有日期维度列，
    比如按类目分组的结果）时返回 `None`，调用方按「无法判断」直接放行（fail
    open）——这道校验只在能拿到明确参照区间时才生效，不臆造一个默认范围。
    """

    comparison = facts.query_result.comparison
    if comparison is not None:
        return comparison.current_range.start, comparison.current_range.end
    found: list[date] = []
    for row in facts.query_result.rows:
        for value in row.values():
            parsed = _parse_business_date(value)
            if parsed is not None:
                found.append(parsed)
    if not found:
        return None
    return min(found), max(found)


def _date_range_issue(raw_text: str, facts: AnswerFacts) -> str | None:
    """回答里显式陈述的日期区间必须落在本次查询的实际范围内，否则判定为编造
    范围——语言无关：中英文、ISO、斜杠写法走同一套抽取与比对逻辑，产出同一条
    issue 文案（两种语言共用同一个 issue 码，`quality_notes` 只是渲染差异）。
    """

    reference = _reference_range(facts)
    if reference is None:
        return None
    ref_start, ref_end = reference
    for first, second in _extract_stated_ranges(raw_text):
        start = _resolve_date(first, ref_start.year)
        end = _resolve_date(second, ref_start.year)
        if start is None or end is None:
            continue
        if start > end:
            start, end = end, start
        if start < ref_start or end > ref_end:
            return _DATE_RANGE_ISSUE
    return None


#: 正则对捕获的数字位数没有上限，模型幻觉出「最近 1000000 天」这类离谱数字时，
#: `date - timedelta(days=days)` 一旦超出 `date` 能表示的公元 1~9999 年范围就会
#: 抛出未捕获的 `OverflowError`，把质量循环直接崩掉（该异常不在 `compose_once`
#: 的 try/except 覆盖范围内）。任何业务问答场景都不会真的问「最近一万天」，
#: 超过这个上限直接当作「不是真实时长声明」跳过，而不是尝试解析后再崩溃——
#: 与本函数一贯的 fail open 原则一致：宁可少校验一条，也不能让校验本身变成
#: 新的故障源。10 年（3650 天）已经远超商家日常查询窗口，留足安全余量。
_MAX_PLAUSIBLE_DURATION_DAYS: Final = 3650


def _extract_stated_durations(text: str) -> list[int]:
    """抽取「最近/过去 N 天」「last/past N days」这类相对时长表述，返回天数。

    过滤掉超过 `_MAX_PLAUSIBLE_DURATION_DAYS` 的离谱数字——那不是真实的时长
    声明，继续拿去做日期运算只会有 `OverflowError` 风险，见上方常量注释。
    """

    days: list[int] = [int(match[1]) for match in _EN_DURATION_CAPTURE.finditer(text)]
    days.extend(int(match[1]) for match in _CN_DURATION_CAPTURE.finditer(text))
    return [value for value in days if value <= _MAX_PLAUSIBLE_DURATION_DAYS]


def _duration_range_issue(raw_text: str, facts: AnswerFacts) -> str | None:
    """相对时长断言必须与实际查询覆盖的天数一致：以事实包里最近的实际日期为
    锚点向前推 N 天，超出实际范围即判定为编造窗口——与 `_date_range_issue`
    共用同一套「无法判断就放行」的 fail open 原则和同一条 issue 文案，只是
    抽取的表述形态不同（相对时长而不是显式起止日期）。
    """

    reference = _reference_range(facts)
    if reference is None:
        return None
    ref_start, ref_end = reference
    for days in _extract_stated_durations(raw_text):
        if days <= 0:
            continue
        claimed_start = ref_end - timedelta(days=days - 1)
        if claimed_start < ref_start:
            return _DATE_RANGE_ISSUE
    return None


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
