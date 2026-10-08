"""记忆存储的已解析主体（N4-1①，PRD A6、R5）。

存储方法不接收调用方传入的 `merchant_id` / `buyer_key`：主体在构造存储时一次性绑定，而主体对象
只能经下面几个可信工厂得到——

- `from_session(ctx)`：路由、工具、Chat 服务，主体来自服务端已验证的会话；
- `from_verified_turn(...)`：记忆 outbox 排空任务，主体来自已落库消息反查到的会话记录，
  且已与会话、对话三方核对一致（`app.jobs.drain_memory_outbox`）；
- `MerchantMemoryOwner.from_maintenance_row(...)`：总结重建任务，主体来自库内陈旧总结行。

直接调用构造函数会抛 `TypeError`。主体是普通只读类而不是 dataclass：`dataclasses.replace()`
会连同信任令牌一起复制字段，从而改写主体（复审 F5）。后两个工厂只允许出现在 `app/jobs/`，
`_TRUSTED` 只允许出现在本模块，均由 `tests/unit/memory/test_owners.py` 的源码扫描守卫。
这是约定级防护：Python 无法在语言层面阻止刻意绕过，守卫的目标是让误用在评审与测试里暴露。
"""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from app.core.session import SessionContext, SessionRole

_TRUSTED = object()


class _ReadOnly:
    __slots__ = ()

    def __setattr__(self, name: str, value: Any) -> NoReturn:
        raise AttributeError("记忆主体只读")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("记忆主体只读")


class CustomerMemoryOwner(_ReadOnly):
    __slots__ = ("_buyer_key", "_merchant_id")
    _merchant_id: UUID
    _buyer_key: str

    def __init__(self, merchant_id: UUID, buyer_key: str, token: object = None) -> None:
        if token is not _TRUSTED:
            raise TypeError("记忆主体只能经可信工厂创建（from_session / from_verified_turn）")
        object.__setattr__(self, "_merchant_id", merchant_id)
        object.__setattr__(self, "_buyer_key", buyer_key)

    @property
    def merchant_id(self) -> UUID:
        return self._merchant_id

    @property
    def buyer_key(self) -> str:
        return self._buyer_key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CustomerMemoryOwner) and (
            (other.merchant_id, other.buyer_key) == (self.merchant_id, self.buyer_key)
        )

    def __hash__(self) -> int:
        return hash((self.merchant_id, self.buyer_key))

    def __repr__(self) -> str:  # 不打印 buyer_key（R5：日志不记身份原值）
        return f"CustomerMemoryOwner(merchant_id={self.merchant_id})"

    @classmethod
    def from_session(cls, ctx: SessionContext) -> CustomerMemoryOwner | None:
        """顾客会话且已绑定服务端顾客身份时返回主体；访客与商家会话返回 None。"""

        if ctx.role is not SessionRole.CUSTOMER or ctx.buyer_key is None:
            return None
        return cls(ctx.merchant_id, ctx.buyer_key, _TRUSTED)

    @classmethod
    def from_verified_turn(cls, *, merchant_id: UUID, buyer_key: str) -> CustomerMemoryOwner:
        """仅供 outbox 排空任务：主体取自已落库回合的会话记录，并已三方核对。"""

        return cls(merchant_id, buyer_key, _TRUSTED)


class MerchantMemoryOwner(_ReadOnly):
    __slots__ = ("_merchant_id",)
    _merchant_id: UUID

    def __init__(self, merchant_id: UUID, token: object = None) -> None:
        if token is not _TRUSTED:
            raise TypeError("记忆主体只能经可信工厂创建（from_session / from_verified_turn）")
        object.__setattr__(self, "_merchant_id", merchant_id)

    @property
    def merchant_id(self) -> UUID:
        return self._merchant_id

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MerchantMemoryOwner) and other.merchant_id == self.merchant_id

    def __hash__(self) -> int:
        return hash(self.merchant_id)

    def __repr__(self) -> str:
        return f"MerchantMemoryOwner(merchant_id={self.merchant_id})"

    @classmethod
    def from_session(cls, ctx: SessionContext) -> MerchantMemoryOwner | None:
        """商家会话时返回主体；顾客会话返回 None。"""

        if ctx.role is not SessionRole.MERCHANT:
            return None
        return cls(ctx.merchant_id, _TRUSTED)

    @classmethod
    def from_verified_turn(cls, *, merchant_id: UUID) -> MerchantMemoryOwner:
        """仅供 outbox 排空任务：主体取自已落库回合的会话记录，并已三方核对。"""

        return cls(merchant_id, _TRUSTED)

    @classmethod
    def from_maintenance_row(cls, merchant_id: UUID) -> MerchantMemoryOwner:
        """仅供总结重建任务：主体取自库内陈旧总结行的 `merchant_id`。"""

        return cls(merchant_id, _TRUSTED)
