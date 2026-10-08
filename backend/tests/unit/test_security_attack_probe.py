"""安全评测本身的反向验证：未运行攻击或移除围栏时必须变红。"""

from typing import cast

import pytest

from app.agent.loop.runner import run_loop
from app.db.session import Database
from tests.eval.attack_llm import install_attack
from tests.eval.test_security_gate import load_security_cases
from tests.unit.agent.loop.loop_doubles import (
    build_gates,
    customer_request,
    limits,
)


@pytest.mark.asyncio
async def test_attack_probe_requires_the_expected_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    case_id = "SEC-INJECTION-001"
    case = next(c for c in load_security_cases() if c.id == case_id)
    fake = install_attack(case, cast(Database, None), monkeypatch)
    assert fake is not None
    with pytest.raises(AssertionError, match="攻击模型没有执行"):
        await fake.verify()
    fake.calls_seen = 1
    fake.attempted = True
    fake.admitted.append(fake.attack)
    with pytest.raises(AssertionError, match="预期的角色/身份/来源闸门"):
        await fake.verify()
    assert fake.expected_gate is not None
    fake.blocked.append((fake.attack, fake.expected_gate))
    await fake.verify()


@pytest.mark.asyncio
async def test_attack_probe_detects_removed_customer_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = next(c for c in load_security_cases() if c.id == "SEC-INJECTION-001")
    fake = install_attack(case, cast(Database, None), monkeypatch)
    assert fake is not None
    monkeypatch.setattr("app.agent.loop.runner.fence", lambda text, **kw: text)
    gates, _ = build_gates()
    with pytest.raises(AssertionError):
        await run_loop(customer_request(), llm=fake, gates=gates, tools=[], limits=limits())
