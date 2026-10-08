"""质量场景登记（交易计划 Task 7）：S1 已登记、可加载、只指向已实现的端点与原语。

场景放在 `quality/scenarios/`，N1 基线脚本只加载 `quality/` 根目录，互不干扰；
这里防止两件事悄悄发生：场景文件坏了没人发现，或者被挪回根目录误跑 v1 商家链路。
"""

from __future__ import annotations

from pathlib import Path

from app.eval.cases import load_cases_from_directory
from app.eval.primitives import PRIMITIVES
from tests.eval.test_security_gate import _registered_routes, normalize

_QUALITY = Path(__file__).resolve().parents[2] / "app" / "eval" / "datasets" / "quality"
_SCENARIOS = _QUALITY / "scenarios"


def test_s1_is_registered_in_both_locales() -> None:
    cases = {case.id: case for case in load_cases_from_directory(_SCENARIOS)}

    assert {"QLT-S1-001", "QLT-S1-002"} <= set(cases)
    assert {cases["QLT-S1-001"].locale, cases["QLT-S1-002"].locale} == {"zh-CN", "en-US"}
    assert all(
        case.risk == "QUALITY" and case.role == "CUSTOMER"
        for case in cases.values()
        if case.id.startswith("QLT-S1-")
    )


def test_s3_is_registered_in_both_locales() -> None:
    cases = {case.id: case for case in load_cases_from_directory(_SCENARIOS)}

    assert {"QLT-S3-001", "QLT-S3-002"} <= set(cases)
    assert {cases["QLT-S3-001"].locale, cases["QLT-S3-002"].locale} == {"zh-CN", "en-US"}
    assert all(
        case.risk == "QUALITY" and case.role == "MERCHANT"
        for case in cases.values()
        if case.id.startswith("QLT-S3-")
    )


def test_scenarios_target_only_implemented_routes_and_primitives() -> None:
    routes = _registered_routes()
    for case in load_cases_from_directory(_SCENARIOS):
        for turn in case.turns:
            if turn.request is not None:
                assert (turn.request.method, normalize(turn.request.path)) in routes, case.id
            else:
                assert turn.primitive is not None and turn.primitive.name in PRIMITIVES, case.id


def test_scenarios_stay_out_of_the_v1_baseline_directory() -> None:
    baseline_ids = {case.id for case in load_cases_from_directory(_QUALITY)}

    assert not any(case_id.startswith(("QLT-S1-", "QLT-S3-")) for case_id in baseline_ids)


def test_n5_quick_prompts_are_registered_with_the_storefront_copy() -> None:
    """顾客端首页六条快捷提问（D-N5-4）登记为质量场景。

    五个顾客 Skill + 规则问答，中文全量、英文抽两条。

    文案与 `shop/src/i18n/messages.ts` 逐字一致——顾客实际点到的就是被评测的那句话。
    """

    cases = [c for c in load_cases_from_directory(_SCENARIOS) if c.id.startswith("QLT-N5-")]
    storefront = (
        Path(__file__).resolve().parents[3] / "shop" / "src" / "i18n" / "messages.ts"
    ).read_text(encoding="utf-8")

    assert len(cases) == 8
    assert all(c.role == "CUSTOMER" and c.risk == "QUALITY" for c in cases)
    assert all(c.introduced_in == "N5" for c in cases)
    assert {c.skill for c in cases if c.locale == "zh-CN"} == {
        "search-discovery",
        "purchase-research",
        "planning-goals",
        "after-sales-service",
        "memory-personalization",
        "platform-rules",
    }
    assert sum(c.locale == "en-US" for c in cases) == 2
    for case in cases:
        request = case.turns[-1].request
        assert request is not None and request.path == "/api/v2/shop/chat"
        message = (request.json_body or {})["message"]
        assert f"'{message}'" in storefront, f"{case.id} 的提问不在顾客端首页文案里"


def test_main_evaluation_set_meets_the_e1_size_and_layers() -> None:
    """PRD E1 / §12.6：主评测集 ≥ 100 条，按角色、风险、语言分层，含多轮；skip 不计入。"""

    datasets = _QUALITY.parent
    cases = [
        *load_cases_from_directory(datasets / "security"),
        *load_cases_from_directory(_QUALITY),
        *load_cases_from_directory(_SCENARIOS),
    ]
    counted = [c for c in cases if not c.is_skipped]

    assert len({c.id for c in cases}) == len(cases), "用例 ID 重复"
    assert len(counted) >= 100
    for role in ("CUSTOMER", "MERCHANT"):
        for locale in ("zh-CN", "en-US"):
            assert any(c.role == role and c.locale == locale for c in counted), (role, locale)
        for risk in ("SECURITY", "QUALITY"):
            assert any(c.role == role and c.risk == risk for c in counted), (role, risk)
    assert sum(len(c.turns) > 1 for c in counted) >= 10
    assert len({c.skill for c in counted}) >= 15
