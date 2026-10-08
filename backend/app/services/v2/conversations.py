"""双端会话目录（PRD M13 / §12.4，契约 §8.8.2、§8.9.2，N2 模块 D Task 1）。

两端逻辑对称，只在两处不同：对话属于哪一端（`surface`），以及归属主体——顾客按
「本店 + 登录主体」（访客是本次认证会话，已绑定顾客是稳定主体摘要，与来源状态同口径），
商家按本店且 `owner_kind IS NULL`。同店商家看不到顾客对话，反之亦然。

- 列表只含本主体未删除的对话；顾客 `created_at DESC`、商家 `updated_at DESC`，
  tie-breaker 都是 `id DESC`；
- 详情与删除走 `require_owned()`：不存在、别人的、已删除、形状不对的 ID 一律同一种 403；
- 删除是软删除，同事务清掉该对话的来源状态（O2），删除后不能再被续写。

两条 Chat 路由写入消息也经过这里（`record_turn`），保证目录详情拿得到与 Chat 响应逐字段相同的回答。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidCursorError
from app.core.session import SessionContext, principal_digest
from app.llm.client import LlmMessage
from app.localization.locales import SupportedLocale
from app.memory.pipeline import enqueue_turn
from app.models.answer import Answer
from app.models.conversation import Conversation, Message
from app.repositories.audit import AuditRepository
from app.repositories.provenance import ConversationProvenanceRepository
from app.schemas.v2.common import CursorPage, V2ChatResponseBase
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.cursor import CursorCodec, CursorScope, descending
from app.services.v2.orders import sort_timestamp
from app.tools.gates import principal_owner

Surface = Literal["SHOP", "MERCHANT"]

#: 目录只展示对话双方的消息；`SYSTEM` 是内部行，不进入契约的 `user / assistant`。
_VISIBLE_ROLES: Final = ("USER", "ASSISTANT")


def parse_conversation_id(raw: str) -> UUID:
    """形状不对的标识与「不存在」同一结果：换成一个必然查不到的新 ID，走同一条查询。"""

    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


async def record_turn(
    session: AsyncSession,
    conversation: Conversation,
    *,
    message: str,
    response: V2ChatResponseBase,
    started: datetime,
    locale: SupportedLocale,
    client_request_id: str,
    request_digest: str,
    ctx: SessionContext,
    processing_status: str = "SUCCEEDED",
) -> None:
    """写入一轮的两条消息与回答行，并把对话的最近活动时间推到这一轮。

    显式给出时间而不用数据库默认值：同一事务里 `now()` 相同，两条消息会只剩随机的
    `id` 决定先后，详情里就可能出现「先答后问」。

    回答行的 `id` 就是响应里的 `id`：反馈（`feedback.answer_id` 外键指向 `answers`）、
    Chat BI 与质量回路都按它找回答。`surface` 取对话所属的端，v1 接口只读 `surface` 为空的行。
    """

    if conversation.surface is None:
        raise ValueError("v2 回合只能写入 v2 对话")
    answered_at = max(response.created_at, started + timedelta(microseconds=1))
    payload = response.model_dump(mode="json")
    user_message = Message(
        merchant_id=conversation.merchant_id,
        conversation_id=conversation.id,
        role="USER",
        content=message,
        source_locale=locale.value,
        created_at=started,
        session_record_id=ctx.session_record_id,
    )
    session.add_all(
        [
            user_message,
            Message(
                merchant_id=conversation.merchant_id,
                conversation_id=conversation.id,
                role="ASSISTANT",
                content=response.answer,
                source_locale=locale.value,
                created_at=answered_at,
                response_payload=payload,
            ),
        ]
    )
    await session.flush()
    await enqueue_turn(session, message=user_message, ctx=ctx)
    session.add(
        Answer(
            id=UUID(response.id),
            merchant_id=conversation.merchant_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            client_request_id=client_request_id,
            request_digest=request_digest,
            processing_status=processing_status,
            response_payload=payload,
            elapsed_ms=int((answered_at - started).total_seconds() * 1000),
            response_locale=locale.value,
            surface=conversation.surface,
            created_at=answered_at,
        )
    )
    conversation.updated_at = answered_at
    await session.flush()


async def load_history(
    session: AsyncSession, conversation: Conversation, *, max_turns: int
) -> list[LlmMessage]:
    """同一会话最近 `max_turns` 轮的用户与助手文字，按时间正序（D-N4-1，契约 §8.8.3 / §8.9.3）。

    调用方必须先经 `require_owned()` / 本端 `_conversation()` 确认对话归属且未删除；这里再按
    对话的 `merchant_id` 过滤一次，归属查询出错时也不会读到别店的消息（R5）。

    只回放文字：工具结果从不落库，推理内容不跨回合回放（§6.17）。顾客原话的围栏由循环统一加
    （`_initial_messages`），这里不做——同一段文字只在一处决定怎么进提示词。截断落在一轮中间时，
    丢掉开头孤立的助手回答，让模型看到的每轮都是「问 → 答」。
    """

    if max_turns <= 0:
        return []
    rows = (
        await session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.merchant_id == conversation.merchant_id,
                Message.role.in_(_VISIBLE_ROLES),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(max_turns * 2)
        )
    ).all()
    ordered = list(reversed(rows))
    if ordered and ordered[0].role == "ASSISTANT":
        ordered = ordered[1:]
    return [
        LlmMessage(role="user" if row.role == "USER" else "assistant", content=row.content)
        for row in ordered
    ]


@dataclass(frozen=True)
class _Endpoints:
    list: str
    messages: str


_ENDPOINTS: Final[dict[Surface, _Endpoints]] = {
    "SHOP": _Endpoints(list="shop.conversations.list", messages="shop.conversations.messages"),
    "MERCHANT": _Endpoints(
        list="merchant.conversations.list", messages="merchant.conversations.messages"
    ),
}


class ConversationDirectory:
    def __init__(
        self,
        session: AsyncSession,
        *,
        ctx: SessionContext,
        surface: Surface,
        principal_secret: bytes,
        audits: AuditRepository,
        codec: CursorCodec,
        request_id: str,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._surface = surface
        self._secret = principal_secret
        self._audits = audits
        self._codec = codec
        self._request_id = request_id
        if surface == "SHOP":
            kind, owner = principal_owner(ctx, principal_secret=principal_secret)
            self._owner: tuple[str | None, str | None] = (kind, owner)
        else:
            self._owner = (None, None)

    # ---- 列表 ------------------------------------------------------------------

    async def list_page(
        self, *, cursor: str | None, limit: int, locale: SupportedLocale
    ) -> CursorPage[Conversation]:
        owner_kind, owner_id = self._owner
        rows = await self._session.scalars(
            select(Conversation).where(
                Conversation.merchant_id == self._ctx.merchant_id,
                Conversation.surface == self._surface,
                Conversation.deleted_at.is_(None),
                (
                    Conversation.owner_kind.is_(None)
                    if owner_kind is None
                    else Conversation.owner_kind == owner_kind
                ),
                (
                    Conversation.owner_id.is_(None)
                    if owner_id is None
                    else Conversation.owner_id == owner_id
                ),
            )
        )
        # §8.8.2 顾客按创建时间、§8.9.2 商家按最近活动时间，均 `id DESC` 兜底。
        if self._surface == "SHOP":

            def key(row: Conversation) -> tuple[str, ...]:
                return descending(sort_timestamp(row.created_at)), descending(str(row.id))
        else:

            def key(row: Conversation) -> tuple[str, ...]:
                return descending(sort_timestamp(row.updated_at)), descending(str(row.id))

        return await self._page(
            sorted(rows.all(), key=key),
            key=key,
            scope=self._scope(_ENDPOINTS[self._surface].list, "CONVERSATION", locale, limit, {}),
            cursor=cursor,
        )

    # ---- 详情与删除 --------------------------------------------------------------

    async def require(self, conversation_id: str) -> Conversation:
        """一次固定形状的查询；不存在、别人的、已删除对外同一种 403（R5、O1）。"""

        target = parse_conversation_id(conversation_id)

        async def fetch() -> ScopeLookupResult[Conversation]:
            row = await self._session.get(Conversation, target)
            if row is None:
                return ScopeLookupResult(resource=None, target_exists=False)
            return ScopeLookupResult(
                resource=row if self._visible(row) else None, target_exists=True
            )

        return await require_owned(
            fetch,
            ctx=self._ctx,
            audits=self._audits,
            resource_type="conversation",
            resource_id=conversation_id[:128],
            request_id=self._request_id,
        )

    async def messages_page(
        self,
        conversation: Conversation,
        *,
        cursor: str | None,
        limit: int,
        locale: SupportedLocale,
    ) -> CursorPage[Message]:
        rows = await self._session.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.role.in_(_VISIBLE_ROLES),
            )
        )

        def key(row: Message) -> tuple[str, ...]:
            return sort_timestamp(row.created_at), str(row.id)

        return await self._page(
            sorted(rows.all(), key=key),
            key=key,
            scope=self._scope(
                _ENDPOINTS[self._surface].messages,
                "CONVERSATION_MESSAGE",
                locale,
                limit,
                {"conversation_id": str(conversation.id)},
            ),
            cursor=cursor,
        )

    async def delete(self, conversation: Conversation) -> None:
        """软删除并同事务清掉来源状态；提交由路由负责。"""

        conversation.deleted_at = datetime.now(UTC)
        kind, principal = principal_owner(self._ctx, principal_secret=self._secret)
        await ConversationProvenanceRepository(self._session).delete_for_conversation(
            principal_kind=kind,
            principal_id=principal,
            merchant_id=self._ctx.merchant_id,
            conversation_id=str(conversation.id),
        )
        await self._session.flush()

    # ---- 内部 ------------------------------------------------------------------

    def _visible(self, row: Conversation) -> bool:
        return (
            row.merchant_id == self._ctx.merchant_id
            and row.surface == self._surface
            and row.deleted_at is None
            and (row.owner_kind, row.owner_id) == self._owner
        )

    def _scope(
        self,
        endpoint: str,
        resource: str,
        locale: SupportedLocale,
        limit: int,
        filters: dict[str, str],
    ) -> CursorScope:
        """游标绑定端点 + 会话主体摘要 + 店铺 + 资源 + 语言 + 每页大小；消息另绑对话。"""

        return CursorScope(
            endpoint=endpoint,
            role=self._ctx.role.value,
            principal_digest=principal_digest(self._ctx, secret=self._secret),
            merchant_id=str(self._ctx.merchant_id),
            resource=resource,
            filters=filters,
            locale=locale.value,
            limit=limit,
        )

    async def _page[T](
        self,
        items: Sequence[T],
        *,
        key: Callable[[T], tuple[str, ...]],
        scope: CursorScope,
        cursor: str | None,
    ) -> CursorPage[T]:
        """跨主体、跨对话或被篡改的游标：422 INVALID_CURSOR，不返回数据，并写审计（§8.7.4）。"""

        try:
            return self._codec.page(
                items, key=key, scope=scope, cursor=cursor, now=datetime.now(UTC)
            )
        except InvalidCursorError:
            await self._audits.record_event(
                merchant_id=self._ctx.merchant_id,
                event_type="INVALID_CURSOR",
                resource_type=scope.resource.lower(),
                request_id=self._request_id,
                metadata={"endpoint": scope.endpoint},
            )
            raise
