"""v2 列表端点的签名游标（契约 §8.7.4）。

游标是**不透明的版本化签名字符串**，不是可以自己拼的 base64：载荷里只有排序键、
签发/过期时间和一个绑定摘要，标识本身（`merchant_id`、主体摘要、排序键里的业务 ID）
都不以明文出现。解码时用同一个绑定摘要比对——跨主体、跨资源或跨查询形状复用游标
一律 `422 INVALID_CURSOR`，不返回数据。

密钥从 `EXPORT_SIGNING_SECRET` 派生 `cursor:v1` 子密钥，不直接用裸密钥：
同一个泄露的签名不应该同时能伪造导出链接、游标和审批证据。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from app.core.errors import InvalidCursorError
from app.schemas.v2.common import CursorPage

CURSOR_VERSION: Final = 1
CURSOR_PURPOSE: Final = b"cursor:v1"
CURSOR_TTL: Final = timedelta(hours=24)


def derive_subkey(secret: bytes | str, purpose: bytes) -> bytes:
    """按用途派生子密钥；各用途之间互不通用。"""

    material = secret.encode() if isinstance(secret, str) else secret
    return hmac.new(material, purpose, hashlib.sha256).digest()


@dataclass(frozen=True)
class CursorScope:
    """游标的绑定条件：端点、主体、资源类型、筛选条件、语言与每页大小。"""

    endpoint: str
    role: str
    principal_digest: str
    merchant_id: str
    resource: str
    filters: Mapping[str, Any]
    locale: str
    limit: int

    def binding(self) -> str:
        payload = json.dumps(
            {
                "endpoint": self.endpoint,
                "role": self.role,
                "principal": self.principal_digest,
                "merchant": self.merchant_id,
                "resource": self.resource,
                "filters": dict(sorted(self.filters.items())),
                "locale": self.locale,
                "limit": self.limit,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def descending(value: str) -> str:
    """降序字段的游标键：按字符取补，让 `page()` 统一的升序 `>` 比较与业务降序一致。"""

    return "".join(chr(0x10FFFF - ord(char)) for char in value)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class CursorCodec:
    def __init__(self, *, secret: bytes | str) -> None:
        self._key = derive_subkey(secret, CURSOR_PURPOSE)

    def encode(self, scope: CursorScope, *, key: tuple[str, ...], now: datetime) -> str:
        payload = {
            "v": CURSOR_VERSION,
            "b": scope.binding(),
            "k": list(key),
            "iat": now.astimezone(UTC).isoformat(),
            "exp": (now.astimezone(UTC) + CURSOR_TTL).isoformat(),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        encoded = _b64encode(raw)
        return f"{encoded}.{self._sign(encoded)}"

    def decode(self, cursor: str, scope: CursorScope, *, now: datetime) -> tuple[str, ...]:
        """任何不合格的游标都只有一种结局：`InvalidCursorError`，不区分原因。"""

        encoded, separator, signature = cursor.partition(".")
        if not separator or not encoded or not signature:
            raise InvalidCursorError
        if not hmac.compare_digest(signature, self._sign(encoded)):
            raise InvalidCursorError
        try:
            payload = json.loads(_b64decode(encoded))
        except (ValueError, TypeError) as exc:
            raise InvalidCursorError from exc
        if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
            raise InvalidCursorError
        if not hmac.compare_digest(str(payload.get("b", "")), scope.binding()):
            raise InvalidCursorError
        if self._expired(payload.get("exp"), now):
            raise InvalidCursorError
        key = payload.get("k")
        if not isinstance(key, list) or not all(isinstance(item, str) for item in key):
            raise InvalidCursorError
        return tuple(key)

    def _sign(self, encoded: str) -> str:
        return hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()

    def page[T](
        self,
        items: Sequence[T],
        *,
        key: Callable[[T], tuple[str, ...]],
        scope: CursorScope,
        cursor: str | None,
        now: datetime,
    ) -> CursorPage[T]:
        """对**已按同一排序键排好序**的序列做 keyset 分页。

        锚点记录在两页之间被删除不影响翻页：这里按游标携带的排序键继续取，
        不为确认锚点是否还在而追加查询（§8.7.4 第 4 条）。
        """

        remaining = list(items)
        if cursor is not None:
            anchor = self.decode(cursor, scope, now=now)
            remaining = [item for item in remaining if key(item) > anchor]
        window = remaining[: scope.limit]
        has_more = len(remaining) > scope.limit
        next_cursor = (
            self.encode(scope, key=key(window[-1]), now=now) if has_more and window else None
        )
        return CursorPage[T](items=window, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _expired(raw: object, now: datetime) -> bool:
        if not isinstance(raw, str):
            return True
        try:
            expires_at = datetime.fromisoformat(raw)
        except ValueError:
            return True
        return now.astimezone(UTC) > expires_at
