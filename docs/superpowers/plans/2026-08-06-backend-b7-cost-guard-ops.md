# B7·补测试与剩余基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `docs/backend-development-plan.md` §B7 清单里代码层面能做完的全部工作——给已上线但零测试的费用防护/限流/可信 IP 代码补测试，落地 Docker 优雅关闭、结构化可观测性、`GET /api/admin/ops/status` 运维端点，以及 Railway 部署配置与运维手册。

**Architecture:** 在既有分层（`app/core`、`app/repositories`、`app/api`、`app/services`、`app/agent`）里补代码，不引入新分层。新增一个进程内 `OperationalMetrics`（`app/core/metrics.py`），走和现有 `SlidingWindowRateLimiter` 一样的「挂在 `app.state` 上、进程内近似」路子；运维端点直接读既有的 `llm_daily_budget` 表（本来就是 Postgres 共享状态）拿预算数据，不重复造轮子。

**Tech Stack:** FastAPI、SQLAlchemy 2.0（async）、Alembic、structlog、pytest/pytest-asyncio、uv、Docker、Railway（配置即代码）。

## Global Constraints

- 分支：`feature/b5-b6-answer-feedback-export`（已存在，继续在其上提交，不新开分支）。
- 工作目录：`d:/vscode html/merchant_assistant/.worktrees/feature-b5-b6-answer-feedback-export/backend`（下文文件路径均相对此目录，除非另有说明）。
- 本轮**不实际执行 Railway 部署**——只产出 `railway.json` 和 `docs/deployment.md`，用户自行执行部署。
- MVP 无 Redis：所有新计数器（限流、可观测性）必须是进程内实现，不引入外部共享存储；多实例下为近似值，须在文档里写明（`docs/backend-development-plan.md` §B7「LLM 费用与限流」）。
- 保持单 worker：不新增多进程/多 worker 支持（`app/run.py` 不传 `workers=`）。
- 单元测试禁止发起真实 LLM 调用（`AGENTS.md` R3）；本轮全部改动都不涉及真实 DeepSeek 调用，全程用 `FakeLlmClient` 或不经过 LLM 的路径。
- 每个新文件/改动文件跑完对应测试后执行 `uv run ruff check . && uv run ruff format --check . && uv run mypy app`（在 `backend/` 目录下），全绿才能提交。
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 现为 `"B6"`，本计划的最后一个任务会改成 `"B7"`——**改早了会导致中途任务的机械防线报错**，必须放在最后。
- 真实 Postgres 集成测试通过 `docker-compose -p borough up -d postgres` 启动，`TEST_DATABASE_URL` 默认值见 `backend/tests/postgres.py::DEFAULT_TEST_DATABASE_URL`；本地跑 `uv run pytest` 缺库会跳过，`REQUIRE_INTEGRATION_DB=1 uv run pytest` 会硬失败,不允许跳过。

---

### Task 1: `LlmCostGuard` 单元测试

**Files:**
- Create: `backend/tests/unit/llm/test_guard.py`

**Interfaces:**
- Consumes: `app.llm.guard.LlmCostGuard`（构造签名 `LlmCostGuard(inner: LlmClient, repository: LlmBudgetRepository, settings: Settings, *, request_id: str, merchant_id: UUID)`，属性 `daily_cap_hit: bool`，方法 `async remaining() -> int`、`async complete(*, system, user, fallback, budget: LlmBudget) -> LlmResult`）；`app.repositories.llm_budget.LlmBudgetRepository`（真实类，但本任务用 fake 替身，不实例化它）；`app.llm.client.LlmBudget`、`LlmResult`、`LlmDailyBudgetExceededError`。
- Produces: 无（叶子测试，不被后续任务依赖）。

- [ ] **Step 1: 写失败的测试**

```python
"""LlmCostGuard 的原子预算防护行为。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest

from app.core.config import AppEnvironment, Settings
from app.llm.client import LlmBudget, LlmClient, LlmDailyBudgetExceededError, LlmResult
from app.llm.guard import LlmCostGuard

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _settings(**overrides: object) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        llm_daily_budget_tokens=1_000,
        llm_max_output_tokens_per_call=200,
        **overrides,
    )


@dataclass
class _ReserveCall:
    usage_date: date
    tokens: int
    budget: int


@dataclass
class _ReconcileCall:
    usage_date: date
    delta: int


@dataclass
class _RecordUsageCall:
    usage_date: date
    request_id: str
    model: str
    tokens: int
    status: str
    merchant_id: UUID | None


class FakeLlmBudgetRepository:
    """不连数据库的 `LlmBudgetRepository` 替身，记录每次调用供断言。"""

    def __init__(self, *, reserve_returns: list[int | None]) -> None:
        self._reserve_returns = list(reserve_returns)
        self.reserve_calls: list[_ReserveCall] = []
        self.reconcile_calls: list[_ReconcileCall] = []
        self.record_usage_calls: list[_RecordUsageCall] = []

    async def reserve(self, *, usage_date: date, tokens: int, budget: int) -> int | None:
        self.reserve_calls.append(_ReserveCall(usage_date, tokens, budget))
        return self._reserve_returns.pop(0)

    async def reconcile(self, *, usage_date: date, delta: int) -> None:
        self.reconcile_calls.append(_ReconcileCall(usage_date, delta))

    async def snapshot(self, *, usage_date: date) -> object:
        raise AssertionError("guard.complete 不应调用 snapshot")

    async def record_usage(
        self,
        *,
        usage_date: date,
        request_id: str,
        model: str,
        tokens: int,
        status: str,
        merchant_id: UUID | None,
    ) -> None:
        self.record_usage_calls.append(
            _RecordUsageCall(usage_date, request_id, model, tokens, status, merchant_id)
        )


class StubInnerClient:
    """被 `LlmCostGuard` 包裹的下游 LLM 客户端替身。"""

    def __init__(self, *, result: LlmResult | None = None, error: BaseException | None = None) -> None:
        self._result = result
        self._error = error
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def complete(
        self, *, system: str, user: str, fallback: str, budget: LlmBudget
    ) -> LlmResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _guard(
    repository: FakeLlmBudgetRepository, inner: LlmClient, *, settings: Settings | None = None
) -> LlmCostGuard:
    return LlmCostGuard(
        inner,
        repository,  # type: ignore[arg-type]
        settings or _settings(),
        request_id="req-1",
        merchant_id=MERCHANT_ID,
    )


@pytest.mark.asyncio
async def test_complete_reconciles_estimate_to_actual_tokens_and_records_success() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[50])
    inner = StubInnerClient(result=LlmResult(text="ok", tokens=30, degraded=False))
    guard = _guard(repository, inner)

    result = await guard.complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )

    assert result.text == "ok"
    assert guard.daily_cap_hit is False
    assert repository.reconcile_calls == [
        _ReconcileCall(repository.reserve_calls[0].usage_date, 30 - repository.reserve_calls[0].tokens)
    ]
    assert repository.record_usage_calls[-1].status == "SUCCEEDED"
    assert repository.record_usage_calls[-1].tokens == 30


@pytest.mark.asyncio
async def test_complete_raises_and_sets_cap_hit_when_reserve_rejected() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[None])
    inner = StubInnerClient(result=LlmResult(text="unused", tokens=0, degraded=False))
    guard = _guard(repository, inner)

    with pytest.raises(LlmDailyBudgetExceededError):
        await guard.complete(
            system="s",
            user="u",
            fallback="fallback",
            budget=LlmBudget(max_calls=4, max_tokens=8_000),
        )

    assert guard.daily_cap_hit is True
    assert inner.calls == 0
    assert repository.record_usage_calls == [
        _RecordUsageCall(
            repository.reserve_calls[0].usage_date, "req-1", "deepseek-v4-flash", 0,
            "BUDGET_REJECTED", MERCHANT_ID,
        )
    ]


@pytest.mark.asyncio
async def test_complete_still_bills_estimate_when_inner_call_fails() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[50])
    inner = StubInnerClient(error=RuntimeError("下游超时"))
    guard = _guard(repository, inner)

    with pytest.raises(RuntimeError, match="下游超时"):
        await guard.complete(
            system="s",
            user="u",
            fallback="fallback",
            budget=LlmBudget(max_calls=4, max_tokens=8_000),
        )

    assert repository.reconcile_calls == []
    assert repository.record_usage_calls[-1].status == "FAILED"
    assert repository.record_usage_calls[-1].tokens == repository.reserve_calls[0].tokens


@pytest.mark.asyncio
async def test_complete_records_failed_without_reconcile_when_degraded_zero_tokens() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[50])
    inner = StubInnerClient(result=LlmResult(text="fallback", tokens=0, degraded=True))
    guard = _guard(repository, inner)

    result = await guard.complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )

    assert result.degraded is True
    assert repository.reconcile_calls == []
    assert repository.record_usage_calls[-1].status == "FAILED"


@pytest.mark.asyncio
async def test_remaining_subtracts_snapshot_from_daily_budget() -> None:
    class SnapshotOnlyRepository(FakeLlmBudgetRepository):
        async def snapshot(self, *, usage_date: date) -> object:
            @dataclass
            class _Snapshot:
                consumed_tokens: int
                call_count: int

            return _Snapshot(consumed_tokens=400, call_count=3)

    repository = SnapshotOnlyRepository(reserve_returns=[])
    guard = _guard(repository, StubInnerClient(), settings=_settings(llm_daily_budget_tokens=1_000))

    assert await guard.remaining() == 600
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/llm/test_guard.py -v`（在 `backend/` 目录下）
Expected: 收集阶段就应该能通过（被测代码已存在），但先确认这条命令本身能跑、能发现测试——如果此时全部失败，说明测试写错了断言而不是代码有 bug（`LlmCostGuard` 本身已经上线在跑）。

- [ ] **Step 3: 确认测试通过（不需要改生产代码）**

Run: `uv run pytest tests/unit/llm/test_guard.py -v`
Expected: 5 个用例全部 PASS。`LlmCostGuard` 已经是完整实现，这一步只是把行为钉成测试，不修改 `app/llm/guard.py`。

- [ ] **Step 4: 提交**

```bash
git add tests/unit/llm/test_guard.py
git commit -m "test(llm): 补齐 LlmCostGuard 的预算防护单元测试"
```

---

### Task 2: `SlidingWindowRateLimiter` 单元测试

**Files:**
- Create: `backend/tests/unit/core/test_rate_limit.py`

**Interfaces:**
- Consumes: `app.core.rate_limit.SlidingWindowRateLimiter(limit: int, *, window_seconds: float = 60, max_keys: int = 10_000, clock: Callable[[], float])`，方法 `allow(*, token: str, client_ip: str) -> bool`。
- Produces: 无。

- [ ] **Step 1: 写失败的测试**

```python
"""SlidingWindowRateLimiter 的滑动窗口与容量行为。"""

from __future__ import annotations

from app.core.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_allows_up_to_limit_then_blocks_within_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is False


def test_window_slides_and_allows_after_expiry() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is False

    clock.advance(61)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True


def test_different_token_ip_pairs_have_independent_buckets() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is False
    assert limiter.allow(token="t2", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t1", client_ip="2.2.2.2") is True


def test_new_key_rejected_once_max_keys_reached() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=10, window_seconds=60, max_keys=1, clock=clock)

    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
    assert limiter.allow(token="t2", client_ip="2.2.2.2") is False
    # 已存在的 key 不受影响，只是新 key 被软性拒绝。
    assert limiter.allow(token="t1", client_ip="1.1.1.1") is True
```

- [ ] **Step 2: 运行测试确认能收集且通过**

Run: `uv run pytest tests/unit/core/test_rate_limit.py -v`
Expected: 4 个用例全部 PASS（`SlidingWindowRateLimiter` 已实现，本任务只补测试）。

- [ ] **Step 3: 提交**

```bash
git add tests/unit/core/test_rate_limit.py
git commit -m "test(core): 补齐滑动窗口限流器单元测试"
```

---

### Task 3: `resolve_client_ip` 单元测试

**Files:**
- Create: `backend/tests/unit/core/test_client_ip.py`

**Interfaces:**
- Consumes: `app.core.client_ip.resolve_client_ip(request: Request, *, trusted_proxy_hops: int, trusted_proxy_ips: frozenset[str]) -> str`。
- Produces: 无。

- [ ] **Step 1: 写失败的测试**

```python
"""resolve_client_ip 的可信代理跳数解析边界。"""

from __future__ import annotations

from fastapi import Request

from app.core.client_ip import resolve_client_ip


def _request(*, peer: str, forwarded_for: str | None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345),
    }
    return Request(scope)


def test_ignores_forwarded_header_when_no_hops_trusted() -> None:
    request = _request(peer="203.0.113.5", forwarded_for="9.9.9.9")

    result = resolve_client_ip(request, trusted_proxy_hops=0, trusted_proxy_ips=frozenset())

    assert result == "203.0.113.5"


def test_takes_rightmost_trusted_hop_when_peer_is_trusted_proxy() -> None:
    request = _request(peer="10.0.0.1", forwarded_for="attacker-fake, 198.51.100.9")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "198.51.100.9"


def test_forged_prefixes_cannot_shift_the_trusted_hop() -> None:
    """客户端在头里塞任意数量的伪造前缀，右起第 N 跳依旧是代理真正追加的那一跳。"""

    honest = _request(peer="10.0.0.1", forwarded_for="198.51.100.9")
    forged = _request(
        peer="10.0.0.1",
        forwarded_for="9.9.9.9, 8.8.8.8, 7.7.7.7, 198.51.100.9",
    )

    kwargs = {"trusted_proxy_hops": 1, "trusted_proxy_ips": frozenset({"10.0.0.1"})}

    assert resolve_client_ip(honest, **kwargs) == resolve_client_ip(forged, **kwargs) == "198.51.100.9"


def test_falls_back_to_peer_when_direct_peer_not_trusted() -> None:
    request = _request(peer="203.0.113.5", forwarded_for="198.51.100.9")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "203.0.113.5"


def test_falls_back_to_peer_when_chain_shorter_than_hops() -> None:
    request = _request(peer="10.0.0.1", forwarded_for="198.51.100.9")

    result = resolve_client_ip(
        request, trusted_proxy_hops=2, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "10.0.0.1"
```

- [ ] **Step 2: 运行测试确认能收集且通过**

Run: `uv run pytest tests/unit/core/test_client_ip.py -v`
Expected: 5 个用例全部 PASS。这条覆盖了「伪造 `X-Forwarded-For` 不能重置限流计数」的根因（`test_forged_prefixes_cannot_shift_the_trusted_hop`）。

- [ ] **Step 3: 提交**

```bash
git add tests/unit/core/test_client_ip.py
git commit -m "test(core): 补齐可信代理跳数解析单元测试，钉住伪造转发头无效"
```

---

### Task 4: `LlmBudgetRepository` 并发预算集成测试（真实 Postgres）

**Files:**
- Create: `backend/tests/integration/repositories/test_llm_budget_repository.py`

**Interfaces:**
- Consumes: `app.repositories.llm_budget.LlmBudgetRepository(database: Database)`；`tests.conftest` 的 `integration_database`/`migrated_postgres` fixtures；`tests.postgres.TRUNCATE_ALL_TABLES`。
- Produces: 无。

`LlmBudgetRepository` 和其他 repository 不一样，构造参数是整个 `Database`（不是 `AsyncSession`）——
它需要在方法内部自己开事务做原子条件更新，不能借用调用方传入的会话。这意味着不能像别的集成测试
那样直接靠 `db_session` fixture（返回的是 `AsyncSession`）拿到自动截断——`db_session` 在
`conftest.py` 里虽然会在 yield 前 `TRUNCATE` 并 `commit`（对数据库是真实生效的，不受它自己那个
会话后续 `rollback` 影响），但它返回的 `AsyncSession` 类型和 `LlmBudgetRepository` 需要的
`Database` 类型对不上，不能直接传给它。本任务改成自己声明一个依赖 `integration_database` 的
fixture 来做同样的截断，再把 `integration_database` 本身传给 repository。

- [ ] **Step 1: 写失败的测试**

```python
"""LlmBudgetRepository 的原子预扣在并发下不超发（§B7 必测）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.session import Database
from app.repositories.llm_budget import LlmBudgetRepository
from tests.postgres import TRUNCATE_ALL_TABLES

USAGE_DATE = date(2026, 8, 6)


@pytest_asyncio.fixture
async def clean_database(integration_database: Database) -> AsyncIterator[Database]:
    """`LlmBudgetRepository` 自己管理事务，不能复用 `db_session` 的自动截断。"""

    async with integration_database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        await session.commit()
    yield integration_database


@pytest.mark.asyncio
async def test_concurrent_reserve_near_budget_never_overspends(
    clean_database: Database,
) -> None:
    """10 个并发请求逼近预算边界：放行数量精确等于预算能容纳的请求数，不多不少。"""

    repository = LlmBudgetRepository(clean_database)
    budget = 100
    per_call = 30  # 预算最多容纳 3 次（90 <= 100），第 4 次及以后必须被拒绝。

    results = await asyncio.gather(
        *[
            repository.reserve(usage_date=USAGE_DATE, tokens=per_call, budget=budget)
            for _ in range(10)
        ]
    )

    admitted = [value for value in results if value is not None]
    rejected = [value for value in results if value is None]

    assert len(admitted) == 3
    assert len(rejected) == 7

    snapshot = await repository.snapshot(usage_date=USAGE_DATE)
    assert snapshot.consumed_tokens == 3 * per_call
    assert snapshot.consumed_tokens <= budget
    assert snapshot.call_count == 3


@pytest.mark.asyncio
async def test_reconcile_converges_estimate_to_actual(clean_database: Database) -> None:
    repository = LlmBudgetRepository(clean_database)
    reserved = await repository.reserve(usage_date=USAGE_DATE, tokens=100, budget=1_000)
    assert reserved == 100

    # 实际只用了 60 token，回填负 40 差额。
    await repository.reconcile(usage_date=USAGE_DATE, delta=60 - 100)

    snapshot = await repository.snapshot(usage_date=USAGE_DATE)
    assert snapshot.consumed_tokens == 60


@pytest.mark.asyncio
async def test_reconcile_does_not_go_negative(clean_database: Database) -> None:
    repository = LlmBudgetRepository(clean_database)
    await repository.reserve(usage_date=USAGE_DATE, tokens=10, budget=1_000)

    await repository.reconcile(usage_date=USAGE_DATE, delta=-9_999)

    snapshot = await repository.snapshot(usage_date=USAGE_DATE)
    assert snapshot.consumed_tokens == 0
```

- [ ] **Step 2: 启动本地 Postgres 并运行测试确认通过**

Run: `docker-compose -p borough up -d postgres`（仓库根目录，若已在跑可跳过），然后在 `backend/` 目录下
Run: `uv run pytest tests/integration/repositories/test_llm_budget_repository.py -v`
Expected: 3 个用例全部 PASS。第一个用例是本轮的关键验收点——如果并发下出现 `len(admitted) > 3`，说明原子更新失效，必须在这一步真实跑一次确认线上代码是对的（不是靠 mock）。

- [ ] **Step 3: 手动变异验证（一次性，验证后还原，不提交这一步的改动）**

临时把 `app/repositories/llm_budget.py::reserve` 里的条件更新改成「先 `SELECT` 再判断再 `UPDATE`」（引入经典竞态），重新跑 Task 4 的第一个用例，确认它能真实失败（`len(admitted)` 会大于 3）。确认失败后用 `git checkout -- app/repositories/llm_budget.py` 还原，重新跑一次确认恢复 PASS。这一步不产生提交，只是证明测试本身有效——写进最终验收记录里（“已做手工变异验证”）而不是仅凭代码读得出来。

- [ ] **Step 4: 提交**

```bash
git add tests/integration/repositories/test_llm_budget_repository.py
git commit -m "test(analytics): 补齐 LLM 每日预算并发原子扣减的真实库回归（B7 必测）"
```

---

### Task 5: API 级测试——伪造 `X-Forwarded-For` 不能绕过限流

**Files:**
- Create: `backend/tests/api/test_rate_limit_trust_boundary.py`

**Interfaces:**
- Consumes: `app.main.create_app`、`app.core.config.Settings`、`tests.conftest.MERCHANT_ONE_TOKEN`/`MERCHANT_ONE_ID`。
- Produces: 无。

`POST /api/chat` 的依赖顺序是 `get_merchant_context` → `enforce_rate_limit` → `get_chat_service`
（见 `backend/app/api/routes/chat.py:167-172`）。FastAPI 按顺序解析依赖，`enforce_rate_limit`
抛出 `RateLimitedError` 时，排在它后面、真正需要访问数据库的 `get_chat_service` 根本不会被调用。
所以只要 `rate_limit_per_minute=1`，第二次请求必然在触达数据库之前就被限流拦下——不需要一个真的
能连上的 Postgres，也不需要断言第一次请求具体返回什么状态码（它可能因为 `database_url` 指向不可达
的假地址而在业务逻辑上失败，那是另一回事，与本测试要验证的「限流是否被绕过」无关）。

- [ ] **Step 1: 写测试**

```python
"""端到端验证：伪造转发头无法绕过限流（§B7 必测）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_ONE_TOKEN

AUTH = {"Authorization": f"Bearer {MERCHANT_ONE_TOKEN}"}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "demo_merchant_tokens": {MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID},
        "rate_limit_per_minute": 1,
    }
    base.update(overrides)
    return Settings(**base)


@pytest_asyncio.fixture
async def untrusted_client() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(trusted_proxy_hops=0))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_varying_forwarded_for_does_not_reset_limit(untrusted_client: AsyncClient) -> None:
    payload = {"message": "hi", "client_request_id": "req-a"}

    first = await untrusted_client.post(
        "/api/chat",
        json=payload,
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "1.1.1.1"},
    )
    second = await untrusted_client.post(
        "/api/chat",
        json={**payload, "client_request_id": "req-b"},
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "2.2.2.2"},
    )

    # 第一次请求可能因为没有真实数据库而在业务逻辑上失败，这条测试只关心限流是否被
    # 伪造的 X-Forwarded-For 绕过，所以只断言第一次没有被限流、第二次一定被限流命中。
    assert first.status_code != 429
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"
```

- [ ] **Step 2: 运行测试确认通过**

Run: `uv run pytest tests/api/test_rate_limit_trust_boundary.py -v`
Expected: PASS。`resolve_client_ip` 在 `trusted_proxy_hops=0` 时完全忽略
`X-Forwarded-For`（Task 3 已经在单元层面钉过这条），限流器按真实 socket 对端地址
（同一个 `AsyncClient` 连接，恒定为 `127.0.0.1`）和 `Authorization` 头分桶，两次请求换不同的
伪造 IP 头也落在同一个桶里，第二次必然命中限流。

- [ ] **Step 3: 补一条正向用例——可信代理链下两个不同下游客户端不共享限流桶**

在同一文件追加：

```python
@pytest_asyncio.fixture
async def trusted_proxy_client() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(trusted_proxy_hops=1, trusted_proxy_ips="127.0.0.1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_trusted_chain_separates_distinct_downstream_clients(
    trusted_proxy_client: AsyncClient,
) -> None:
    payload = {"message": "hi", "client_request_id": "req-c"}

    first = await trusted_proxy_client.post(
        "/api/chat",
        json=payload,
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "198.51.100.1"},
    )
    second = await trusted_proxy_client.post(
        "/api/chat",
        json={**payload, "client_request_id": "req-d"},
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "198.51.100.2"},
    )

    assert first.status_code != 429
    assert second.status_code != 429
```

`ASGITransport` 不显式传 `client=` 参数时，`request.client.host` 固定是 `"127.0.0.1"`（httpx
`ASGITransport.__init__` 的默认值 `client: tuple[str, int] = ("127.0.0.1", 123)`，见
`.venv/Lib/site-packages/httpx/_transports/asgi.py`），所以上面 `trusted_proxy_ips="127.0.0.1"`
是确定值，不需要现测。

- [ ] **Step 4: 运行全部测试确认通过**

Run: `uv run pytest tests/api/test_rate_limit_trust_boundary.py -v`
Expected: 2 个用例全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add tests/api/test_rate_limit_trust_boundary.py
git commit -m "test(api): 端到端钉住伪造转发头无法绕过限流（B7 必测）"
```

---

### Task 6: Docker 优雅关闭窗口 + 单 worker 决策记录

**Files:**
- Modify: `backend/app/run.py`
- Create: `backend/tests/unit/core/test_run.py`

**Interfaces:**
- Consumes: `uvicorn.run`、`app.core.runtime.loop_factory`。
- Produces: `app.run.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（int 常量）供 `docs/deployment.md`（Task 17）引用。

- [ ] **Step 1: 写失败的测试**

```python
"""容器启动入口：优雅关闭窗口与单 worker 决策。"""

from __future__ import annotations

import pytest
import uvicorn

from app.run import GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS, main


def test_main_configures_graceful_shutdown_and_stays_single_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.delenv("PORT", raising=False)

    main()

    assert captured["app"] == "app.main:create_app"
    assert captured["timeout_graceful_shutdown"] == GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
    assert "workers" not in captured
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/core/test_run.py -v`
Expected: FAIL——`ImportError: cannot import name 'GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS'`（常量还不存在）。

- [ ] **Step 3: 修改 `app/run.py`**

```python
"""容器和本地开发启动入口。"""

from __future__ import annotations

import os

import uvicorn

from app.core.runtime import loop_factory

# 收到 SIGTERM 后最多等待这么久，让在途 SSE 流收尾，超时后 uvicorn 强制断开
# 剩余连接。Railway 自己的 SIGTERM→SIGKILL 宽限期更长，这里给出一个明确的
# 上限，避免依赖 uvicorn 未设置时的默认行为（可能无限等待）。
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30

# 刻意不传 `workers=`：限流器（`SlidingWindowRateLimiter`）、LLM 每日预算的
# 「估算-reserve」协调和运维可观测性计数器（`OperationalMetrics`）都是进程内
# 状态。同一容器起多个 worker 会让它们各算各的——`LlmBudgetRepository.reserve`
# 在数据库层是原子的，预算本身不会超发，但限流命中数和可观测性指标会失真。
# MVP 阶段没有 Redis 等共享存储，要扩容请在 Railway 加多个 Service 副本，
# 不要在这里加 worker 数；副本之间的「进程内近似」约束见 docs/deployment.md。


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        proxy_headers=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
        # uvicorn 不看全局事件循环策略，必须显式传工厂，
        # 否则 Windows 上会拿到 ProactorEventLoop 而连不上数据库。
        loop=loop_factory(),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/core/test_run.py -v`
Expected: PASS。

- [ ] **Step 5: 手动验收记录（不是自动化测试，记录在最终验收报告里）**

真实 SIGTERM 驱动的优雅关闭无法用 `pytest` 覆盖（需要真实起停子进程 + 保持一个流式连接跨越关闭窗口）。本步骤不产生代码改动，只在 Task 18 的最终验收记录里写一条手动验证步骤：`docker build` 出镜像后 `docker run` 启动，发起一个长 SSE 请求（例如故意问一个会触发多轮 LangGraph 节点的问题），另开一个终端 `docker stop <container>`，确认该请求收到完整的 `done`/`error` 事件收尾而不是连接被直接掐断，且容器在 30 秒内退出。

- [ ] **Step 6: 提交**

```bash
git add app/run.py tests/unit/core/test_run.py
git commit -m "feat(run): 显式优雅关闭窗口并记录单 worker 的架构决策（B7 Docker）"
```

---

### Task 7: `OperationalMetrics` 核心模块

**Files:**
- Create: `backend/app/core/metrics.py`
- Create: `backend/tests/unit/core/test_metrics.py`

**Interfaces:**
- Consumes: 无外部依赖（纯内存数据结构）。
- Produces: `OperationalMetrics` 类，供 Task 8（`app.state.metrics` 挂载）、Task 9（`error_code_counts`/`rate_limit_hits`）、Task 10（`degraded_count`）、Task 11（`agent_node_average_ms`）、Task 13（运维端点读取）复用。公开接口：
  - `rate_limit_hits: int`（可直接 `+= 1`）
  - `degraded_count: int`（可直接 `+= 1`）
  - `record_error_code(code: str) -> None`
  - `error_code_counts: dict[str, int]`（只读属性，返回快照副本）
  - `record_route_duration(route: str, duration_seconds: float) -> None`
  - `route_average_ms: dict[str, float]`（只读属性）
  - `record_node_duration(node: str, duration_seconds: float) -> None`
  - `agent_node_average_ms: dict[str, float]`（只读属性）

- [ ] **Step 1: 写失败的测试**

```python
"""OperationalMetrics：进程内运维计数器。"""

from __future__ import annotations

from app.core.metrics import OperationalMetrics


def test_rate_limit_hits_and_degraded_count_are_plain_counters() -> None:
    metrics = OperationalMetrics()

    metrics.rate_limit_hits += 1
    metrics.rate_limit_hits += 1
    metrics.degraded_count += 1

    assert metrics.rate_limit_hits == 2
    assert metrics.degraded_count == 1


def test_record_error_code_accumulates_per_code() -> None:
    metrics = OperationalMetrics()

    metrics.record_error_code("RATE_LIMITED")
    metrics.record_error_code("RATE_LIMITED")
    metrics.record_error_code("AUTH_REQUIRED")

    assert metrics.error_code_counts == {"RATE_LIMITED": 2, "AUTH_REQUIRED": 1}


def test_error_code_counts_returns_snapshot_not_live_reference() -> None:
    metrics = OperationalMetrics()
    metrics.record_error_code("RATE_LIMITED")

    snapshot = metrics.error_code_counts
    snapshot["RATE_LIMITED"] = 999

    assert metrics.error_code_counts == {"RATE_LIMITED": 1}


def test_route_average_ms_computes_mean_of_recorded_durations() -> None:
    metrics = OperationalMetrics()

    metrics.record_route_duration("/api/chat", 0.100)
    metrics.record_route_duration("/api/chat", 0.300)
    metrics.record_route_duration("/api/health", 0.010)

    averages = metrics.route_average_ms

    assert averages["/api/chat"] == pytest.approx(200.0)
    assert averages["/api/health"] == pytest.approx(10.0)


def test_agent_node_average_ms_computes_mean_per_node() -> None:
    metrics = OperationalMetrics()

    metrics.record_node_duration("load_context", 0.010)
    metrics.record_node_duration("load_context", 0.030)

    assert metrics.agent_node_average_ms == {"load_context": pytest.approx(20.0)}


def test_route_average_ms_empty_when_nothing_recorded() -> None:
    metrics = OperationalMetrics()

    assert metrics.route_average_ms == {}
    assert metrics.agent_node_average_ms == {}
```

在文件顶部补 `import pytest`（`pytest.approx` 需要）。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/core/test_metrics.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'app.core.metrics'`。

- [ ] **Step 3: 实现 `app/core/metrics.py`**

```python
"""进程内运维指标：限流命中、降级次数、错误码分布、路由与 Agent 节点耗时。

和 `app.core.rate_limit.SlidingWindowRateLimiter` 共享同一份约束：不落库、
进程重启归零，多实例部署下互不同步，只是近似值——见 `docs/deployment.md`。
`GET /api/admin/ops/status`（B7 运维端点）是这份数据唯一的消费方。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _RunningAverage:
    count: int = 0
    total_seconds: float = 0.0

    def record(self, duration_seconds: float) -> None:
        self.count += 1
        self.total_seconds += duration_seconds

    @property
    def average_ms(self) -> float:
        if self.count == 0:
            return 0.0
        return (self.total_seconds / self.count) * 1000


class OperationalMetrics:
    """`app.state.metrics` 挂载的唯一运维计数器实例。"""

    def __init__(self) -> None:
        self.rate_limit_hits = 0
        self.degraded_count = 0
        self._error_code_counts: dict[str, int] = {}
        self._route_durations: dict[str, _RunningAverage] = {}
        self._agent_node_durations: dict[str, _RunningAverage] = {}

    def record_error_code(self, code: str) -> None:
        self._error_code_counts[code] = self._error_code_counts.get(code, 0) + 1

    @property
    def error_code_counts(self) -> dict[str, int]:
        return dict(self._error_code_counts)

    def record_route_duration(self, route: str, duration_seconds: float) -> None:
        self._route_durations.setdefault(route, _RunningAverage()).record(duration_seconds)

    @property
    def route_average_ms(self) -> dict[str, float]:
        return {route: avg.average_ms for route, avg in self._route_durations.items()}

    def record_node_duration(self, node: str, duration_seconds: float) -> None:
        self._agent_node_durations.setdefault(node, _RunningAverage()).record(duration_seconds)

    @property
    def agent_node_average_ms(self) -> dict[str, float]:
        return {node: avg.average_ms for node, avg in self._agent_node_durations.items()}
```

`field` 导入未被使用——去掉，避免 `ruff` 报 unused import：

```python
from dataclasses import dataclass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/core/test_metrics.py -v`
Expected: 6 个用例全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/core/metrics.py tests/unit/core/test_metrics.py
git commit -m "feat(core): 新增进程内运维指标 OperationalMetrics（B7 可观测性）"
```

---

### Task 8: 挂载 `app.state.metrics` + 请求耗时结构化日志

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_request_logging.py`

**Interfaces:**
- Consumes: Task 7 的 `OperationalMetrics`（构造 `OperationalMetrics()`，方法 `record_route_duration`）。
- Produces: `app.state.metrics: OperationalMetrics`（供 Task 9/10/11/13 使用）；`request_id_middleware` 记录每次请求的 `route_average_ms`。

- [ ] **Step 1: 写失败的测试**

```python
"""main.py 挂载的 app.state.metrics 与请求耗时记录。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app


def _settings() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        rate_limit_per_minute=1000,
    )


@pytest.mark.asyncio
async def test_app_state_exposes_operational_metrics() -> None:
    from app.core.metrics import OperationalMetrics

    app = create_app(_settings())

    assert isinstance(app.state.metrics, OperationalMetrics)


@pytest.mark.asyncio
async def test_health_request_records_route_duration() -> None:
    app = create_app(_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert "/api/health" in app.state.metrics.route_average_ms
    assert app.state.metrics.route_average_ms["/api/health"] >= 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_request_logging.py -v`
Expected: FAIL——`AttributeError: 'State' object has no attribute 'metrics'`。

- [ ] **Step 3: 修改 `app/main.py`**

在现有 import 块里加一行（紧跟 `from app.core.rate_limit import SlidingWindowRateLimiter` 之后）：

```python
from app.core.metrics import OperationalMetrics
```

在 `app.state.rate_limiter = SlidingWindowRateLimiter(...)` 之后加：

```python
    app.state.metrics = OperationalMetrics()
```

把现有的 `request_id_middleware` 替换成：

```python
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: RequestHandler) -> Response:
        request_id = _resolve_request_id(request.headers.get("X-Request-Id"))
        request.state.request_id = request_id
        start = monotonic()
        response = await call_next(request)
        duration_seconds = monotonic() - start
        route = request.scope.get("route")
        route_path = route.path if route is not None else request.url.path
        app.state.metrics.record_route_duration(route_path, duration_seconds)
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            route=route_path,
            status_code=response.status_code,
            duration_ms=round(duration_seconds * 1000, 2),
        )
        response.headers["X-Request-Id"] = request_id
        return response
```

`route_path` 取 `request.scope["route"].path`（路由模板，比如 `/api/health`，不是带真实参数的完整 URL）而不是 `request.url.path`——`call_next` 内部完成路由匹配后会把匹配到的 `route` 对象写回 `scope`，请求成功匹配到路由时可以读到；未匹配到任何路由（比如 404）时 `scope.get("route")` 是 `None`，回退到 `request.url.path`。这一行不需要额外 import，`monotonic` 已经在文件顶部因为 `SlidingWindowRateLimiter` 的构造而被导入（`from time import monotonic`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/api/test_request_logging.py -v`
Expected: 2 个用例全部 PASS。

- [ ] **Step 5: 跑一次全量现有测试，确认没有破坏已有行为**

Run: `uv run pytest -x -q`
Expected: 除因缺库被跳过的集成测试外全部 PASS（改动只是新增字段和替换一个中间件函数体，不改变任何响应内容）。

- [ ] **Step 6: 提交**

```bash
git add app/main.py tests/api/test_request_logging.py
git commit -m "feat(main): 挂载运维指标并记录每次请求的路由耗时结构化日志（B7 可观测性）"
```

---

### Task 9: 错误码计数与限流命中计数接入

**Files:**
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/api/dependencies.py`
- Create: `backend/tests/api/test_metrics_error_tracking.py`

**Interfaces:**
- Consumes: Task 7/8 的 `request.app.state.metrics`（`record_error_code`、`rate_limit_hits`）。
- Produces: 无新增公开接口，纯行为增强，供 Task 13 的运维端点读取 `error_code_counts`/`rate_limit_hits`。

- [ ] **Step 1: 写失败的测试**

```python
"""AppError 与限流命中都会被记入 OperationalMetrics。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_ONE_TOKEN

AUTH = {"Authorization": f"Bearer {MERCHANT_ONE_TOKEN}"}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "rate_limit_per_minute": 1000,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_auth_required_error_is_recorded_in_error_code_counts() -> None:
    app = create_app(_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/chat",
            json={"message": "hi", "client_request_id": "req-1"},
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 401
    assert app.state.metrics.error_code_counts.get("AUTH_REQUIRED") == 1


@pytest.mark.asyncio
async def test_rate_limited_error_increments_both_dedicated_and_generic_counters() -> None:
    settings = _settings(
        rate_limit_per_minute=1,
        demo_merchant_tokens={MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID},
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        payload = {"message": "hi", "client_request_id": "req-a"}
        await client.post(
            "/api/chat", json=payload, headers={**AUTH, "Accept": "application/json"}
        )
        second = await client.post(
            "/api/chat",
            json={**payload, "client_request_id": "req-b"},
            headers={**AUTH, "Accept": "application/json"},
        )

    assert second.status_code == 429
    assert app.state.metrics.rate_limit_hits == 1
    assert app.state.metrics.error_code_counts.get("RATE_LIMITED") == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_metrics_error_tracking.py -v`
Expected: FAIL——两个断言都是 0（`error_code_counts` 目前是空字典，`rate_limit_hits` 还没有任何写入点）。

- [ ] **Step 3: 修改 `app/core/errors.py`**

把 `handle_app_error` 改成：

```python
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request.app.state.metrics.record_error_code(str(exc.code))
        return _response(
            ErrorResponse(
                code=exc.code,
                message=exc.message,
                request_id=_request_id(request),
                details=exc.details,
                retryable=exc.retryable,
            ),
            exc.status_code,
        )
```

- [ ] **Step 4: 修改 `app/api/dependencies.py`**

把 `enforce_rate_limit` 改成：

```python
def enforce_rate_limit(
    request: Request,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    token = request.headers.get("authorization", "")
    limiter = request.app.state.rate_limiter
    if not limiter.allow(
        token=token,
        client_ip=resolve_client_ip(
            request,
            trusted_proxy_hops=settings.trusted_proxy_hops,
            trusted_proxy_ips=settings.trusted_proxy_ip_set,
        ),
    ):
        request.app.state.metrics.rate_limit_hits += 1
        raise RateLimitedError
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/api/test_metrics_error_tracking.py -v`
Expected: 2 个用例全部 PASS。

- [ ] **Step 6: 回归 Task 5 的限流测试，确认没有破坏**

Run: `uv run pytest tests/api/test_rate_limit_trust_boundary.py -v`
Expected: 3 个用例全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/core/errors.py app/api/dependencies.py tests/api/test_metrics_error_tracking.py
git commit -m "feat(core): 错误码与限流命中计入运维指标（B7 可观测性）"
```

---

### Task 10: 降级计数接入 `ChatService`

**Files:**
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Create/Modify: `backend/tests/unit/services/test_chat_service.py`（追加用例，不新建文件——该文件已存在且已经在用 `DeterministicAgent` 等替身，追加到文件末尾）

**Interfaces:**
- Consumes: `app.core.metrics.OperationalMetrics`（Task 7）。
- Produces: `ChatService.__init__` 新增可选参数 `metrics: OperationalMetrics | None = None`。

**已核对现有文件**（`backend/tests/unit/services/test_chat_service.py`）：替身类是
`FakeSession`、`FakeConversationRepository`；`DeterministicAgent`（`tests/support/agent.py`）
产出的 `ChatResponse` 固定 `degraded=True`；文件里已有 `chat_request(message=..., key=...) -> ChatRequest`
辅助函数和 `build_service(agent=None)` 辅助函数，但 `build_service` 不接受 `metrics` 参数，本任务的
新用例改为直接构造 `ChatService(...)`（不经过 `build_service`），其余复用现成的
`chat_request`/`CountingAgent`。

- [ ] **Step 1: 在该文件末尾追加失败的测试**

```python
@pytest.mark.asyncio
async def test_finalized_degraded_response_increments_metrics() -> None:
    from app.core.metrics import OperationalMetrics

    session = FakeSession()
    repository = FakeConversationRepository()
    metrics = OperationalMetrics()
    service = ChatService(
        session,  # type: ignore[arg-type]
        repository,
        CountingAgent(),  # DeterministicAgent 的回答固定 degraded=True，见 tests/support/agent.py
        metrics=metrics,
    )

    await service.submit(CONTEXT, chat_request(key="req-degraded-1"), request_id="req-1")

    assert metrics.degraded_count == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/services/test_chat_service.py -v -k degraded`
Expected: FAIL——`TypeError: ChatService.__init__() got an unexpected keyword argument 'metrics'`。

- [ ] **Step 3: 修改 `app/services/chat_service.py`**

加 import：

```python
from app.core.metrics import OperationalMetrics
```

`__init__` 签名改为：

```python
    def __init__(
        self,
        session: AsyncSession,
        conversations: ConversationRepository,
        agent: ChatAgentProtocol,
        scope_service: MerchantScopeService[Conversation] | None = None,
        export_service: ExportService | None = None,
        cost_guard: CostGuardProtocol | None = None,
        budget_gate: CostGuardProtocol | None = None,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._agent = agent
        self._scope_service = scope_service
        self._export_service = export_service
        self._cost_guard = cost_guard
        self._budget_gate = budget_gate
        self._metrics = metrics
```

在 `_run_agent` 里，`if self._cost_guard is not None and self._cost_guard.daily_cap_hit:` 那一整个 `if` 块结束之后（也就是紧接着原来的 `await self._conversations.create_message(...)` 之前）插入：

```python
            if self._metrics is not None and response.degraded:
                self._metrics.degraded_count += 1
```

这一行必须放在「预算耗尽强制降级」的 `if` 块**之后**，这样无论 `response.degraded` 是问答图本身就产出的（比如查询被拒绝）还是本次因预算耗尽被临时改写的，都会被计入同一个计数器——这是唯一一处 `ChatResponse` 最终定稿的地方。重放路径（`_dispatch_existing` 命中已有终态答案）不经过这里，不重复计数，这是有意为之：重放的是已经算过一次的历史答案，不应该让客户端反复重试同一个请求就把降级计数刷高。

- [ ] **Step 4: 修改 `app/api/dependencies.py` 把 metrics 传进 `get_chat_service`**

在 `ChatService(...)` 构造调用处（`get_chat_service` 函数体最后一行）加上 `metrics=request.app.state.metrics`：

```python
    return ChatService(
        session,
        conversations,
        graph,
        MerchantScopeService(conversations, AuditRepository(database)),
        _build_export_service(session, settings),
        guard,
        guard,
        metrics=request.app.state.metrics,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/services/test_chat_service.py -v`
Expected: 全部 PASS（包括新用例和文件里原有的所有用例）。

- [ ] **Step 6: 提交**

```bash
git add app/services/chat_service.py app/api/dependencies.py tests/unit/services/test_chat_service.py
git commit -m "feat(chat): 最终降级回答计入运维指标（B7 可观测性）"
```

---

### Task 11: Agent 节点耗时

**Files:**
- Modify: `backend/app/agent/graph.py`
- Create: `backend/tests/unit/agent/test_graph_node_timing.py`

**Interfaces:**
- Consumes: 无新外部依赖（定义自己的 `NodeTimerLike` Protocol，和现有 `QueryServiceLike` 同一种写法）。
- Produces: `MerchantQaGraph.__init__` 新增可选参数 `node_timer: NodeTimerLike | None = None`；`app.core.metrics.OperationalMetrics` 天然满足该 Protocol（已有 `record_node_duration` 方法，Task 7 已实现，无需再改 `metrics.py`）。

- [ ] **Step 1: 写失败的测试**

```python
"""MerchantQaGraph 在配置了 node_timer 时记录每个节点的耗时。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.agent.graph import GRAPH_NODES, MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog


class _Document:
    def __init__(self, path: str, content: str) -> None:
        self.source_path = path
        self.title = path
        self.content = content
        self.is_complete = True


class _KnowledgeRepo:
    async def list_active(self) -> list[_Document]:
        return [_Document("index/README.md", "交易"), _Document("业务/交易/正文.md", "订单 GMV")]


class _MetricRepo:
    async def get_by_code(self, metric_code: str) -> None:
        return None


@dataclass
class FakeNodeTimer:
    recorded: list[tuple[str, float]] = field(default_factory=list)

    def record_node_duration(self, node: str, duration_seconds: float) -> None:
        self.recorded.append((node, duration_seconds))


def _metric_response(mode: str, metric: str | None) -> str:
    return json.dumps(
        {
            "answer_mode": mode,
            "category": "TRADE" if mode == "METRIC" else "UNKNOWN",
            "metric": metric,
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


@pytest.mark.asyncio
async def test_all_graph_nodes_report_duration_when_timer_configured() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            _metric_response("METRIC", "gmv"),
        ]
    )
    timer = FakeNodeTimer()
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_KnowledgeRepo()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_MetricRepo(), llm),
        node_timer=timer,
    )

    await graph.run("昨天GMV", uuid4())

    recorded_nodes = [node for node, _duration in timer.recorded]
    assert recorded_nodes == list(GRAPH_NODES)
    assert all(duration >= 0 for _node, duration in timer.recorded)


@pytest.mark.asyncio
async def test_graph_runs_normally_without_node_timer() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            _metric_response("METRIC", "gmv"),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_KnowledgeRepo()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_MetricRepo(), llm),
    )

    result = await graph.run("昨天GMV", uuid4())

    assert [step.node for step in result.steps] == list(GRAPH_NODES)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/agent/test_graph_node_timing.py -v`
Expected: FAIL——`TypeError: MerchantQaGraph.__init__() got an unexpected keyword argument 'node_timer'`。

- [ ] **Step 3: 修改 `app/agent/graph.py`**

在顶部 import 块，把

```python
from collections.abc import Sequence
```

改成

```python
from collections.abc import Awaitable, Callable, Sequence
```

再加

```python
from time import monotonic
```

在 `QueryServiceLike` Protocol 定义之后（第 47-57 行附近）新增一个 Protocol：

```python
class NodeTimerLike(Protocol):
    """`_build_graph` 给每个节点计时时依赖的最小接口。"""

    def record_node_duration(self, node: str, duration_seconds: float) -> None: ...
```

`MerchantQaGraph.__init__` 签名加一个参数（放在 `visualization_service` 之后）：

```python
        visualization_service: VisualizationService | None = None,
        node_timer: NodeTimerLike | None = None,
    ) -> None:
```

函数体里加一行：

```python
        self._visualization_service = visualization_service or VisualizationService()
        self._node_timer = node_timer
        self._graph = self._build_graph()
```

把 `_build_graph` 方法体替换成：

```python
    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        node_methods: dict[str, Callable[[AgentState], Awaitable[dict[str, object]]]] = {
            "load_context": self._load_context,
            "retrieve_knowledge_index": self._retrieve_knowledge_index,
            "classify_intent": self._classify_intent,
            "understand_intent": self._understand_intent,
            "validate_intent": self._validate_intent,
            "retrieve_knowledge_detail": self._retrieve_knowledge_detail,
            "query_data": self._query_data,
            "compose_answer": self._compose_answer,
            "local_validate": self._local_validate,
            "review_answer": self._review_answer,
            "decide_retry": self._decide_retry,
            "suggest_questions": self._suggest_questions,
            "persist_answer": self._persist_answer,
        }
        for name in GRAPH_NODES:
            graph.add_node(name, self._timed_node(name, node_methods[name]))
        graph.add_edge(START, "load_context")
        for source, target in pairwise(GRAPH_NODES):
            graph.add_edge(source, target)
        graph.add_edge("persist_answer", END)
        return graph.compile()

    def _timed_node(
        self, name: str, fn: Callable[[AgentState], Awaitable[dict[str, object]]]
    ) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
        if self._node_timer is None:
            return fn

        async def wrapper(state: AgentState) -> dict[str, object]:
            start = monotonic()
            try:
                return await fn(state)
            finally:
                self._node_timer.record_node_duration(name, monotonic() - start)

        return wrapper
```

`node_methods` 字典里的键必须和 `GRAPH_NODES`（文件顶部已有的常量）完全一致——这也是为什么测试里直接拿 `GRAPH_NODES` 来断言顺序，而不是手写一遍节点名列表，避免两处定义漂移。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/agent/test_graph_node_timing.py -v`
Expected: 2 个用例全部 PASS。

- [ ] **Step 5: 回归已有的 Agent 图测试，确认没有破坏行为**

Run: `uv run pytest tests/unit/agent/ -v`
Expected: 全部 PASS（`_build_graph` 的外部行为——节点顺序、边的连接——完全不变，只是每个节点函数被可选地包了一层计时）。

- [ ] **Step 6: 在 `app/api/dependencies.py` 把 `node_timer` 接进 `get_chat_service`**

在 `MerchantQaGraph(...)` 构造调用处加 `node_timer=request.app.state.metrics`：

```python
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(KnowledgeRepository(session)),
        intent_service_llm=llm,
        catalog=MetricCatalog(MetricRepository(session), llm),
        max_llm_calls=settings.llm_max_calls_per_request,
        max_llm_tokens=settings.llm_max_tokens_per_request,
        query_service=SafeQueryService(
            AnalyticsRepository(session), business_timezone=settings.business_timezone
        ),
        merchant_id=context.merchant_id,
        answer_llm=llm,
        reviewer_llm=llm,
        node_timer=request.app.state.metrics,
    )
```

- [ ] **Step 7: 跑一次全量测试确认接线没有破坏 Chat 相关测试**

Run: `uv run pytest tests/unit/services/test_chat_service.py tests/unit/agent/ -v`
Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
git add app/agent/graph.py app/api/dependencies.py tests/unit/agent/test_graph_node_timing.py
git commit -m "feat(agent): Agent 节点耗时接入运维指标（B7 可观测性）"
```

---

### Task 12: 管理员令牌依赖与错误类型

**Files:**
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/api/dependencies.py`
- Create: `backend/tests/unit/core/test_admin_dependency.py`

**Interfaces:**
- Consumes: `app.core.errors.AdminForbiddenError`（已存在）、`app.core.config.Settings.admin_token`。
- Produces: `app.core.errors.AdminTokenRequiredError`（新，401）；`app.api.dependencies.require_admin_token(request, settings) -> None`（供 Task 13 的运维路由使用）。

- [ ] **Step 1: 写失败的测试**

```python
"""require_admin_token：只认 X-Admin-Token，忽略 Authorization。"""

from __future__ import annotations

import pytest
from fastapi import Request

from app.api.dependencies import require_admin_token
from app.core.config import AppEnvironment, Settings
from app.core.errors import AdminForbiddenError, AdminTokenRequiredError


def _settings(admin_token: str | None) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=admin_token,
    )


def _request(headers: dict[str, str]) -> Request:
    encoded = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({"type": "http", "headers": encoded, "client": ("testclient", 1234)})


def test_missing_header_raises_401() -> None:
    with pytest.raises(AdminTokenRequiredError):
        require_admin_token(_request({}), _settings("correct-admin-token-value"))


def test_wrong_token_raises_403() -> None:
    with pytest.raises(AdminForbiddenError):
        require_admin_token(
            _request({"X-Admin-Token": "merchant-one-token"}),
            _settings("correct-admin-token-value"),
        )


def test_correct_token_passes() -> None:
    require_admin_token(
        _request({"X-Admin-Token": "correct-admin-token-value"}),
        _settings("correct-admin-token-value"),
    )


def test_authorization_header_is_ignored() -> None:
    with pytest.raises(AdminTokenRequiredError):
        require_admin_token(
            _request({"Authorization": "Bearer correct-admin-token-value"}),
            _settings("correct-admin-token-value"),
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/core/test_admin_dependency.py -v`
Expected: FAIL——`ImportError: cannot import name 'require_admin_token'`。

- [ ] **Step 3: 修改 `app/core/errors.py`**

在 `AdminForbiddenError` 定义之前插入新错误类：

```python
class AdminTokenRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.AUTH_REQUIRED,
            message="请提供有效的管理员凭证",
            status_code=401,
        )
```

- [ ] **Step 4: 修改 `app/api/dependencies.py`**

在文件顶部加 `import hmac`（放在 `from __future__ import annotations` 之后、其他 stdlib import 之前）。

在 `from app.core.errors import AuthRequiredError, RateLimitedError` 这一行改成：

```python
from app.core.errors import AdminForbiddenError, AdminTokenRequiredError, AuthRequiredError, RateLimitedError
```

在 `enforce_rate_limit` 函数之后新增：

```python
def require_admin_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    """运维端点专用认证：只认 `X-Admin-Token`，忽略 `Authorization`。"""

    token = request.headers.get("x-admin-token")
    if not token:
        raise AdminTokenRequiredError
    if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
        raise AdminForbiddenError
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/core/test_admin_dependency.py -v`
Expected: 4 个用例全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/core/errors.py app/api/dependencies.py tests/unit/core/test_admin_dependency.py
git commit -m "feat(core): 新增管理员令牌依赖，401/403 两种失败区分清楚（B7 运维端点前置）"
```

---

### Task 13: `GET /api/admin/ops/status` 运维端点

**Files:**
- Create: `backend/app/api/routes/admin.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_admin_ops.py`

**Interfaces:**
- Consumes: Task 12 的 `require_admin_token`；Task 7 的 `OperationalMetrics`（`rate_limit_hits`、`degraded_count`、`error_code_counts`、`agent_node_average_ms`）；`app.repositories.llm_budget.LlmBudgetRepository`（Task 4 已验证其原子性，这里只读 `snapshot`）；`app.analytics.dates.business_today`。
- Produces: `GET /api/admin/ops/status` 路由，响应模型 `OpsStatusResponse`。

- [ ] **Step 1: 写失败的测试**

```python
"""GET /api/admin/ops/status：401/403/200/未配置时 404。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.main import create_app
from tests.conftest import MERCHANT_ONE_TOKEN
from tests.postgres import TRUNCATE_ALL_TABLES

ADMIN_TOKEN = "test-only-admin-token-value"


def _settings_without_admin_token() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )


def _settings_with_admin_token() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
    )


@pytest.mark.asyncio
async def test_route_absent_when_admin_token_not_configured() -> None:
    app = create_app(_settings_without_admin_token())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/admin/ops/status")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_header_returns_401() -> None:
    app = create_app(_settings_with_admin_token())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/admin/ops/status")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_merchant_token_used_as_admin_header_returns_403() -> None:
    app = create_app(_settings_with_admin_token())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/api/admin/ops/status", headers={"X-Admin-Token": MERCHANT_ONE_TOKEN}
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest_asyncio.fixture
async def admin_app(migrated_postgres: str) -> AsyncIterator[object]:
    """必须先截断 `llm_daily_budget`：Task 4 用固定日期 `date(2026, 8, 6)` 写过预算行，
    如果它恰好等于跑测试当天的业务日期（`business_today()` 取的就是真实当天），不截断的话
    这里断言的 `llm_tokens_used_today == 0` 会被 Task 4 遗留的数据污染，与执行顺序和是否
    重复跑过 `pytest` 有关，必须每次都显式清干净，不能假设一个干净的库。
    """

    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        llm_daily_budget_tokens=5_000,
    )
    database = Database(settings)
    async with database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        await session.commit()
    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest.mark.asyncio
async def test_correct_token_returns_200_with_safe_payload(admin_app: object) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN}
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "llm_tokens_used_today",
        "llm_tokens_remaining_today",
        "llm_calls_today",
        "rate_limit_hits",
        "degraded_count",
        "error_code_counts",
        "agent_node_average_ms",
    }
    assert body["llm_tokens_used_today"] == 0
    assert body["llm_tokens_remaining_today"] == 5_000

    raw = response.text
    assert ADMIN_TOKEN not in raw
    assert "postgresql" not in raw.lower()
    assert MERCHANT_ONE_TOKEN not in raw
```

`admin_app` fixture 依赖 `migrated_postgres`（`tests/conftest.py` 里已有的 session-scoped fixture），本文件不需要重新声明它——pytest 会从 `conftest.py` 自动发现。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_admin_ops.py -v`
Expected: FAIL——全部 404（路由还不存在，因为 `admin.py` 还没创建、也没接进 `main.py`）。

- [ ] **Step 3: 创建 `app/api/routes/admin.py`**

```python
"""运维端点：暴露费用防护与限流的运行时状态，仅限管理员令牌访问。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.analytics.dates import business_today
from app.api.dependencies import get_app_settings, get_database, require_admin_token
from app.core.config import Settings
from app.core.errors import error_responses
from app.db.session import Database
from app.repositories.llm_budget import LlmBudgetRepository

router = APIRouter(prefix="/admin", tags=["admin"])


class OpsStatusResponse(BaseModel):
    """系统级聚合快照，不含任何商家标识、Token 明文或 Prompt 内容。"""

    llm_tokens_used_today: int
    llm_tokens_remaining_today: int
    llm_calls_today: int
    rate_limit_hits: int
    degraded_count: int
    error_code_counts: dict[str, int]
    agent_node_average_ms: dict[str, float]


@router.get(
    "/ops/status",
    response_model=OpsStatusResponse,
    responses=error_responses(401, 403),
)
async def ops_status(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> OpsStatusResponse:
    repository = LlmBudgetRepository(database)
    usage_date = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    snapshot = await repository.snapshot(usage_date=usage_date)
    metrics = request.app.state.metrics
    return OpsStatusResponse(
        llm_tokens_used_today=snapshot.consumed_tokens,
        llm_tokens_remaining_today=max(
            settings.llm_daily_budget_tokens - snapshot.consumed_tokens, 0
        ),
        llm_calls_today=snapshot.call_count,
        rate_limit_hits=metrics.rate_limit_hits,
        degraded_count=metrics.degraded_count,
        error_code_counts=metrics.error_code_counts,
        agent_node_average_ms=metrics.agent_node_average_ms,
    )
```

- [ ] **Step 4: 在 `main.py` 里按 `settings.admin_token` 条件注册路由**

`admin_router` **不**并入 `app/api/router.py` 的 `api_router`（那个聚合路由没有拿到 `settings`，没法做条件注册）。改为在 `app/main.py` 顶部 import 块加：

```python
from app.api.routes.admin import router as admin_router
```

在 `app.include_router(api_router, prefix="/api")` 之后加：

```python
    app.include_router(api_router, prefix="/api")
    if resolved_settings.admin_token:
        app.include_router(admin_router, prefix="/api")
    return app
```

未配置 `admin_token` 时这个路由完全不存在，请求会落到 FastAPI 默认的 404 处理，天然满足「未配置管理员令牌时端点整体关闭」。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/api/test_admin_ops.py -v`
Expected: 4 个用例全部 PASS（第 4 个需要真实 Postgres，缺库时会被 `migrated_postgres` fixture 跳过，本地有 `docker-compose -p borough up -d postgres` 时应该跑通）。

- [ ] **Step 6: 跑一次全量测试确认路由聚合和条件注册没有破坏其他端点**

Run: `uv run pytest -x -q`
Expected: 除因缺库跳过的以外全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/api/routes/admin.py app/main.py tests/api/test_admin_ops.py
git commit -m "feat(api): 新增 GET /api/admin/ops/status 运维端点（B7）"
```

---

### Task 14: `create_app()` 永不启用 Debug 的回归测试

**Files:**
- Create: `backend/tests/unit/core/test_app_debug_disabled.py`

**Interfaces:**
- Consumes: `app.main.create_app`。
- Produces: 无。

- [ ] **Step 1: 写测试**

```python
"""生产部署前置条件：FastAPI 应用永远不以 debug=True 构造。"""

from __future__ import annotations

from app.core.config import AppEnvironment, Settings
from app.main import create_app


def test_create_app_never_enables_debug_mode() -> None:
    for env in (AppEnvironment.DEVELOPMENT, AppEnvironment.TEST, AppEnvironment.PRODUCTION):
        settings = Settings(
            app_env=env,
            database_url="postgresql+psycopg://user:pass@localhost/test",
            frontend_origin="http://localhost:5173",
            export_signing_secret=(
                "a-genuinely-long-random-signing-secret-value"
                if env is AppEnvironment.PRODUCTION
                else None
            ),
        )
        app = create_app(settings)

        assert app.debug is False
```

- [ ] **Step 2: 运行测试确认通过**

Run: `uv run pytest tests/unit/core/test_app_debug_disabled.py -v`
Expected: PASS——`FastAPI(...)` 从未显式传 `debug=`，默认值就是 `False`，这条测试只是把这个事实钉死，防止未来有人为了本地调试加个 `debug=True` 却忘了限制在非生产环境。

- [ ] **Step 3: 提交**

```bash
git add tests/unit/core/test_app_debug_disabled.py
git commit -m "test(core): 钉住 create_app 永不启用 debug 模式（B7 生产前置条件）"
```

---

### Task 15: `railway.json`

**Files:**
- Create: `backend/railway.json`

**Interfaces:**
- Consumes: 无（纯配置文件，Railway 平台读取）。
- Produces: 无代码接口；Task 16 的 `docs/deployment.md` 会引用这个文件。

- [ ] **Step 1: 创建文件**

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "healthcheckPath": "/api/health",
    "healthcheckTimeout": 30,
    "releaseCommand": "python -m alembic upgrade head",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

- [ ] **Step 2: 校验 JSON 语法**

Run: `python -c "import json; json.load(open('railway.json', encoding='utf-8'))"`（在 `backend/` 目录下）
Expected: 无输出、退出码 0（说明是合法 JSON）。

- [ ] **Step 3: 确认 `releaseCommand` 在容器里能找到 `alembic.ini`**

`Dockerfile` 里 `WORKDIR /app`，`alembic.ini` 被 COPY 到 `/app/alembic.ini`（见 `backend/Dockerfile:30`），Railway 的 `releaseCommand` 默认在镜像的 `WORKDIR` 下执行，`python -m alembic upgrade head` 不需要额外 `--config` 参数。这一步不需要跑命令，只需要读 `Dockerfile` 确认路径一致（已在设计阶段确认，这里复核一遍）。

- [ ] **Step 4: 提交**

```bash
git add railway.json
git commit -m "chore(deploy): 新增 Railway 配置即代码（健康检查、迁移发布步骤）"
```

---

### Task 16: `docs/deployment.md` 部署运维手册

**Files:**
- Create: `docs/deployment.md`（仓库根目录下的 `docs/`，不是 `backend/docs`）

**Interfaces:**
- Consumes: 无代码接口；引用 Task 6 的 `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`、Task 13 的 `/api/admin/ops/status`、Task 15 的 `railway.json`。
- Produces: 无。

- [ ] **Step 1: 写文档**

```markdown
# 部署手册（Railway）

> 本文档面向执行实际部署的人（人类或 coding agent）。代码层面的 B7 工作已经完成
> （见 `docs/superpowers/specs/2026-08-06-backend-b7-cost-guard-ops-design.md`），
> 本文档只覆盖 Railway 控制台/CLI 里需要手动做的步骤。

## 1. 创建两个 Service

1. **PostgreSQL**：在 Railway 项目里添加官方 PostgreSQL 插件，得到一个 `DATABASE_URL`。
2. **Backend**：新建 Service，Root Directory 设为 `/backend`（仓库里后端代码所在目录），
   构建方式选 Dockerfile（`backend/railway.json` 已经声明 `builder: DOCKERFILE`，
   Railway 检测到这个文件会自动使用它，不需要在控制台里重复配置健康检查路径）。

Backend Service 的环境变量里，`DATABASE_URL` 用 Railway 的变量引用语法指向 PostgreSQL
Service（不要手填连接串），例如 `${{Postgres.DATABASE_URL}}`。

## 2. 必需环境变量

| 变量 | 用途 | 取值约束（见 `backend/app/core/config.py::Settings`） |
| --- | --- | --- |
| `DATABASE_URL` | 数据库连接 | 引用 PostgreSQL Service，不手填 |
| `FRONTEND_ORIGIN` | CORS 精确 Origin | 必须是 `scheme://host[:port]`，禁止 `*`、禁止带路径/查询/凭据 |
| `LLM_API_KEY` | 真实 DeepSeek 密钥 | 配了这个就必须同时配 `ADMIN_TOKEN`（`Settings.enforce_environment_safety` 会拒绝启动） |
| `ADMIN_TOKEN` | 运维端点凭证 | 生产环境下长度需 ≥16 且不能含 `placeholder`/`change-me`/`example`/`development`/`<` 等占位标记 |
| `EXPORT_SIGNING_SECRET` | CSV 导出签名 | 生产环境必填，同样受占位值检测约束 |
| `APP_ENV` | 运行环境 | 设为 `production`（会自动关闭 `/api/demo/merchants`，见 `Settings.enforce_environment_safety`） |
| `TRUSTED_PROXY_HOPS` | 可信代理跳数 | Railway 是单层反向代理，设为 `1` |
| `TRUSTED_PROXY_IPS` | 可信直连对端 IP 列表 | 逗号分隔；不确定 Railway 内部代理的固定出口 IP 时，先部署后从 `X-Forwarded-For` 之外的连接信息核实，再回填 |
| `RATE_LIMIT_PER_MINUTE` | 单 Token+IP 每分钟限流 | 默认 10，按预期演示流量调整 |
| `LLM_DAILY_BUDGET_TOKENS` | 每日 LLM token 预算 | 默认 20000，按真实预算调整 |

## 3. 已经满足、不需要重复配置的checklist 项

- **CORS 精确 Origin**：`Settings.frontend_origin` 的校验器已经拒绝 `*` 和任何带路径/查询/
  凭据的值（`backend/app/core/config.py:82-100`），`app/main.py` 用它构造
  `CORSMiddleware(allow_origins=[...])`，不需要在 Railway 侧另配。
- **生产环境日志走 JSON**：`app/core/logging.py::configure_logging` 按 `APP_ENV` 自动切换
  `JSONRenderer`/`ConsoleRenderer`，只要 `APP_ENV=production` 就自动生效。
- **生产环境关闭 Debug**：`backend/tests/unit/core/test_app_debug_disabled.py`
  （B7 Task 14）机械钉住 `create_app()` 永不以 `debug=True` 构造。
- **数据库连接重试**：`Database.connect_with_retry()`（`app/db/session.py`）已在
  `app/main.py` 的 `lifespan` 里调用，应用早于数据库启动时会按
  `db_connect_max_attempts`/`db_connect_retry_seconds` 重试，不需要额外配置。
- **Migration 只执行一次**：`railway.json` 的 `deploy.releaseCommand` 由 Railway 保证在
  新实例接流量前执行且只执行一次，不需要应用代码里加分布式锁。
- **容器临时磁盘不保存正式附件**：截至本轮，B8 附件功能尚未开始，代码库里没有任何写本地
  磁盘的附件逻辑，这一条目前是可验证的既成事实；**进入 B8 后必须重新审计这一条**。

## 4. 手动验收清单（对应 `docs/backend-development-plan.md` §B7「验收（MVP 出口）」）

- [ ] Railway 健康检查（`/api/health`）在部署后持续通过；
- [ ] 重启 Backend Service 后数据仍在（验证 `DATABASE_URL` 确实指向持久化的 PostgreSQL Service，
      不是临时容器内数据库）；
- [ ] 应用先于数据库启动时能重试成功（可以临时把 Backend Service 设为比 PostgreSQL 更早部署，
      观察日志里的 `database_startup_degraded` 告警是否在 PostgreSQL 就绪后自愈）；
- [ ] `/api/demo/merchants` 在生产配置下不可访问（`APP_ENV=production` 会自动关闭它，
      部署后实测确认返回 404/403）；
- [ ] 超过每日预算后不再调用 LLM 且返回显式降级（可以临时把 `LLM_DAILY_BUDGET_TOKENS` 调到很小的值，
      触发几轮对话后确认 `ChatResponse.degraded=True` 而不是报错）；
- [ ] 超过频次限制返回 `RATE_LIMITED`；
- [ ] 伪造 `X-Forwarded-For` 无法绕过限流（自动化测试见
      `backend/tests/api/test_rate_limit_trust_boundary.py`，部署后可用两个不同来源 IP 的
      真实请求复核一次）；
- [ ] `GET /api/admin/ops/status` 需要 `X-Admin-Token` 且不泄露敏感数据（自动化测试见
      `backend/tests/api/test_admin_ops.py`）；
- [ ] SIGTERM 优雅关闭：见下方「手动 SIGTERM 验证」；
- [ ] 前端可以通过部署域名完成核心 E2E，SSE 在真实 CORS 环境下正常流式（依赖前端 F3 完成后再验收，
      不在本轮 B7 范围内）。

## 5. 手动 SIGTERM 验证（无法自动化，每次改动 `app/run.py` 后重新做一次）

```bash
docker build -t borough-backend ./backend
docker run --rm -p 8000:8000 --env-file backend/.env borough-backend
# 另开一个终端，发起一个会触发多轮 LangGraph 节点的长请求，紧接着：
docker stop <container-id>
```

预期：该请求收到完整的 SSE `done`/`error` 事件收尾，而不是连接被直接掐断；容器在
`GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`（`backend/app/run.py`，当前 30 秒）内退出。

## 6. 多实例限制（如实记录，不是待办）

限流器（`SlidingWindowRateLimiter`）、LLM 预算的估算-reserve 协调缓存路径、以及
`OperationalMetrics` 全部是进程内状态，不跨实例同步。`LlmBudgetRepository.reserve` 本身在数据库
层是原子的，所以**预算不会真的超发**，但如果同时起多个 Backend Service 副本：

- 限流会变成「每个副本各自的每分钟 N 次」，实际总吞吐是 `N × 副本数`；
- `GET /api/admin/ops/status` 里的 `rate_limit_hits`/`degraded_count`/`error_code_counts`/
  `agent_node_average_ms` 只反映处理这次请求的那个副本的本地状态，不是全局聚合。

MVP 阶段没有 Redis，这是刻意的取舍（见 `docs/backend-development-plan.md` §B7「LLM 费用与限流」
「MVP 无 Redis，限流使用进程内计数器」）。如果未来需要多副本，需要先引入共享存储再放开这个约束，
不要在没有共享状态的前提下直接加副本数。
```

- [ ] **Step 2: 检查文档里引用的每个文件路径/常量确实存在**

对照文档里提到的 `backend/app/core/config.py:82-100`、`app/run.py::GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`、
`backend/tests/unit/core/test_app_debug_disabled.py`、`backend/tests/api/test_rate_limit_trust_boundary.py`、
`backend/tests/api/test_admin_ops.py` 逐一确认文件和符号确实存在（前面的任务应该都已经创建好），
如果行号因为后续任务的改动漂移了，改成不带行号的引用（模块名 + 符号名）。

- [ ] **Step 3: 提交**

```bash
git add docs/deployment.md
git commit -m "docs(deploy): 新增 Railway 部署运维手册（B7）"
```

---

### Task 17: `CURRENT_STAGE` 更新为 `"B7"`

**Files:**
- Modify: `backend/tests/unit/agent/test_stage_reference_hygiene.py`

**Interfaces:**
- Consumes: 该文件已有的 `CURRENT_STAGE` 常量和文案卫生扫描逻辑。
- Produces: 无。

**这个任务必须放在所有其他任务之后执行**——提前改会让文案卫生防线用新阶段名去扫描还没写完的旧阶段代码，产生误报或漏报。

- [ ] **Step 1: 确认当前值**

Run: `grep -n "CURRENT_STAGE" tests/unit/agent/test_stage_reference_hygiene.py`
Expected: 找到一行 `CURRENT_STAGE = "B6"`（或类似赋值）。

- [ ] **Step 2: 修改**

把 `CURRENT_STAGE = "B6"` 改成 `CURRENT_STAGE = "B7"`。

- [ ] **Step 3: 运行该测试确认通过**

Run: `uv run pytest tests/unit/agent/test_stage_reference_hygiene.py -v`
Expected: PASS——本轮新增的所有代码和 fixture 都不应该包含「将在 B7 接入」这类指向当前阶段的过期前向引用（B7 本身就是本轮在做的阶段，写这种引用没有意义；引用更后面的 B8/B9 是允许的）。如果这一步失败，说明本计划前面某个任务里不小心写了类似「B7 将实现」的字样，回到对应文件删掉那句话，改成如实描述当前状态。

- [ ] **Step 4: 提交**

```bash
git add tests/unit/agent/test_stage_reference_hygiene.py
git commit -m "chore(agent): CURRENT_STAGE 推进到 B7（文案卫生防线边界更新）"
```

---

### Task 18: 最终验证（真实 Postgres 全量回归 + 静态检查）

**Files:**
- 不修改任何文件，纯验证任务。

**Interfaces:**
- 无。

- [ ] **Step 1: 启动本地 Postgres**

Run: `docker-compose -p borough up -d postgres`（仓库根目录）

- [ ] **Step 2: 跑真实数据库全量回归**

Run（`backend/` 目录下）: `$env:REQUIRE_INTEGRATION_DB="1"; uv run pytest`（PowerShell）或
`REQUIRE_INTEGRATION_DB=1 uv run pytest`（bash）
Expected: 全部 PASS，0 skipped——包括本计划新增的所有单元/集成/API 测试，以及此前遗留、
一直没有用真实库复核过的 B5/B6 用例（`docs/project-progress.md`「最近验证」提到的
「652 passed 未用真实库复核」那批）。

- [ ] **Step 3: 静态检查**

Run（`backend/` 目录下）:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```
Expected: 三条命令全部零错误退出。

- [ ] **Step 4: 更新 `docs/project-progress.md`**

在「当前阶段」和「已完成」「最近验证」「下一步」四个小节里，把本轮 B7 工作的完成情况
如实写入——具体测试通过数字必须来自 Step 2/3 的真实输出，不得照抄本计划文档里的预估。
格式和详略程度参照文件里已有的 B4/B5/B6 记录段落风格。

- [ ] **Step 5: 提交**

```bash
git add docs/project-progress.md
git commit -m "docs: B7 补测试与剩余基础设施收口，记录真实库回归结果"
```

---

## 自查记录（写计划时已做，仅供实现者参考）

- **Spec 覆盖**：spec 第 3.1–3.5 节分别对应 Task 1–5（补测试）、Task 6（Docker）、
  Task 7–11（可观测性）、Task 12–14（运维端点）、Task 15–16（Railway），第 4 节收尾对应
  Task 17，第 5 节测试策略表格里列出的每个文件都能在上面找到对应任务。
- **占位符扫描**：所有 Step 都给了可直接运行的完整代码/命令，没有「补充测试」「视情况处理」
  这类占位描述；Task 10 的替身类名因为需要先读现存文件确认真实命名，明确标注了「必须先打开文件
  确认」而不是假装知道答案。
- **类型/签名一致性**：`OperationalMetrics`（Task 7）在 Task 8/9/10/11/13 里始终用同一组方法名
  （`record_error_code`、`record_route_duration`、`record_node_duration`、
  `rate_limit_hits`/`degraded_count` 直接自增）；`NodeTimerLike` Protocol（Task 11）与
  `OperationalMetrics.record_node_duration`（Task 7）签名一致；`ChatService.__init__` 新增的
  `metrics` 参数（Task 10）与 `MerchantQaGraph.__init__` 新增的 `node_timer` 参数（Task 11）
  都在 Task 11 Step 6/Task 10 Step 5 里对应接回 `app/api/dependencies.py::get_chat_service`
  的同一处构造调用。
