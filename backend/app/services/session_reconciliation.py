"""演示 Token 与已签发商家会话的启动对账（D8⑤，Astra D3）。"""

from __future__ import annotations

from app.core.config import Settings
from app.core.session import issuer_fingerprint
from app.db.session import Database
from app.repositories.session import SessionRepository


async def reconcile_demo_issuers(database: Database, settings: Settings) -> int:
    """撤销由已从 `DEMO_MERCHANT_TOKENS` 移除的演示 Token 换取的商家会话。

    本版不提供公开撤销端点：运维从 Railway Variables 删掉某个演示 Token 并重启后，
    由这里让它此前换出的会话一并失效。只比较指纹，原 Token 不出这个函数、不进日志；
    返回值只是撤销行数，供启动日志记录。同一进程内若将来支持受控配置刷新，也调用这里。
    """

    active = {issuer_fingerprint(token) for token in settings.demo_merchant_tokens}
    async with database.session() as session:
        revoked = await SessionRepository(
            session, default_ttl_seconds=settings.session_ttl_seconds
        ).revoke_unlisted_issuers(active)
        await session.commit()
    return revoked
