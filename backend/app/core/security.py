"""演示 Token 解析与可信商家上下文。"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AuthRequiredError


@dataclass(frozen=True, slots=True)
class MerchantContext:
    """由服务端认证结果生成的可信商家身份。"""

    merchant_id: UUID
    is_admin: bool = False


def resolve_demo_token(token: str, settings: Settings) -> MerchantContext:
    """以常量时间比较解析演示 Token。"""

    for configured_token, merchant_id in settings.demo_merchant_tokens.items():
        if hmac.compare_digest(token, configured_token):
            return MerchantContext(merchant_id=merchant_id)
    raise AuthRequiredError
