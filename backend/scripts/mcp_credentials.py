"""MCP 只读凭证的签发、撤销与列表（PRD A8；2026-09-21 用户裁定：只经后端命令行，没有 HTTP 路径）。

用法（在 `backend/` 下，`DATABASE_URL` 指向目标库）：

    uv run python -m scripts.mcp_credentials issue --merchant <code> --scopes query_metrics \
        --ttl-hours 24
    uv run python -m scripts.mcp_credentials list [--merchant <merchant_code>]
    uv run python -m scripts.mcp_credentials revoke --id <credential_id>

`issue` 是凭证原值**唯一一次**出现的地方：只打印到标准输出，不写日志、不落库（库里只有指纹）。
线上签发属生产变更，须先取得用户同意。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from app.core.config import get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.mcp.credentials import (
    MCP_SCOPE_WHITELIST,
    InvalidMcpCredentialRequest,
    McpCredentialStore,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp_credentials", description="MCP 只读凭证管理")
    commands = parser.add_subparsers(dest="command", required=True)

    issue = commands.add_parser("issue", help="签发凭证；原值只展示这一次")
    issue.add_argument("--merchant", required=True, help="商家编码（即店铺标识 merchant_code）")
    issue.add_argument(
        "--scopes",
        required=True,
        help=f"逗号分隔的工具名，只能取自：{', '.join(sorted(MCP_SCOPE_WHITELIST))}",
    )
    issue.add_argument("--ttl-hours", required=True, type=int, help="有效期（小时）")
    issue.add_argument("--label", default=None, help="可选备注，便于列表识别用途")

    listing = commands.add_parser("list", help="列出凭证（不含原值与指纹）")
    listing.add_argument("--merchant", default=None, help="只列某个商家编码")

    revoke = commands.add_parser("revoke", help="撤销凭证；下一次请求即返回 401")
    revoke.add_argument("--id", required=True, type=UUID, help="凭证 id（见 list 输出）")
    return parser


def _fail(parser: argparse.ArgumentParser, message: str) -> None:
    parser.exit(2, f"错误：{message}\n")


async def run(argv: Sequence[str], *, database: Database) -> None:
    parser = _parser()
    args = parser.parse_args(list(argv))
    store = McpCredentialStore(database)

    if args.command == "issue":
        merchant_id = await store.resolve_merchant(args.merchant)
        if merchant_id is None:
            _fail(parser, f"商家 {args.merchant} 不存在或未启用")
            return
        scopes = {scope.strip() for scope in args.scopes.split(",") if scope.strip()}
        try:
            issued = await store.issue(
                merchant_id=merchant_id,
                scopes=scopes,
                ttl=timedelta(hours=args.ttl_hours),
                label=args.label,
            )
        except InvalidMcpCredentialRequest as error:
            _fail(parser, str(error))
            return
        print(f"id: {issued.credential_id}")
        print(f"merchant: {args.merchant}")
        print(f"scopes: {','.join(sorted(issued.scopes))}")
        print(f"expires_at: {issued.expires_at.isoformat()}")
        print(f"token: {issued.token}")
        print("该凭证原值只显示这一次，请立即保存到 MCP 客户端配置；库中只保存其指纹。")
        return

    if args.command == "list":
        for item in await store.list(merchant_code=args.merchant):
            state = "REVOKED" if item.revoked_at is not None else "ACTIVE"
            print(
                f"{item.credential_id}  {item.merchant_code}  {state}  "
                f"expires={item.expires_at.isoformat()}  scopes={','.join(item.scopes)}"
                + (f"  label={item.label}" if item.label else "")
            )
        return

    if args.command == "revoke":
        if not await store.revoke(args.id):
            _fail(parser, "凭证不存在或已撤销")
            return
        print(f"已撤销 {args.id}；持有该凭证的客户端下一次请求将返回 401。")


async def _main(argv: Sequence[str]) -> None:
    database = Database(get_settings())
    try:
        await run(argv, database=database)
    finally:
        await database.dispose()


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(_main(sys.argv[1:]))
