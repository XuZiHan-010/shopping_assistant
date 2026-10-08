"""MCP 凭证命令行（N5 A Task 1；2026-09-21 用户裁定：只经后端脚本签发与撤销，原值只展示一次）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.mcp.credentials import McpCredentialStore


def _load_cli() -> ModuleType:
    """按文件路径加载：仓库根与 `backend/` 各有一个顶层包 `scripts`，全量运行时包名会被
    仓库根那个抢先绑定（见 `tests/unit/scripts/test_seed_demo_analytics.py`）。"""

    path = Path(__file__).resolve().parents[3] / "scripts" / "mcp_credentials.py"
    spec = importlib.util.spec_from_file_location("borough_mcp_credentials_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load_cli().run

pytestmark = pytest.mark.integration

MERCHANT_CODE = "borough-analytics-100"  # tests.conftest 的 merchant_one_id 夹具


@pytest.fixture
async def merchant(db_session: AsyncSession, merchant_one_id: UUID) -> UUID:
    await db_session.commit()
    return merchant_one_id


def _token_from(output: str) -> str:
    lines = [line for line in output.splitlines() if line.startswith("token: ")]
    assert len(lines) == 1, output
    return lines[0].removeprefix("token: ").strip()


async def test_plaintext_shown_exactly_once(
    integration_database: Database, merchant: UUID, capsys: pytest.CaptureFixture[str]
) -> None:
    await run(
        ["issue", "--merchant", MERCHANT_CODE, "--scopes", "query_metrics", "--ttl-hours", "24"],
        database=integration_database,
    )
    token = _token_from(capsys.readouterr().out)
    assert await McpCredentialStore(integration_database).verify(token) is not None

    await run(["list", "--merchant", MERCHANT_CODE], database=integration_database)
    listing = capsys.readouterr().out

    assert "query_metrics" in listing
    assert token not in listing


async def test_revoke_via_cli_invalidates_token(
    integration_database: Database, merchant: UUID, capsys: pytest.CaptureFixture[str]
) -> None:
    store = McpCredentialStore(integration_database)
    await run(
        ["issue", "--merchant", MERCHANT_CODE, "--scopes", "query_metrics", "--ttl-hours", "1"],
        database=integration_database,
    )
    out = capsys.readouterr().out
    token = _token_from(out)
    credential_id = next(
        line.removeprefix("id: ").strip() for line in out.splitlines() if line.startswith("id: ")
    )

    await run(["revoke", "--id", credential_id], database=integration_database)

    assert await store.verify(token) is None


@pytest.mark.parametrize("missing", ["--merchant", "--scopes", "--ttl-hours"])
async def test_issue_requires_merchant_scope_and_expiry(
    integration_database: Database, merchant: UUID, missing: str
) -> None:
    args = {"--merchant": MERCHANT_CODE, "--scopes": "query_metrics", "--ttl-hours": "24"}
    argv = ["issue"]
    for flag, value in args.items():
        if flag != missing:
            argv += [flag, value]

    with pytest.raises(SystemExit) as exc:
        await run(argv, database=integration_database)
    assert exc.value.code != 0


async def test_issue_rejects_write_tool_scope(
    integration_database: Database, merchant: UUID
) -> None:
    with pytest.raises(SystemExit) as exc:
        await run(
            ["issue", "--merchant", MERCHANT_CODE, "--scopes", "draft_restock", "--ttl-hours", "1"],
            database=integration_database,
        )
    assert exc.value.code != 0


async def test_issue_rejects_unknown_merchant(
    integration_database: Database, merchant: UUID
) -> None:
    with pytest.raises(SystemExit) as exc:
        await run(
            [
                "issue",
                "--merchant",
                "no-such-shop",
                "--scopes",
                "query_metrics",
                "--ttl-hours",
                "1",
            ],
            database=integration_database,
        )
    assert exc.value.code != 0
