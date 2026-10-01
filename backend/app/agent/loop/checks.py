"""回答的确定性校验（Q16：先于 LLM Reviewer，安全不依赖 Reviewer）。

默认只有一项：**回答里的数字必须有来源**（R4：数字由后端产生，不由模型编造）。来源包括工具结果、
工具给模型的说明、护栏给出的限制、系统提示词、用户本轮与历史中的**用户**消息。
回放的助手历史回答是模型生成内容，不算来源（D-N4-1，契约 §6.12）。
`load_skill` 加载的 Skill 正文**不算**来源：它是做法说明，
其中的示例数字（「满 199 减 20」）若能作证，模型照抄示例就能骗过校验。

这是启发式而非证明，取舍如下（宁可误拦降级为可见的 `VALIDATION`，也不放过编造的数字）：

- 数字紧贴汉字照样检查（「净成交额是999万」）；只有紧贴 ASCII 字母、下划线或「字母-」的数字
  视为标识符的一部分（`SPU-1`、`GMV2`、`p-9`），不检查；
- 个位整数不检查（「3 单」「第 1 个」）；日期、时刻与「30 天」「3 个月」这类时长不检查；
- 单位换算：「1.2 万」按 12000 比对，「12.5%」同时按 12.5 与 0.125 比对；工具以「分」返回金额时，
  来源值同时按 ÷100 的「元」比对；
- 按回答里写出的精度比对：「1.2 万」接受 11500–12500，「1200.00」接受 1199.995–1200.005。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final, Protocol

from app.localization.locales import SupportedLocale
from app.skills.spec import SkillSpec
from app.tools.types import ToolResult


class DeterministicCheck(Protocol):
    """零 LLM 的确定性校验：返回面向用户的问题说明，空列表表示通过。"""

    def __call__(
        self,
        answer: str,
        evidence: Sequence[ToolResult],
        *,
        sources: Sequence[str],
        locale: SupportedLocale,
    ) -> list[str]: ...


# 先把不参与比对的片段整体抹掉：日期、时刻、时长与月份。顺序有意义——「3个月」要先于「3月」。
_NOT_A_QUANTITY: Final = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r"|\d{2,4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?)?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
    r"|\d+\s*(?:个月|天|周|小时|分钟|秒)"
    r"|\d{1,2}\s*月份?"
)
# 数字前不能是数字、小数点、ASCII 字母或下划线，也不能是「字母-」（标识符）；汉字可以。
_QUANTITY: Final = re.compile(
    r"(?<![\d.A-Za-z_])(?<![A-Za-z0-9]-)"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?\s*(?P<unit>万|亿|千|[kK]|%|％)?"
)
_MULTIPLIER: Final = {
    "万": Decimal(10_000),
    "亿": Decimal(100_000_000),
    "千": Decimal(1_000),
    "k": Decimal(1_000),
    "K": Decimal(1_000),
}


def _quantities(text: str) -> Iterable[tuple[str, Decimal, Decimal, str | None]]:
    """产出（原文，数值，按写出精度的半个末位，单位）。"""

    for match in _QUANTITY.finditer(_NOT_A_QUANTITY.sub(" ", text)):
        frac = match.group("frac") or ""
        try:
            value = Decimal(match.group("int").replace(",", "") + frac)
        except InvalidOperation:  # pragma: no cover - 正则已保证是合法数字
            continue
        decimals = max(len(frac) - 1, 0)
        tolerance = Decimal(5) * Decimal(10) ** -(decimals + 1)
        unit = match.group("unit")
        written = match.group("int") + frac + (unit or "")
        yield written, value, tolerance, unit


def _candidates(
    value: Decimal, tolerance: Decimal, unit: str | None
) -> list[tuple[Decimal, Decimal]]:
    candidates = [(value, tolerance)]
    if unit in _MULTIPLIER:
        factor = _MULTIPLIER[unit]
        candidates.append((value * factor, tolerance * factor))
    elif unit in {"%", "％"}:
        candidates.append((value / 100, tolerance / 100))
    return candidates


def _grounded_values(texts: Iterable[str]) -> list[Decimal]:
    values: list[Decimal] = []
    for text in texts:
        for _, value, tolerance, unit in _quantities(text):
            for candidate, _ in _candidates(value, tolerance, unit):
                values.extend((candidate, candidate / 100))  # 分 → 元
    return values


def ungrounded_numbers(
    answer: str, evidence: Sequence[ToolResult], *, sources: Sequence[str]
) -> list[str]:
    """回答里出现、却在任何来源中都找不到的数字（按回答写出的原文返回，去重、保序）。"""

    texts = list(sources)
    for result in evidence:
        if isinstance(result.payload, SkillSpec):
            # Skill 正文是做法说明，不是后端数据：其中的示例数字不能给回答里的数字作证（R4）。
            continue
        texts.append(result.summary)
        if result.payload is not None:
            texts.append(json.dumps(result.payload, ensure_ascii=False, default=str))
        if result.guardrail is not None and result.guardrail.current_limit:
            texts.append(result.guardrail.current_limit)
    grounded = _grounded_values(texts)

    missing: list[str] = []
    for written, value, tolerance, unit in _quantities(answer):
        if unit is None and "." not in written and value < 10:
            continue
        matched = any(
            abs(abs(candidate) - abs(source)) <= slack
            for candidate, slack in _candidates(value, tolerance, unit)
            for source in grounded
        )
        if not matched and written not in missing:
            missing.append(written)
    return missing


def number_grounding_check(
    answer: str,
    evidence: Sequence[ToolResult],
    *,
    sources: Sequence[str],
    locale: SupportedLocale,
) -> list[str]:
    missing = ungrounded_numbers(answer, evidence, sources=sources)
    if not missing:
        return []
    if locale is SupportedLocale.ZH_CN:
        return [f"回答中的数字 {'、'.join(missing)} 在工具结果中找不到来源"]
    return [f"The numbers {', '.join(missing)} in the answer have no source in the tool results"]


DEFAULT_CHECKS: Final[tuple[DeterministicCheck, ...]] = (number_grounding_check,)
