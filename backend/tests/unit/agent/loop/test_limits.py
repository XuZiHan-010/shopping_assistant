"""循环上限与 LLM 调用预算公式（§6.10，N2 Task 3；Astra N2-2）。

两套重试是乘加关系——配错了应当启动即失败，而不是运行时伪装成「模型不听话」。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import EnvSettingsSource

from app.agent.loop.limits import LoopLimits
from app.core.config import AppEnvironment, Settings, agent_loop_llm_call_floor


def _settings(**overrides: Any) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        **overrides,
    )


def test_formula_counts_first_generation_inside_turns() -> None:
    """最终作答由最后一轮决策产生：第一次质量尝试的生成不重复计数。"""

    assert agent_loop_llm_call_floor(
        max_turns=8, compaction_max_calls=1, quality_max_attempts=2
    ) == 8 + 1 + (2 * 2 - 1)


def test_loop_budget_rejected_when_too_small_for_worst_path() -> None:
    with pytest.raises(ValidationError, match="AGENT_LOOP_MAX_LLM_CALLS"):
        _settings(
            agent_loop_max_turns=8,
            agent_loop_max_llm_calls=10,
            compaction_max_calls=1,
            agent_loop_quality_max_attempts=2,
        )  # 8 + 1 + 3 = 12 > 10


def test_loop_budget_accepted_at_exact_floor() -> None:
    """边界：恰好等于下限必须能启动，不能多要一次。"""

    s = _settings(
        agent_loop_max_turns=8,
        agent_loop_max_llm_calls=12,
        compaction_max_calls=1,
        quality_max_attempts=2,
    )
    assert s.agent_loop_max_llm_calls == 12


def test_loop_budget_rejected_one_below_floor() -> None:
    with pytest.raises(ValidationError, match="AGENT_LOOP_MAX_LLM_CALLS"):
        _settings(
            agent_loop_max_turns=8,
            agent_loop_max_llm_calls=11,
            compaction_max_calls=1,
            agent_loop_quality_max_attempts=2,
        )


def test_raising_quality_attempts_without_raising_budget_fails_startup() -> None:
    """任一加数加码都要同步预算，否则拒绝启动。"""

    with pytest.raises(ValidationError, match="AGENT_LOOP_MAX_LLM_CALLS"):
        _settings(agent_loop_quality_max_attempts=3)  # 8 + 1 + 5 = 14 > 12


def test_default_loop_budget_satisfies_formula() -> None:
    s = _settings()
    assert (s.agent_loop_max_turns, s.agent_loop_max_tool_calls) == (8, 16)
    assert s.agent_loop_wall_clock_seconds == 60
    assert s.agent_loop_max_llm_calls == 12
    assert s.agent_loop_max_llm_calls >= (
        s.agent_loop_max_turns + s.compaction_max_calls + 2 * s.agent_loop_quality_max_attempts - 1
    )


def test_v1_budget_is_untouched_by_loop_formula() -> None:
    """v1 上限不得被 v2 公式牵动：两条链路各用各的上限。"""

    s = _settings(agent_loop_max_turns=20, agent_loop_max_llm_calls=40)
    assert s.llm_max_calls_per_request == 10


def test_v1_quality_attempts_do_not_affect_loop_budget() -> None:
    """v1 按原注释调到三轮质量尝试，不得因为 v2 公式而拒绝启动：两条链路各用各的字段。"""

    s = _settings(quality_max_attempts=3, llm_max_calls_per_request=12)
    assert s.quality_max_attempts == 3
    assert s.agent_loop_quality_max_attempts == 2


def test_v1_budget_is_not_validated_against_loop_formula() -> None:
    """v1 的 10 小于 v2 下限 12，这不是配置错误：它根本不参与 v2 公式。"""

    s = _settings(llm_max_calls_per_request=5)
    assert s.llm_max_calls_per_request == 5


def test_loop_settings_use_unprefixed_environment_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """R6：沿用无前缀命名。测试夹具关掉了 Settings 的环境来源，这里直接问环境来源本身。"""

    monkeypatch.setenv("AGENT_LOOP_MAX_TURNS", "4")
    monkeypatch.setenv("AGENT_LOOP_MAX_TOOL_CALLS", "6")
    monkeypatch.setenv("AGENT_LOOP_WALL_CLOCK_SECONDS", "30")
    monkeypatch.setenv("AGENT_LOOP_MAX_LLM_CALLS", "8")
    monkeypatch.setenv("AGENT_LOOP_QUALITY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("COMPACTION_MAX_CALLS", "0")
    read = EnvSettingsSource(Settings)()
    assert {k: read[k] for k in read if k.startswith(("agent_loop_", "compaction_"))} == {
        "agent_loop_max_turns": "4",
        "agent_loop_max_tool_calls": "6",
        "agent_loop_wall_clock_seconds": "30",
        "agent_loop_max_llm_calls": "8",
        "agent_loop_quality_max_attempts": "1",
        "compaction_max_calls": "0",
    }


def test_loop_limits_from_settings() -> None:
    s = _settings()
    limits = LoopLimits.from_settings(s)
    assert limits == LoopLimits(
        max_turns=8,
        max_tool_calls=16,
        max_llm_calls=12,
        wall_clock_seconds=60,
        max_tokens=s.llm_max_tokens_per_request,
        quality_max_attempts=2,
    )
    budget = limits.new_budget()
    assert (budget.max_calls, budget.max_tokens) == (12, s.llm_max_tokens_per_request)


@pytest.mark.parametrize(
    "field", ["max_turns", "max_tool_calls", "max_llm_calls", "max_tokens", "quality_max_attempts"]
)
def test_loop_limits_reject_non_positive(field: str) -> None:
    values: dict[str, Any] = {
        "max_turns": 1,
        "max_tool_calls": 1,
        "max_llm_calls": 3,
        "wall_clock_seconds": 1.0,
        "max_tokens": 100,
        "quality_max_attempts": 1,
    }
    values[field] = 0
    with pytest.raises(ValueError, match=field):
        LoopLimits(**values)
