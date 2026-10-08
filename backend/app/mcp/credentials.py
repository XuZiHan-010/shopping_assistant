"""MCP 只读凭证：签发、校验、撤销与列表（PRD A8、§12.5；契约 §8.14.3）。

与会话凭证同一安全等级，复用 `new_session_token()` / `token_fingerprint()`：
高熵生成、库里只存指纹、限定商家 / scope / 有效期。

**校验不缓存**：每次 `verify()` 都查库核对 `revoked_at IS NULL` 与有效期——
撤销来自命令行进程，校验发生在 API 进程，「撤销后下一次请求立即失效」只能靠每次查库保证。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update

from app.core.session import new_session_token, token_fingerprint
from app.db.session import Database
from app.models.mcp_credential import McpCredential
from app.models.merchant import Merchant
from app.schemas.v2.memory import McpReadOnlyTool

MCP_SCOPE_WHITELIST: frozenset[str] = frozenset(tool.value for tool in McpReadOnlyTool)
MAX_CREDENTIAL_TTL = timedelta(days=7)
"""演示级短期凭证的上限；正式兼容外部客户端时按 MCP 授权规范实现（A8），不靠延长有效期。"""


class InvalidMcpCredentialRequest(ValueError):
    """签发参数不合规：scope 为空或越出只读白名单、有效期非正或过长、商家不存在。"""


@dataclass(frozen=True)
class McpPrincipal:
    """校验通过的凭证主体；`merchant_id` 只从这里来，不接受请求传入。"""

    credential_id: UUID
    merchant_id: UUID
    scopes: frozenset[str]


@dataclass(frozen=True)
class IssuedMcpCredential:
    """签发结果。`token` 原值只在这里出现一次，此后没有任何途径能再取回。"""

    credential_id: UUID
    token: str
    merchant_id: UUID
    scopes: frozenset[str]
    expires_at: datetime


@dataclass(frozen=True)
class McpCredentialSummary:
    """列表用摘要：不含原值，也不含指纹。"""

    credential_id: UUID
    merchant_code: str
    scopes: tuple[str, ...]
    label: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _validated_scopes(scopes: Iterable[str]) -> frozenset[str]:
    requested = frozenset(scopes)
    if not requested:
        raise InvalidMcpCredentialRequest("scopes 不能为空")
    outside = requested - MCP_SCOPE_WHITELIST
    if outside:
        raise InvalidMcpCredentialRequest(
            f"scopes 只能是 MCP 只读白名单的子集，越界：{', '.join(sorted(outside))}"
        )
    return requested


class McpCredentialStore:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._clock = clock

    async def issue(
        self,
        *,
        merchant_id: UUID,
        scopes: Iterable[str],
        ttl: timedelta,
        label: str | None = None,
    ) -> IssuedMcpCredential:
        validated = _validated_scopes(scopes)
        if ttl <= timedelta(0) or ttl > MAX_CREDENTIAL_TTL:
            raise InvalidMcpCredentialRequest(
                f"有效期必须为正且不超过 {MAX_CREDENTIAL_TTL.days} 天"
            )
        now = self._clock()
        token = new_session_token()
        credential = McpCredential(
            token_fingerprint=token_fingerprint(token),
            merchant_id=merchant_id,
            scopes=sorted(validated),
            label=label,
            created_at=now,
            expires_at=now + ttl,
        )
        async with self._database.session() as session:
            merchant = await session.get(Merchant, merchant_id)
            if merchant is None or merchant.status != "ACTIVE":
                raise InvalidMcpCredentialRequest("商家不存在或未启用")
            session.add(credential)
            await session.commit()
        return IssuedMcpCredential(
            credential_id=credential.id,
            token=token,
            merchant_id=merchant_id,
            scopes=validated,
            expires_at=credential.expires_at,
        )

    async def verify(self, token: str) -> McpPrincipal | None:
        """凭证有效则返回主体；未知、过期、已撤销或商家停用一律 `None`（调用方统一 401）。"""

        now = self._clock()
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(McpCredential.id, McpCredential.merchant_id, McpCredential.scopes)
                    .join(Merchant, Merchant.id == McpCredential.merchant_id)
                    .where(
                        McpCredential.token_fingerprint == token_fingerprint(token),
                        McpCredential.revoked_at.is_(None),
                        McpCredential.expires_at > now,
                        Merchant.status == "ACTIVE",
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        # 白名单收紧后，旧凭证里多出的 scope 自动失效，而不是继续放行。
        scopes = frozenset(str(scope) for scope in row.scopes) & MCP_SCOPE_WHITELIST
        return McpPrincipal(credential_id=row.id, merchant_id=row.merchant_id, scopes=scopes)

    async def revoke(self, credential_id: UUID) -> bool:
        """撤销；目标不存在或已撤销返回 `False`。只写 `revoked_at`，行保留供审计。"""

        async with self._database.session() as session:
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    update(McpCredential)
                    .where(McpCredential.id == credential_id, McpCredential.revoked_at.is_(None))
                    .values(revoked_at=self._clock())
                ),
            )
            await session.commit()
        return bool(result.rowcount)

    async def list(self, *, merchant_code: str | None = None) -> list[McpCredentialSummary]:
        statement = (
            select(McpCredential, Merchant.merchant_code)
            .join(Merchant, Merchant.id == McpCredential.merchant_id)
            .order_by(McpCredential.created_at.desc(), McpCredential.id)
        )
        if merchant_code is not None:
            statement = statement.where(Merchant.merchant_code == merchant_code)
        async with self._database.session() as session:
            rows = (await session.execute(statement)).all()
        return [
            McpCredentialSummary(
                credential_id=credential.id,
                merchant_code=code,
                scopes=tuple(str(scope) for scope in credential.scopes),
                label=credential.label,
                created_at=credential.created_at,
                expires_at=credential.expires_at,
                revoked_at=credential.revoked_at,
            )
            for credential, code in rows
        ]

    async def resolve_merchant(self, merchant_code: str) -> UUID | None:
        async with self._database.session() as session:
            merchant_id: UUID | None = await session.scalar(
                select(Merchant.id).where(
                    Merchant.merchant_code == merchant_code, Merchant.status == "ACTIVE"
                )
            )
        return merchant_id
