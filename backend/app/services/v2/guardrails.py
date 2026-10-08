"""商家业务护栏（PRD §7.3 不变量 4、D9②）。

起草时的预检与应用时的复检**必须调用同一个函数**：两处各写一份判定，迟早会出现
「预检说可以、应用说不行」或者更糟的反过来。这里只表达业务护栏（数量、价格、时效），
安全闸门的内部规则名不出现在结果里（§8.13.1）。

结果按显示语言渲染（R1）：商家看到的「当前限制」和「修正方法」要能直接读懂。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.localization.locales import SupportedLocale
from app.models.promotion import GuardrailConfig
from app.schemas.v2.drafts import GuardrailCheckResult

RESTOCK_DELTA_CODE: Final = "RESTOCK_DELTA_EXCEEDS_LIMIT"
#: 商家没有单独配置时的补货上限，与迁移 `20260923_0028` 的列默认值一致。
DEFAULT_MAX_RESTOCK_DELTA: Final = 500
#: `guardrail_configs.max_discount_rate` 的 DB CHECK 上限（Q6：实付不得低于原价 80%）；
#: 没有单独配置时的默认值与该列的 `server_default` 一致。
DEFAULT_MAX_DISCOUNT_RATE: Final = Decimal("0.20")
#: `guardrail_configs.max_price_change_rate` 没有单独配置时的默认值。
DEFAULT_MAX_PRICE_CHANGE_RATE: Final = Decimal("0.20")

MIN_PRICE_UNCONFIGURED_CODE: Final = "MIN_PRICE_UNCONFIGURED"
PRICE_BELOW_FLOOR_CODE: Final = "PRICE_BELOW_FLOOR"
PRICE_CHANGE_RATE_EXCEEDS_LIMIT_CODE: Final = "PRICE_CHANGE_RATE_EXCEEDS_LIMIT"
DISCOUNT_RATE_EXCEEDS_LIMIT_CODE: Final = "DISCOUNT_RATE_EXCEEDS_LIMIT"


@dataclass(frozen=True)
class GuardrailLimits:
    max_restock_delta: int = DEFAULT_MAX_RESTOCK_DELTA
    max_discount_rate: Decimal = DEFAULT_MAX_DISCOUNT_RATE
    max_price_change_rate: Decimal = DEFAULT_MAX_PRICE_CHANGE_RATE
    #: 未配置（`None`）时任何调价一律拒绝应用（M6：没有成本依据就不能放行调价）。
    min_allowed_price: Decimal | None = None


async def load_limits(session: AsyncSession, merchant_id: UUID) -> GuardrailLimits:
    """读取**当前**生效的护栏配置；调用方必须在需要判定的那一刻读，不缓存跨请求复用。"""

    config = (
        await session.execute(
            select(GuardrailConfig).where(GuardrailConfig.merchant_id == merchant_id)
        )
    ).scalar_one_or_none()
    if config is None:
        return GuardrailLimits()
    return GuardrailLimits(
        max_restock_delta=config.max_restock_delta,
        max_discount_rate=config.max_discount_rate,
        max_price_change_rate=config.max_price_change_rate,
        min_allowed_price=config.min_allowed_price,
    )


def check_restock(
    delta: int,
    *,
    limits: GuardrailLimits,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> list[GuardrailCheckResult]:
    passed = delta <= limits.max_restock_delta
    if passed:
        return [
            GuardrailCheckResult(
                code=RESTOCK_DELTA_CODE, passed=True, current_limit=None, remediation=None
            )
        ]
    return [
        GuardrailCheckResult(
            code=RESTOCK_DELTA_CODE,
            passed=False,
            current_limit=_limit_text(limits.max_restock_delta, locale),
            remediation=_remediation_text(limits.max_restock_delta, locale),
        )
    ]


def _limit_text(limit: int, locale: SupportedLocale) -> str:
    if locale is SupportedLocale.EN_US:
        return f"A single restock may add at most {limit} units."
    return f"单次补货最多 {limit} 件"


def _remediation_text(limit: int, locale: SupportedLocale) -> str:
    if locale is SupportedLocale.EN_US:
        return f"Reduce the restock quantity to {limit} or fewer, or split it into several drafts."
    return f"把补货数量降到 {limit} 件以内，或拆成多份草稿分批补货"


def check_price_change(
    *,
    current_price: Decimal,
    new_price: Decimal,
    limits: GuardrailLimits,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> list[GuardrailCheckResult]:
    """M6 调价护栏：未配置最低售价一律拒绝；降价不得低于底线；单次幅度有上限。

    预检（起草时）与应用时的复检必须调用同一个函数——调用方各自读取当时生效的
    `GuardrailLimits` 传入，本函数本身不读数据库、不缓存（D9②）。
    """

    checks: list[GuardrailCheckResult] = []

    if limits.min_allowed_price is None:
        checks.append(
            GuardrailCheckResult(
                code=MIN_PRICE_UNCONFIGURED_CODE,
                passed=False,
                current_limit=_min_price_unconfigured_text(locale),
                remediation=_min_price_unconfigured_remediation(locale),
            )
        )
    elif new_price < limits.min_allowed_price:
        checks.append(
            GuardrailCheckResult(
                code=PRICE_BELOW_FLOOR_CODE,
                passed=False,
                current_limit=_floor_text(limits.min_allowed_price, locale),
                remediation=_floor_remediation(limits.min_allowed_price, locale),
            )
        )
    else:
        checks.append(
            GuardrailCheckResult(
                code=PRICE_BELOW_FLOOR_CODE, passed=True, current_limit=None, remediation=None
            )
        )

    # 涨价不受"单次调价幅度上限"约束的降价保护逻辑影响，但幅度上限本身对涨跌都生效
    # （PRD M6 只说"单次调价幅度有上限"，未区分方向）；这里按绝对幅度判断。
    if current_price > 0:
        change_rate = abs(new_price - current_price) / current_price
    else:
        change_rate = Decimal("0")
    if change_rate > limits.max_price_change_rate:
        checks.append(
            GuardrailCheckResult(
                code=PRICE_CHANGE_RATE_EXCEEDS_LIMIT_CODE,
                passed=False,
                current_limit=_rate_limit_text(limits.max_price_change_rate, locale),
                remediation=_rate_remediation_text(limits.max_price_change_rate, locale),
            )
        )
    else:
        checks.append(
            GuardrailCheckResult(
                code=PRICE_CHANGE_RATE_EXCEEDS_LIMIT_CODE,
                passed=True,
                current_limit=None,
                remediation=None,
            )
        )
    return checks


def check_coupon(
    *,
    discount_rate: Decimal | None = None,
    threshold_amount: Decimal | None = None,
    discount_amount: Decimal | None = None,
    limits: GuardrailLimits,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> list[GuardrailCheckResult]:
    """Q6：实付不得低于原价的 (1 - max_discount_rate)，即减免比例不得超过上限。"""

    if discount_rate is None:
        if threshold_amount is None or discount_amount is None:
            raise ValueError("满减券需要门槛和减免金额")
        # 门槛处的优惠幅度最大；没有门槛的满减券无法保证实付不低于 80%。
        discount_rate = (
            discount_amount / threshold_amount
            if threshold_amount > 0
            else Decimal("1")
        )

    if discount_rate <= limits.max_discount_rate:
        return [
            GuardrailCheckResult(
                code=DISCOUNT_RATE_EXCEEDS_LIMIT_CODE,
                passed=True,
                current_limit=None,
                remediation=None,
            )
        ]
    return [
        GuardrailCheckResult(
            code=DISCOUNT_RATE_EXCEEDS_LIMIT_CODE,
            passed=False,
            current_limit=_discount_limit_text(limits.max_discount_rate, locale),
            remediation=_discount_remediation_text(limits.max_discount_rate, locale),
        )
    ]


def _min_price_unconfigured_text(locale: SupportedLocale) -> str:
    if locale is SupportedLocale.EN_US:
        return "No minimum allowed price is configured for this store."
    return "本店尚未配置最低允许售价"


def _min_price_unconfigured_remediation(locale: SupportedLocale) -> str:
    if locale is SupportedLocale.EN_US:
        return "Ask an admin to configure a minimum allowed price before drafting a price change."
    return "请先请管理员配置最低允许售价，再发起调价"


def _floor_text(min_price: Decimal, locale: SupportedLocale) -> str:
    if locale is SupportedLocale.EN_US:
        return f"The price may not go below {min_price}."
    return f"售价不得低于 {min_price} 元"


def _floor_remediation(min_price: Decimal, locale: SupportedLocale) -> str:
    if locale is SupportedLocale.EN_US:
        return f"Raise the new price to at least {min_price}."
    return f"把新价格调整到不低于 {min_price} 元"


def _rate_limit_text(rate: Decimal, locale: SupportedLocale) -> str:
    percent = (rate * 100).normalize()
    if locale is SupportedLocale.EN_US:
        return f"A single price change may not exceed {percent}%."
    return f"单次调价幅度最多 {percent}%"


def _rate_remediation_text(rate: Decimal, locale: SupportedLocale) -> str:
    percent = (rate * 100).normalize()
    if locale is SupportedLocale.EN_US:
        return f"Propose a change within {percent}%, or split it into several staged changes."
    return f"把调价幅度控制在 {percent}% 以内，或拆成多次调整"


def _discount_limit_text(rate: Decimal, locale: SupportedLocale) -> str:
    percent = (rate * 100).normalize()
    if locale is SupportedLocale.EN_US:
        return f"A coupon may not discount more than {percent}%."
    return f"优惠幅度最多 {percent}%"


def _discount_remediation_text(rate: Decimal, locale: SupportedLocale) -> str:
    percent = (rate * 100).normalize()
    if locale is SupportedLocale.EN_US:
        return f"Reduce the discount to {percent}% or less."
    return f"把优惠幅度降到 {percent}% 以内"
