"""N1 关键安全集：CI 硬门禁（E3，PRD §15 N1）。

零失败。任一失败即阻断合并；零 skip 由 `tests/eval/conftest.py` 的钩子兜底。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.config import AppEnvironment, Settings
from app.eval.cases import EvalCase, load_cases_from_directory, validate_coverage
from app.eval.primitives import PRIMITIVES
from app.eval.security_harness import SecurityHarness
from app.main import create_app
from tests.eval.attack_llm import AttackLlm, install_attack

pytestmark = pytest.mark.integration

_DATASET_DIR = Path(__file__).resolve().parents[2] / "app" / "eval" / "datasets" / "security"

CURRENT_MILESTONE = "N2"
CATEGORY_INTRODUCED_IN = {
    "CROSS": "N1",
    "SQLI": "N1",
    "IDENTITY": "N1",
    "BUYERKEY": "N1",
    "APPROVAL": "N2",
    "SELFAPPROVE": "N2",
    "INJECTION": "N2",
    "CATALOG": "N2",
    "CART": "N2",
    "ORDER": "N2",
}
MILESTONES = ("N1", "N2", "N3", "N4", "N5")

#: AGENTS.md §8.3「公开」类端点里属于 v2 且已落地的部分；每条都要写明理由。
#: 不得把「还没来得及写用例」的路由放进来。
PUBLIC_V2_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # 创建访客会话是唯一无需任何凭证即可调用的 v2 端点（未知/未激活
        # shop_slug 统一 403，不泄露店铺是否存在），本身就是 SEC-IDENTITY-001
        # 打的端点。
        ("POST", "/api/v2/shop/sessions"),
    }
)

_PATH_PARAM = re.compile(r"\{[^}]+\}")


def normalize(path: str) -> str:
    return _PATH_PARAM.sub("{}", path)


def load_security_cases() -> list[EvalCase]:
    return load_cases_from_directory(_DATASET_DIR)


def _due(milestone: str) -> bool:
    return MILESTONES.index(milestone) <= MILESTONES.index(CURRENT_MILESTONE)


def test_dataset_loads_without_error() -> None:
    cases = load_security_cases()
    assert len(cases) >= 12


def test_dataset_layer_coverage() -> None:
    cases = [c for c in load_security_cases() if _due(c.introduced_in)]
    validate_coverage(cases)
    # 原语没有 HTTP 显示语言；只有最终攻击落在端点的用例才计入端点分层。
    present = {
        (c.role, c.locale)
        for c in cases
        if c.form == "ENDPOINT" and c.turns[-1].request is not None
    }
    required = {
        (role, locale) for role in ("CUSTOMER", "MERCHANT") for locale in ("zh-CN", "en-US")
    }
    assert not required - present, sorted(required - present)


def test_security_set_has_no_skips() -> None:
    """安全集不允许 skip——「暂时跳过」等于「暂时不安全」。"""

    assert all(c.skip_reason is None for c in load_security_cases())


def test_due_categories_have_at_least_three_cases() -> None:
    counts = Counter(c.id.split("-")[1] for c in load_security_cases() if _due(c.introduced_in))
    due = {cat for cat, ms in CATEGORY_INTRODUCED_IN.items() if _due(ms)}
    missing = {cat: counts.get(cat, 0) for cat in due if counts.get(cat, 0) < 3}
    assert not missing, missing


@pytest.mark.asyncio
async def test_attack_model_uses_registered_write_tools(security_app: FastAPI) -> None:
    """注入攻击必须打真实写工具；自批要先起草真实草稿再尝试不存在的应用入口。"""

    registry = security_app.state.tool_registry
    for case in load_security_cases():
        if "INJECTION" not in case.id and "SELFAPPROVE" not in case.id:
            continue
        if case.id == "SEC-INJECTION-003":
            continue  # 请求 Schema 在模型调用之前拦截
        scripted = AttackLlm(case, security_app.state.database)
        assert registry.find(scripted.attack) is not None or case.id.startswith(
            "SEC-SELFAPPROVE"
        ), case.id
        if case.id.startswith("SEC-SELFAPPROVE"):
            assert scripted.stages_real_draft, case.id


def test_case_targets_are_implemented() -> None:
    """PRD §15：用例随实际对象交付，不靠提前推进里程碑放行。

    各阶段所有 turn 都须指向已注册对象；不存在的端点即使预期 404 也拒绝。
    最低类别数量仍由 CURRENT_MILESTONE 控制，所有登记用例照常实际执行。
    """
    routes = _registered_routes()
    missing: list[str] = []
    for case in load_security_cases():
        if case.form == "ENDPOINT" and case.turns[-1].request is None:
            missing.append(f"{case.id}: ENDPOINT 最终 turn 必须是 HTTP 请求")
        if case.form == "PRIMITIVE" and any(t.request is not None for t in case.turns):
            missing.append(f"{case.id}: PRIMITIVE 不得伪装 HTTP 用例")
        for turn in case.turns:
            if turn.request is not None:
                target = (turn.request.method, normalize(turn.request.path))
                if target not in routes:
                    missing.append(f"{case.id}: 未实现端点 {target}")
            elif turn.primitive is not None and turn.primitive.name not in PRIMITIVES:
                missing.append(f"{case.id}: 未登记原语 {turn.primitive.name}")
    assert not missing, missing


def _registered_routes() -> set[tuple[str, str]]:
    app = create_app(
        Settings(
            app_env=AppEnvironment.TEST,
            database_url="postgresql+psycopg://user:pass@localhost/test",
            frontend_origin="http://localhost:5173",
            llm_api_key=None,
        )
    )
    return {
        (method.upper(), normalize(path))
        for path, methods in app.openapi()["paths"].items()
        for method in methods
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    }


def test_every_v2_route_has_an_endpoint_security_case() -> None:
    """路由覆盖守卫：v2 路由一上线，就必须有端点级安全用例。

    枚举方式特意选 `app.openapi()`，不直接走 `app.routes`：FastAPI 近期版本把
    `include_router` 的子路由折叠进内部的 `_IncludedRouter`/`_EffectiveRouteContext`
    惰性结构，`app.routes` 顶层不再能直接读出子路由的有效路径；`openapi()`
    是稳定的公开契约产出，且本来就是前端/OpenAPI 导出实际依赖的同一份真相。
    """

    routes = {
        (method, path)
        for method, path in _registered_routes()
        if path.startswith("/api/v2/") and method not in {"HEAD", "OPTIONS"}
    }
    covered = {
        (turn.request.method, normalize(turn.request.path))
        for case in load_security_cases()
        if case.form == "ENDPOINT"
        for turn in [case.turns[-1]]
        if turn.request is not None
    }
    uncovered = routes - covered - PUBLIC_V2_ROUTES
    assert not uncovered, sorted(uncovered)


@pytest.fixture
def harness(security_harness: SecurityHarness) -> SecurityHarness:
    return security_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load_security_cases(), ids=lambda c: c.id)
async def test_security_case_passes(
    case: EvalCase,
    harness: SecurityHarness,
    security_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E3 硬门禁：零失败。任一失败即阻断。"""

    attack = install_attack(case, security_app.state.database, monkeypatch)
    if attack is not None:
        await attack.prepare()
    result = await harness.run(case)
    assert result.passed, result.failure_detail
    if attack is not None:
        await attack.verify()
