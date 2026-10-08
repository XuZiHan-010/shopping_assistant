"""三级预算：全局 / 角色 / 店铺（N5 B Task 1；PRD §10.2、Q37）。

三级同时生效，任一耗尽即熔断；预算检查在**发出请求之前**完成。
- 角色级把公开的顾客流量与商家工作台隔开：顾客流量再大也拖不垮商家；
- 店铺级让一家店耗尽不影响另一家；同一家店的顾客流量与商家工作台也各算各的；
- 非对话调用（记忆抽取、压缩摘要、简报预生成）按所属角色与店铺照样计入。

这里用尊重各级额度的内存仓储验证隔离语义；原子性与并发由
`tests/integration/repositories/test_llm_budget_repository.py` 在真实 PostgreSQL 上证明。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from uuid import UUID

import pytest

from app.core.config import AppEnvironment, Settings
from app.core.session import SessionRole
from app.llm.client import (
    LlmBudget,
    LlmBudgetExceededError,
    LlmDailyBudgetExceededError,
    LlmMessage,
    LlmResult,
    LlmTurn,
)
from app.llm.guard import BudgetScope, LlmCostGuard, budget_scopes

M_A = UUID("00000000-0000-0000-0000-0000000000a1")
M_B = UUID("00000000-0000-0000-0000-0000000000b2")


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "llm_daily_budget_tokens": 100_000,
        "llm_customer_daily_budget_tokens": 40_000,
        "llm_merchant_daily_budget_tokens": 60_000,
        "llm_shop_daily_budget_tokens": 20_000,
        "llm_max_output_tokens_per_call": 200,
    }
    values.update(overrides)
    return Settings(**values)


class ScopedBudgets:
    """按 scope 分别记账的内存仓储：一次预扣要么所有 scope 都扣，要么都不扣。"""

    def __init__(self) -> None:
        self.consumed: dict[str, int] = defaultdict(int)
        self.reserve_calls = 0

    async def reserve_scoped(
        self, *, usage_date: date, tokens: int, scopes: Sequence[BudgetScope]
    ) -> str | None:
        self.reserve_calls += 1
        for scope in scopes:
            if self.consumed[scope.key] + tokens > scope.budget:
                return scope.key
        for scope in scopes:
            self.consumed[scope.key] += tokens
        return None

    async def reconcile_scoped(
        self, *, usage_date: date, delta: int, scope_keys: Sequence[str]
    ) -> None:
        for key in scope_keys:
            self.consumed[key] = max(self.consumed[key] + delta, 0)

    async def record_usage(self, **kwargs: object) -> None:
        return None


class CountingLlm:
    def __init__(self) -> None:
        self.requests = 0

    def is_configured(self) -> bool:
        return True

    async def complete(self, **kwargs: object) -> LlmResult:
        self.requests += 1
        return LlmResult(text="ok", tokens=1_000, degraded=False, usage_known=True)


def _guard(
    repo: ScopedBudgets,
    settings: Settings,
    *,
    role: SessionRole | None,
    merchant: UUID | None,
    llm: CountingLlm | None = None,
) -> LlmCostGuard:
    return LlmCostGuard(
        llm or CountingLlm(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        settings,
        request_id="req",
        merchant_id=merchant,
        role=role,
    )


async def _call(guard: LlmCostGuard) -> None:
    await guard.complete(
        system="s" * 50,
        user="u" * 50,
        fallback="",
        budget=LlmBudget(max_calls=10_000, max_tokens=1_000),
    )


async def _exhaust(guard: LlmCostGuard) -> None:
    with pytest.raises(LlmDailyBudgetExceededError):
        for _ in range(10_000):
            await _call(guard)


def test_scopes_cover_global_role_and_shop() -> None:
    settings = _settings()

    keys = {scope.key: scope.budget for scope in budget_scopes(settings, SessionRole.MERCHANT, M_A)}

    assert keys == {
        "GLOBAL": 100_000,
        "ROLE:MERCHANT": 60_000,
        f"SHOP:MERCHANT:{M_A}": 20_000,
    }


def test_calls_without_role_or_merchant_only_hit_global() -> None:
    assert [s.key for s in budget_scopes(_settings(), None, None)] == ["GLOBAL"]


async def test_customer_traffic_cannot_exhaust_merchant_budget() -> None:
    repo, settings = ScopedBudgets(), _settings(llm_shop_daily_budget_tokens=100_000)
    await _exhaust(_guard(repo, settings, role=SessionRole.CUSTOMER, merchant=M_A))

    await _call(_guard(repo, settings, role=SessionRole.MERCHANT, merchant=M_A))


async def test_customers_of_a_shop_cannot_exhaust_that_shops_workbench() -> None:
    repo, settings = ScopedBudgets(), _settings()
    await _exhaust(_guard(repo, settings, role=SessionRole.CUSTOMER, merchant=M_A))

    await _call(_guard(repo, settings, role=SessionRole.MERCHANT, merchant=M_A))


async def test_one_shop_cannot_exhaust_another() -> None:
    repo, settings = ScopedBudgets(), _settings()
    await _exhaust(_guard(repo, settings, role=SessionRole.MERCHANT, merchant=M_A))

    await _call(_guard(repo, settings, role=SessionRole.MERCHANT, merchant=M_B))


async def test_global_exhaustion_stops_everything() -> None:
    repo = ScopedBudgets()
    settings = _settings(
        llm_daily_budget_tokens=5_000,
        llm_customer_daily_budget_tokens=100_000,
        llm_merchant_daily_budget_tokens=100_000,
        llm_shop_daily_budget_tokens=100_000,
    )
    await _exhaust(_guard(repo, settings, role=None, merchant=None))

    for role, merchant in ((SessionRole.CUSTOMER, M_A), (SessionRole.MERCHANT, M_B)):
        with pytest.raises(LlmDailyBudgetExceededError):
            await _call(_guard(repo, settings, role=role, merchant=merchant))


async def test_budget_checked_before_request_sent() -> None:
    repo, settings, llm = ScopedBudgets(), _settings(), CountingLlm()
    guard = _guard(repo, settings, role=SessionRole.MERCHANT, merchant=M_A, llm=llm)
    await _exhaust(guard)
    sent = llm.requests

    with pytest.raises(LlmDailyBudgetExceededError):
        await _call(guard)

    assert llm.requests == sent
    assert guard.daily_cap_hit is True
    assert guard.exhausted_scope == f"SHOP:MERCHANT:{M_A}"


async def test_remaining_request_tokens_cover_input_and_output_before_daily_reservation() -> None:
    repo, llm = ScopedBudgets(), CountingLlm()
    guard = _guard(repo, _settings(), role=SessionRole.MERCHANT, merchant=M_A, llm=llm)
    budget = LlmBudget(max_calls=10, max_tokens=500, tokens=400)

    with pytest.raises(LlmBudgetExceededError):
        await guard.complete(system="s" * 50, user="u" * 50, fallback="", budget=budget)

    assert repo.reserve_calls == 0
    assert llm.requests == 0


async def test_tool_turn_checks_remaining_request_tokens_before_daily_reservation() -> None:
    class ToolLlm(CountingLlm):
        async def converse(self, **kwargs: object) -> None:
            self.requests += 1
            raise AssertionError("request should not be sent")

    repo, llm = ScopedBudgets(), ToolLlm()
    guard = _guard(repo, _settings(), role=SessionRole.MERCHANT, merchant=M_A, llm=llm)
    budget = LlmBudget(max_calls=10, max_tokens=500, tokens=400)

    with pytest.raises(LlmBudgetExceededError):
        await guard.converse(
            messages=[LlmMessage(role="user", content="hello")], tools=[], budget=budget
        )

    assert repo.reserve_calls == 0
    assert llm.requests == 0


async def test_tool_turn_clips_output_to_remaining_request_budget() -> None:
    class ToolLlm(CountingLlm):
        output_limit: int | None = None

        async def converse(self, **kwargs: object) -> LlmTurn:
            self.requests += 1
            self.output_limit = kwargs["options"].max_output_tokens  # type: ignore[union-attr]
            return LlmTurn(
                text="ok", tool_calls=[], stop_reason="END_TURN", tokens=20, usage_known=True
            )

    repo, llm = ScopedBudgets(), ToolLlm()
    guard = _guard(
        repo,
        _settings(llm_max_output_tokens_per_call=200),
        role=SessionRole.MERCHANT,
        merchant=M_A,
        llm=llm,
    )
    budget = LlmBudget(max_calls=10, max_tokens=1000, tokens=500)
    await guard.converse(
        messages=[LlmMessage(role="user", content="hello")], tools=[], budget=budget
    )

    assert llm.requests == 1
    assert llm.output_limit is not None and 0 < llm.output_limit < 200


async def test_default_request_budget_fits_a_skill_then_query_then_answer_turn() -> None:
    """2026-10-07 真实对照：加载 Skill、查一次指标后，第三次调用（作答）被单请求预算拒绝。

    输入按 UTF-8 字节数取上界，实测约 3.5 倍于真实 token；默认单请求上限必须容得下
    这种三步回合，否则凡是用到 Skill 的回合都只能拿到「预算已达上限」。
    数字取自当日账本：前两次调用共 9,280 token，第三次输入约 19,500 字节。
    """

    from app.agent.loop.limits import LoopLimits

    class AnswerLlm(CountingLlm):
        async def converse(self, **kwargs: object) -> LlmTurn:
            self.requests += 1
            return LlmTurn(
                text="ok", tool_calls=[], stop_reason="END_TURN", tokens=5_000, usage_known=True
            )

    settings = _settings(
        llm_daily_budget_tokens=500_000,
        llm_customer_daily_budget_tokens=200_000,
        llm_merchant_daily_budget_tokens=300_000,
        llm_shop_daily_budget_tokens=100_000,
        llm_max_output_tokens_per_call=8_000,
    )
    budget = LoopLimits.from_settings(settings).new_budget()
    budget.calls, budget.tokens = 2, 9_280
    repo, llm = ScopedBudgets(), AnswerLlm()
    guard = _guard(repo, settings, role=SessionRole.MERCHANT, merchant=M_A, llm=llm)

    await guard.converse(
        messages=[LlmMessage(role="system", content="经" * 6_500)], tools=[], budget=budget
    )

    assert llm.requests == 1


async def test_every_demo_merchant_can_finish_25_skill_questions_a_day_on_default_budgets() -> None:
    """用户 2026-10-07 裁定：每个商家每天要能问 25 个左右的问题。

    按当日真实账本的回合尺寸模拟最费的常见回合——加载 Skill、查一次数据、作答，
    三次调用的输入约 14,500 / 18,600 / 19,500 字节，实际约 4,100 / 5,100 / 5,300 token。
    三个演示商家各问满 25 个之后，顾客端仍要有额度（全局预算不能被商家端吃光）。
    """

    from app.agent.loop.limits import LoopLimits

    turn = ((4_830, 4_141), (6_200, 5_139), (6_500, 5_300))  # （系统消息汉字数，实际 token）

    class TurnLlm(CountingLlm):
        def __init__(self) -> None:
            super().__init__()
            self.next_tokens = 0

        async def converse(self, **kwargs: object) -> LlmTurn:
            self.requests += 1
            kwargs["budget"].charge(self.next_tokens)  # type: ignore[attr-defined]
            return LlmTurn(
                text="ok",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=self.next_tokens,
                usage_known=True,
            )

    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )
    repo = ScopedBudgets()
    merchants = (M_A, M_B, UUID("00000000-0000-0000-0000-0000000000c3"))
    for merchant in merchants:
        llm = TurnLlm()
        guard = _guard(repo, settings, role=SessionRole.MERCHANT, merchant=merchant, llm=llm)
        for _question in range(25):
            budget = LoopLimits.from_settings(settings).new_budget()
            for chars, tokens in turn:
                llm.next_tokens = tokens
                await guard.converse(
                    messages=[LlmMessage(role="system", content="经" * chars)],
                    tools=[],
                    budget=budget,
                )
        assert llm.requests == 75

    customer_llm = TurnLlm()
    customer_llm.next_tokens = 4_000
    customer = _guard(repo, settings, role=SessionRole.CUSTOMER, merchant=M_A, llm=customer_llm)
    await customer.converse(
        messages=[LlmMessage(role="system", content="经" * 4_830)],
        tools=[],
        budget=LoopLimits.from_settings(settings).new_budget(),
    )
    assert customer_llm.requests == 1


async def test_default_request_budget_fits_the_measured_after_sales_turn() -> None:
    """2026-10-07 真实复测：售后回合在第 5 次调用被单请求预算拒绝（当时上限 60,000）。

    这类回合要先加载 Skill、列出售后、看详情、查几次规则，再起草决定并作答，工具结果很长。
    前四次调用的输入字节数与实际 token 取自当日账本（字节约为 token 的 3.5 倍）；
    第 5–7 次按同样比例外推：每次再多一条约 2,000 字节的工具结果。
    """

    from app.agent.loop.limits import LoopLimits

    calls = (  # （输入字节数，实际 token）
        (14_775, 4_285),
        (17_574, 4_953),
        (19_466, 5_611),
        (31_143, 9_068),
        (37_300, 10_800),
        (39_300, 11_400),
        (41_300, 12_000),
    )

    class TurnLlm(CountingLlm):
        next_tokens = 0

        async def converse(self, **kwargs: object) -> LlmTurn:
            self.requests += 1
            kwargs["budget"].charge(self.next_tokens)  # type: ignore[attr-defined]
            return LlmTurn(
                text="ok",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=self.next_tokens,
                usage_known=True,
            )

    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )
    budget = LoopLimits.from_settings(settings).new_budget()
    llm = TurnLlm()
    guard = _guard(ScopedBudgets(), settings, role=SessionRole.MERCHANT, merchant=M_A, llm=llm)

    for input_bytes, tokens in calls:
        llm.next_tokens = tokens
        await guard.converse(
            messages=[LlmMessage(role="system", content="a" * input_bytes)],
            tools=[],
            budget=budget,
        )

    assert llm.requests == 7
