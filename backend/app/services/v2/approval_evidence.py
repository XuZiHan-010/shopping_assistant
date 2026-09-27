"""界面操作证据的签发与校验（契约 §8.7.9，落地 §8.13.2 不变量 6）。

「批准只能来自审批界面」不是 UI 约定，而是这里的三条机制：

1. 证据只在 `GET /merchant/drafts/{draft_id}` 的响应里出现，而那条路由不是工具——
   Agent、MCP、SSE 和日志都拿不到它；
2. 证据绑定**签发会话**、商家、草稿、草案版本与目标版本。换一个会话、
   换一个草稿、或者草案内容变了，旧证据立刻失效（D9⑦）；
3. nonce 持久化在数据库里，并与业务写入在**同一事务**内消费（见 `OperationEvidenceRepository`）。

五类失败——缺失、签名错误、过期、绑定不符、已消费——**对外是同一个中性错误**。
原因枚举只进内部审计，令牌原值任何时候都不记录。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, NoReturn, Protocol, cast

from app.core.errors import ConfirmationRequiredError
from app.services.v2.cursor import derive_subkey

security_log = logging.getLogger("app.security.evidence")

EVIDENCE_PURPOSE: Final = "draft-approval:v1"
EVIDENCE_VERSION: Final = 1
#: §8.7.9：有效期不超过 10 分钟。
EVIDENCE_TTL: Final = timedelta(minutes=10)
NONCE_BYTES: Final = 24


class EvidenceRejection(StrEnum):
    """内部审计用的原因枚举；对外一律不可区分。"""

    MISSING = "MISSING"
    MALFORMED = "MALFORMED"
    BAD_SIGNATURE = "BAD_SIGNATURE"
    EXPIRED = "EXPIRED"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    ALREADY_CONSUMED = "ALREADY_CONSUMED"


@dataclass(frozen=True)
class ApprovalBinding:
    """证据绑定的全部内容；任一项不同就是另一份证据。"""

    session_record_id: str
    merchant_id: str
    draft_id: str
    draft_version: int
    target_version: int
    def digest(self) -> str:
        payload = json.dumps(
            {
                "sub": self.session_record_id,
                "merchant": self.merchant_id,
                "draft": self.draft_id,
                "draft_version": self.draft_version,
                "target_version": self.target_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class EvidenceBinding(Protocol):
    def digest(self) -> str: ...


@dataclass(frozen=True)
class CustomerConfirmationBinding:
    """顾客申请令牌只绑定摘要，不把 buyer_key 原值放进签名载荷。"""

    session_record_id: str
    merchant_id: str
    buyer_digest: str
    order_id: str
    after_sale_type: str
    request_digest: str

    def digest(self) -> str:
        payload = json.dumps(
            {
                "sub": self.session_record_id,
                "merchant": self.merchant_id,
                "buyer": self.buyer_digest,
                "order": self.order_id,
                "kind": self.after_sale_type,
                "request": self.request_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class IssuedEvidence:
    token: str
    nonce: str
    expires_at: datetime


@dataclass(frozen=True)
class VerifiedEvidence:
    """校验通过但**尚未消费**：消费必须和业务写入在同一事务里完成。"""

    nonce: str
    expires_at: datetime


class ApprovalEvidenceService:
    def __init__(
        self,
        *,
        secret: bytes | str,
        purpose: str = EVIDENCE_PURPOSE,
        ttl: timedelta = EVIDENCE_TTL,
    ) -> None:
        self._key = derive_subkey(secret, purpose.encode())
        self._purpose = purpose
        self._ttl = ttl

    @property
    def purpose(self) -> str:
        return self._purpose

    def issue(self, binding: EvidenceBinding, *, now: datetime) -> IssuedEvidence:
        nonce = secrets.token_urlsafe(NONCE_BYTES)
        expires_at = now.astimezone(UTC) + self._ttl
        payload = {
            "v": EVIDENCE_VERSION,
            "p": self._purpose,
            "b": binding.digest(),
            "n": nonce,
            "iat": now.astimezone(UTC).isoformat(),
            "exp": expires_at.isoformat(),
        }
        encoded = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        return IssuedEvidence(
            token=f"{encoded}.{self._sign(encoded)}", nonce=nonce, expires_at=expires_at
        )

    def verify(
        self, token: str | None, binding: EvidenceBinding, *, now: datetime
    ) -> VerifiedEvidence:
        """校验证据；任何失败都抛同一个 `ConfirmationRequiredError`。"""

        if not token:
            self._reject(EvidenceRejection.MISSING)
        encoded, separator, signature = token.partition(".")
        if not separator or not encoded or not signature:
            self._reject(EvidenceRejection.MALFORMED)
        if not hmac.compare_digest(signature, self._sign(encoded)):
            self._reject(EvidenceRejection.BAD_SIGNATURE)
        payload = self._payload(encoded)
        if payload.get("v") != EVIDENCE_VERSION or payload.get("p") != self._purpose:
            self._reject(EvidenceRejection.BINDING_MISMATCH)
        if not hmac.compare_digest(str(payload.get("b", "")), binding.digest()):
            self._reject(EvidenceRejection.BINDING_MISMATCH)
        expires_at = _parse_time(payload.get("exp"))
        if expires_at is None or now.astimezone(UTC) > expires_at:
            self._reject(EvidenceRejection.EXPIRED)
        nonce = payload.get("n")
        if not isinstance(nonce, str) or not nonce:
            self._reject(EvidenceRejection.MALFORMED)
        return VerifiedEvidence(nonce=nonce, expires_at=expires_at)

    def reject_consumed(self) -> NoReturn:
        """nonce 消费失败（不存在、已消费或已过期）——与其余四类失败同一个对外结构。"""

        self._reject(EvidenceRejection.ALREADY_CONSUMED)

    def _payload(self, encoded: str) -> dict[str, Any]:
        try:
            payload = json.loads(_b64decode(encoded))
        except (ValueError, TypeError):
            self._reject(EvidenceRejection.MALFORMED)
        if not isinstance(payload, dict):
            self._reject(EvidenceRejection.MALFORMED)
        return cast(dict[str, Any], payload)

    def _sign(self, encoded: str) -> str:
        return hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()

    def _reject(self, reason: EvidenceRejection) -> NoReturn:
        # 只记原因枚举与用途，绝不记令牌原值（§8.7.9）。
        security_log.warning(
            "approval_evidence_rejected purpose=%s reason=%s", self._purpose, reason.value
        )
        raise ConfirmationRequiredError


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _parse_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
