"""从真实 FakeAgent 导出 Chat 契约 Fixture。

前端 Adapter 的契约测试消费 `docs/fixtures/chat/*.json`。这些载荷必须来自后端的
真实输出，不能由前端按类型自造——类型只保证字段名，不保证语义组合合法。

产物由 `backend/tests/api/test_chat_fixtures.py` 逐字节把关。
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent.fake_agent import FakeAgent  # noqa: E402
from app.schemas.chat import ChatResponse  # noqa: E402

# ChatResponse.id 来自 uuid4()、created_at 来自 now()。原样导出会让每次运行都产生
# 不同的 JSON，哨兵测试永远为红，最终必然被人加参数绕过——那时它就不再防任何漂移。
# 所以这两个字段在导出时覆盖为确定性值：id 用命名空间 UUID5（同名同值），
# created_at 用固定时间戳。其余字段全部是 FakeAgent 的真实输出。
_FIXTURE_NAMESPACE = uuid5(NAMESPACE_URL, "https://borough.local/fixtures/chat")
_FROZEN_CREATED_AT = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FixtureCase:
    name: str
    message: str
    purpose: str


FIXTURES: tuple[FixtureCase, ...] = (
    FixtureCase(
        name="metric-refund",
        message="最近7天退货量趋势",
        purpose="METRIC 八字段 + visualization + recommendations + FALLBACK 降级",
    ),
    FixtureCase(
        name="metric-gmv",
        message="昨天总 GMV 是多少？",
        purpose="METRIC + TRADE 分类",
    ),
    FixtureCase(
        name="metric-order-detail",
        message="查看最近订单明细",
        purpose="total_rows=327、truncated=true、export 为 null",
    ),
    FixtureCase(
        name="rule-platform",
        message="我要货品上架，具体规则有吗？",
        purpose="RULE 模式下按模式字段全部缺省",
    ),
    FixtureCase(
        name="chat-greeting",
        message="你好",
        purpose="CHAT + [NONE] + degraded=false",
    ),
    FixtureCase(
        name="invalid-refused",
        message="帮我修改订单金额",
        purpose="INVALID 拒绝语义",
    ),
)


def fixtures_dir() -> Path:
    return ROOT / "docs" / "fixtures" / "chat"


async def build_fixture(case: FixtureCase) -> ChatResponse:
    """跑一次真实 FakeAgent，再把非确定性字段冻结。"""

    session_id = uuid5(_FIXTURE_NAMESPACE, f"{case.name}/session")
    result = await FakeAgent().run(case.message, session_id)
    return result.response.model_copy(
        update={
            "id": uuid5(_FIXTURE_NAMESPACE, f"{case.name}/answer"),
            "created_at": _FROZEN_CREATED_AT,
        }
    )


def render_fixture_json(response: ChatResponse) -> str:
    payload = response.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_readme() -> str:
    rows = "\n".join(
        f"| `{case.name}.json` | {case.message} | {case.purpose} |" for case in FIXTURES
    )
    return f"""# Chat 契约 Fixture

> 本目录由 `scripts/export_chat_fixtures.py` 生成，请勿手改。
> 改动后端 `FakeAgent` 输出后必须重新导出，否则
> `backend/tests/api/test_chat_fixtures.py` 会失败。

前端 `src/api/adapters/chat.spec.ts` 直接消费这些文件，用于验证 Adapter 能正确
消化后端**真实产生**的载荷，而不是前端自己按类型造出来的载荷。

`id` 与 `created_at` 在导出时被冻结为确定性值（命名空间 UUID5 + 固定时间戳），
其余字段均为 `FakeAgent` 的真实输出。

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
{rows}
"""


async def main_async() -> None:
    target = fixtures_dir()
    target.mkdir(parents=True, exist_ok=True)
    for case in FIXTURES:
        response = await build_fixture(case)
        (target / f"{case.name}.json").write_text(
            render_fixture_json(response), encoding="utf-8"
        )
    (target / "README.md").write_text(render_readme(), encoding="utf-8")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
