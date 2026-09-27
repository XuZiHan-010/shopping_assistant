"""双端认证会话的领域角色和凭证原语。"""

import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from app.localization.locales import SupportedLocale


class SessionRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"


class SessionAlreadyBoundError(RuntimeError):
    """已绑定访客尝试绑定另一演示顾客身份。"""


@dataclass(frozen=True, slots=True)
class SessionContext:
    """经服务端验证后传递的会话主体，不保存明文会话凭证。"""

    session_record_id: UUID
    role: SessionRole
    merchant_id: UUID
    buyer_key: str | None
    shop_slug: str | None
    #: 供签发/绑定响应回显；解析路径不强依赖它，缺省 `None` 不影响鉴权判定。
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        # frozen dataclass 不做运行时类型检查；字符串角色会让下面的 `is` 守卫失效
        object.__setattr__(self, "role", SessionRole(self.role))
        if self.role is SessionRole.MERCHANT and self.buyer_key is not None:
            raise ValueError("商家会话不得携带 buyer_key")

    @property
    def is_bound(self) -> bool:
        """顾客会话是否已绑定服务端顾客身份。"""
        return self.buyer_key is not None


def new_session_token() -> str:
    """生成仅在签发时返回一次的高熵 URL 安全会话凭证。"""
    return secrets.token_urlsafe(32)


def token_fingerprint(token: str) -> str:
    """生成可存储的会话凭证 SHA-256 指纹。"""
    return sha256(token.encode()).hexdigest()


def issuer_fingerprint(demo_token: str) -> str:
    """生成演示商家签发凭证的 SHA-256 指纹。"""
    return sha256(demo_token.encode()).hexdigest()


def principal_digest(context: SessionContext, *, secret: bytes) -> str:
    """为来源状态与幂等域派生同一稳定主体摘要，不存原始顾客标识。"""

    if context.role is SessionRole.MERCHANT:
        principal = "merchant"
    elif context.buyer_key is not None:
        principal = f"buyer:{context.buyer_key}"
    else:
        principal = f"guest:{context.session_record_id}"
    message = f"borough-principal-v1:{context.role.value}:{context.merchant_id}:{principal}"
    return hmac.new(secret, message.encode(), sha256).hexdigest()


def buyer_alias(
    alias_key: bytes,
    merchant_id: UUID,
    buyer_key: str,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> str:
    """返回仅能在当前店铺内稳定识别顾客的脱敏别名。

    先按店铺派生子密钥再对 `buyer_key` 取摘要，跨店铺不可关联。摘要只取 32 位，
    店铺内顾客很多时会碰撞，只能用于展示，不能当作顾客唯一标识。
    """
    merchant_key = hmac.new(alias_key, str(merchant_id).encode(), sha256).digest()
    digest = hmac.new(merchant_key, buyer_key.encode(), sha256).hexdigest()[:8]
    prefix = "Buyer" if locale is SupportedLocale.EN_US else "顾客"
    return f"{prefix} #{digest}"
