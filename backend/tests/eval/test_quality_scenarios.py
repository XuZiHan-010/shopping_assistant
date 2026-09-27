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
