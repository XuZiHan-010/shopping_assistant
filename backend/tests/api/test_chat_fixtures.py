"""Chat Fixture 漂移哨兵。

前端的 Adapter 契约测试直接消费 `docs/fixtures/chat/*.json`。如果让前端按
`generated.ts` 的类型自造载荷，类型只能保证字段名、保证不了语义——前端可以合法
构造出 `answer_mode="CHAT"` 配 `analysis_sources=["DATABASE"]` 这类后端永远不会
产生的组合，测试照样绿，等于自己批改自己的作业。

所以载荷由后端 B3 问答图导出，并在这里逐字节比对，防止后端改了输出而
前端还在按旧形状写代码。
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.export_chat_fixtures import (  # noqa: E402
    FIXTURES,
    FixtureCase,
    build_fixture,
    fixtures_dir,
    render_fixture_json,
)

pytestmark = pytest.mark.asyncio


async def _payload(case: FixtureCase) -> dict[str, Any]:
    rendered = render_fixture_json(await build_fixture(case))
    return json.loads(rendered)


@pytest.mark.parametrize("case", FIXTURES, ids=lambda case: case.name)
async def test_exported_fixture_matches_the_current_agent(case: FixtureCase) -> None:
    path = fixtures_dir() / f"{case.name}.json"
    stale = (
        f"{case.name} 与当前 B3 问答图输出不一致，"
        "请运行 uv run python ../scripts/export_chat_fixtures.py"
    )

    assert path.exists(), f"缺少 {path.name}，请先运行导出脚本"
    assert path.read_text(encoding="utf-8") == render_fixture_json(await build_fixture(case)), stale


async def test_fixtures_are_deterministic_across_runs() -> None:
    """导出必须可重复，否则哨兵永远为红，最终会被人加参数绕过。"""

    first = [render_fixture_json(await build_fixture(case)) for case in FIXTURES]
    second = [render_fixture_json(await build_fixture(case)) for case in FIXTURES]

    assert first == second


async def test_fixtures_cover_every_p0_answer_mode() -> None:
    modes = {(await _payload(case))["answer_mode"] for case in FIXTURES}

    assert modes == {"METRIC", "DETAIL", "IDENTITY", "RULE", "CHAT", "INVALID"}


async def test_fake_answers_are_never_presented_as_real_data() -> None:
    """AGENTS.md R7：演示结果不得伪装成真实经营数据。

    B4 起 METRIC/DETAIL 走真实的 `query_data` 节点，导出脚本用
    `_StubQueryService` 演示「查询已成功」这一真实存在的分支——这里的
    DATABASE 不是伪装，是这两个模式现在确实会产生的结果。R7 真正要防的是
    反过来的情况：从不查询经营数据的模式（CHAT/RULE/IDENTITY/INVALID）绝不能
    生造出一个 DATABASE 来源，把没做过的事说成做过了。
    """

    for case in FIXTURES:
        payload = await _payload(case)
        sources = payload["analysis_sources"]

        if "DATABASE" in sources:
            assert payload["answer_mode"] in {"METRIC", "DETAIL"}
            assert payload["degraded"] is False
        if "KNOWLEDGE" in sources:
            assert payload["answer_mode"] == "RULE"
            assert "来源：" in payload["answer"]
        if "FALLBACK" in sources:
            assert payload["degraded"] is True
            assert payload["degraded_reason"]
            assert payload["quality_status"] == "DEGRADED"
        for step in payload["thinking_steps"]:
            assert "Doris" not in step["label"]
            assert "数据库" not in step["label"]
