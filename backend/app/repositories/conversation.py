"""会话数据访问，所有业务方法显式要求 merchant_id。"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, exists, func, literal, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidRequestError
from app.localization.locales import SourceLanguage, detect_source_language
from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation, Message

# 会话详情消息游标签名密钥（Task 7，§8.6.3）。这不是 R6 意义上的机密——
# 消息查询本身始终按已认证的可信 `merchant_id` + 已由 `MerchantScopeService`
# 校验过的 `conversation_id` 过滤，伪造或重放游标不可能读到别的商家/会话
# 的任何一行数据；签名只用于把"游标属于哪个会话"这条不变量做成可检测的，
# 使跨会话/跨商家复用产生**稳定错误码**而不是悄悄按错误的时间边界分页。
# 因此固定为进程内常量即可，不走 Settings/环境变量。
_MESSAGE_CURSOR_SECRET = b"borough-conversation-message-cursor-v1"


def _encode_message_cursor(
    *,
    merchant_id: UUID,
    conversation_id: UUID,
    created_at: datetime,
    message_id: UUID,
) -> str:
    payload = {
        "merchant_id": str(merchant_id),
        "conversation_id": str(conversation_id),
        "created_at": created_at.isoformat(),
        "message_id": str(message_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(_MESSAGE_CURSOR_SECRET, raw.encode("utf-8"), sha256).hexdigest()
    token = json.dumps({"p": payload, "s": signature}, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def _decode_message_cursor(
    cursor: str,
    *,
    merchant_id: UUID,
    conversation_id: UUID,
) -> tuple[datetime, UUID]:
    """解出游标携带的分页边界，并校验签名与所属 `merchant_id`/`conversation_id`。

    任何一步失败——base64/JSON 格式错误、签名不匹配、或签名有效但绑定的
    `merchant_id`/`conversation_id` 与本次可信上下文不一致——都统一归为
    `InvalidRequestError`（422 `INVALID_REQUEST`），不区分"格式错"还是
    "跨会话复用"：两者对调用方来说都是"这个游标在这次请求里不适用"，稳定
    错误码不需要再分子类型。
    """

    try:
        token_raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        token = json.loads(token_raw)
        payload = token["p"]
        signature = str(token["s"])
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        expected_signature = hmac.new(
            _MESSAGE_CURSOR_SECRET, raw.encode("utf-8"), sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidRequestError("消息分页游标签名不合法")
        if payload["merchant_id"] != str(merchant_id) or payload["conversation_id"] != str(
            conversation_id
        ):
            raise InvalidRequestError("消息分页游标不属于当前会话")
        created_at = datetime.fromisoformat(payload["created_at"])
        message_id = UUID(payload["message_id"])
    except InvalidRequestError:
        raise
    except Exception as exc:
        raise InvalidRequestError("消息分页游标不合法") from exc
    return created_at, message_id


@dataclass(frozen=True)
class MessagePage:
    """`ConversationRepository.list_messages_page()` 的返回形状。

    `messages` 始终按创建时间正序排列（页内时间正序，见 §8.6.3）；
    `next_cursor` 非空时代表"还有更早一页"，为空代表已经翻到最早一条。

    `boundary_user_message_id` / `boundary_pairing_unresolved` 只在
    `messages[0].role == "ASSISTANT"` 时有意义——消息严格按 USER/ASSISTANT
    交替写入，`message_limit` 为奇数时分页边界必然会把某一轮拆到相邻两页，
    使这条 ASSISTANT 在它自己所在的页里找不到同页的配对 USER 消息。
    `boundary_user_message_id` 携带紧邻它之前那条消息的 id（正常情况下就是
    它的配对 USER 消息），供调用方在装配 `answer_payload` 时当作"跨页续接"
    的起点，而不是把这条 ASSISTANT 的结构化回答整个丢掉。`
    boundary_pairing_unresolved=True` 表示确实尝试过续接但没能确认——消息
    序列不满足预期的严格交替不变量（数据异常，正常写路径下不会出现）——
    调用方必须把这种情况当作真正的降级显式对用户可见，不能悄悄吞掉。
    """

    messages: list[Message]
    next_cursor: str | None
    has_more: bool
    boundary_user_message_id: UUID | None = None
    boundary_pairing_unresolved: bool = False


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, merchant_id: UUID, title: str | None = None) -> Conversation:
        conversation = Conversation(merchant_id=merchant_id, title=title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_or_create_daily_report_conversation(self, merchant_id: UUID) -> Conversation:
        """返回每商家唯一的日报系统会话，不按标题识别系统资源。"""

        existing = await self._session.scalar(
            select(Conversation).where(
                Conversation.merchant_id == merchant_id,
                Conversation.conversation_kind == "DAILY_REPORT",
            )
        )
        if existing is not None:
            return existing

        try:
            # 并发首建时，条件唯一索引才是最终裁决；savepoint 让输家可以继续在
            # 同一请求事务中重读赢家行，而不是把整个 AsyncSession 标记为失败。
            async with self._session.begin_nested():
                created = Conversation(
                    merchant_id=merchant_id,
                    title="每日经营报告",
                    conversation_kind="DAILY_REPORT",
                )
                self._session.add(created)
                await self._session.flush()
        except IntegrityError:
            raced = await self._session.scalar(
                select(Conversation).where(
                    Conversation.merchant_id == merchant_id,
                    Conversation.conversation_kind == "DAILY_REPORT",
                )
            )
            if raced is not None:
                return raced
            raise
        return created

    async def list_for_merchant(
        self,
        merchant_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        result = await self._session.scalars(
            select(Conversation)
            .where(
                Conversation.merchant_id == merchant_id,
                Conversation.conversation_kind == "CHAT",
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def get_for_merchant(
        self,
        conversation_id: UUID,
        merchant_id: UUID,
    ) -> Conversation | None:
        result = await self._session.scalars(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.merchant_id == merchant_id,
            )
        )
        return result.one_or_none()

    async def exists(self, conversation_id: UUID) -> bool:
        return bool(
            await self._session.scalar(select(exists().where(Conversation.id == conversation_id)))
        )

    async def delete_for_merchant(
        self,
        conversation_id: UUID,
        merchant_id: UUID,
    ) -> bool:
        conversation = await self.get_for_merchant(conversation_id, merchant_id)
        if conversation is None:
            return False
        await self._session.delete(conversation)
        await self._session.flush()
        return True

    async def create_message(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        *,
        source_locale: str | None = None,
    ) -> Message:
        """Task 6：`messages.source_locale` 是 NOT NULL 且无 DB 默认值的列
        （Task 3）。`source_locale` 默认按 `detect_source_language(content)`
        自动推断——多数调用点（包括未升级到显式传参的既有调用点，如
        `report_service.py` 的日报消息落库）都不需要关心这一列，行为与
        Task 6 之前完全一致；`ChatService` 等已知源语言的调用点可以显式覆盖，
        避免对已知内容再做一次不必要的推断。
        """

        message = Message(
            merchant_id=merchant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            source_locale=source_locale or str(detect_source_language(content)),
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def has_assistant_message(self, merchant_id: UUID, conversation_id: UUID) -> bool:
        """闸门首轮判定专用（`app.agent.prefilter.decide`）。

        用助手消息而非用户消息作判据：当前轮的用户消息可能已先行落库，用它判断
        会让首轮把自己误判成「已有历史」，闸门形同虚设（design.md D6）。
        """

        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        Message.merchant_id == merchant_id,
                        Message.conversation_id == conversation_id,
                        Message.role == "ASSISTANT",
                    )
                )
            )
        )

    async def touch_conversation(self, merchant_id: UUID, conversation_id: UUID) -> None:
        """推进会话的 updated_at。

        新增消息只写 messages 表，不会触发 conversations 行的 onupdate，
        而 updated_at 是 ConversationSummary 的对外字段，不能长期等于 created_at。
        """

        await self._session.execute(
            update(Conversation)
            .where(
                Conversation.merchant_id == merchant_id,
                Conversation.id == conversation_id,
            )
            .values(updated_at=func.now())
        )

    async def list_messages_for_conversation(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
    ) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(
                Message.merchant_id == merchant_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(result)

    async def list_messages_page(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        *,
        limit: int,
        before: str | None = None,
    ) -> MessagePage:
        """按 `message_before` 游标分页返回会话消息（Task 7，§8.6.3）。

        第一页（`before=None`）取最新 `limit` 条；`before` 非空时先解出并校验
        游标（`_decode_message_cursor()`：签名不合法或不属于 `merchant_id` +
        `conversation_id` 都会抛 `InvalidRequestError`），再取比游标边界更早
        的 `limit` 条。无论哪一页,返回前都会把结果反转成时间正序（`messages`
        字段），只有取数时的排序方向是"倒序 + LIMIT"，这是唯一能用一次索引
        扫描同时拿到"最新 N 条"和"是否还有更早一页"的写法。

        `(created_at, id)` 组合边界（而不是只用 `created_at`）用于兼容同一
        时刻创建的多条消息——`tuple_()` 生成的行值比较在这种并列情形下仍能
        给出稳定、不重复、不漏行的分页顺序。
        """

        conditions = [
            Message.merchant_id == merchant_id,
            Message.conversation_id == conversation_id,
        ]
        if before is not None:
            cursor_created_at, cursor_message_id = _decode_message_cursor(
                before, merchant_id=merchant_id, conversation_id=conversation_id
            )
            conditions.append(
                tuple_(Message.created_at, Message.id)
                < tuple_(literal(cursor_created_at), literal(cursor_message_id))
            )

        rows = list(
            await self._session.scalars(
                select(Message)
                .where(*conditions)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        page.reverse()

        next_cursor: str | None = None
        if has_more and page:
            oldest = page[0]
            next_cursor = _encode_message_cursor(
                merchant_id=merchant_id,
                conversation_id=conversation_id,
                created_at=oldest.created_at,
                message_id=oldest.id,
            )

        boundary_user_message_id: UUID | None = None
        boundary_pairing_unresolved = False
        if page and page[0].role == "ASSISTANT":
            boundary_user_message_id = await self._find_preceding_user_message_id(
                merchant_id, conversation_id, before=page[0]
            )
            boundary_pairing_unresolved = boundary_user_message_id is None

        return MessagePage(
            messages=page,
            next_cursor=next_cursor,
            has_more=has_more,
            boundary_user_message_id=boundary_user_message_id,
            boundary_pairing_unresolved=boundary_pairing_unresolved,
        )

    async def _find_preceding_user_message_id(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        *,
        before: Message,
    ) -> UUID | None:
        """`list_messages_page()` 跨页续接专用：查紧邻 `before`（某页最早一条
        ASSISTANT 消息）之前的那一条消息。只在真的需要时才多发这一次
        `LIMIT 1` 查询，不影响其它调用路径的成本。

        找到且角色是 `USER` 才返回其 id——这是严格交替写入下唯一合法的配对；
        找不到（`before` 已经是整个会话第一条消息）或角色不是 `USER`（写入
        路径出现过异常）都返回 `None`，由调用方通过
        `MessagePage.boundary_pairing_unresolved` 感知并显式对用户可见，
        不能把这种情况和"正常查到了"混为一谈。
        """

        result = await self._session.execute(
            select(Message.id, Message.role)
            .where(
                Message.merchant_id == merchant_id,
                Message.conversation_id == conversation_id,
                tuple_(Message.created_at, Message.id)
                < tuple_(literal(before.created_at), literal(before.id)),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        row = result.first()
        if row is not None and row.role == "USER":
            return cast(UUID, row.id)
        return None

    async def list_succeeded_answers_for_conversation(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
    ) -> list[tuple[Answer, Feedback | None]]:
        result = await self._session.execute(
            select(Answer, Feedback)
            .outerjoin(
                Feedback,
                and_(
                    Feedback.answer_id == Answer.id,
                    Feedback.merchant_id == merchant_id,
                ),
            )
            .where(
                Answer.merchant_id == merchant_id,
                Answer.conversation_id == conversation_id,
                Answer.processing_status == "SUCCEEDED",
            )
            .order_by(Answer.created_at.asc(), Answer.id.asc())
        )
        return list(result.tuples())

    async def get_answer_by_client_request(
        self,
        merchant_id: UUID,
        client_request_id: str,
    ) -> Answer | None:
        result = await self._session.scalar(
            select(Answer).where(
                Answer.merchant_id == merchant_id,
                Answer.client_request_id == client_request_id,
            )
        )
        return result

    async def try_acquire_daily_report_recompute_lock(
        self,
        merchant_id: UUID,
        report_date: date,
    ) -> bool:
        """获取一次事务级日报重算锁，避免并发删除并重建同一幂等行。"""

        lock_key = f"daily-report-recompute:{merchant_id}:{report_date.isoformat()}"
        return bool(
            await self._session.scalar(
                select(func.pg_try_advisory_xact_lock(func.hashtextextended(lock_key, 0)))
            )
        )

    async def get_daily_report_answer_for_update(
        self,
        merchant_id: UUID,
        client_request_id: str,
    ) -> Answer | None:
        return cast(
            Answer | None,
            await self._session.scalar(
                select(Answer)
                .where(
                    Answer.merchant_id == merchant_id,
                    Answer.client_request_id == client_request_id,
                )
                .with_for_update()
            ),
        )

    async def answer_has_feedback(self, answer_id: UUID) -> bool:
        return bool(
            await self._session.scalar(select(exists().where(Feedback.answer_id == answer_id)))
        )

    async def delete_answer(self, answer: Answer) -> None:
        await self._session.delete(answer)
        await self._session.flush()

    async def create_processing_answer(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID | None,
        client_request_id: str,
        request_digest: str,
    ) -> Answer:
        answer = Answer(
            merchant_id=merchant_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            client_request_id=client_request_id,
            request_digest=request_digest,
            processing_status="PROCESSING",
            # `response_locale` 是 NOT NULL 且无 `default=`/`server_default=`
            # 的列（见 `app/models/answer.py` 的字段注释）：这里写入前实际
            # 语言还未知，用 CHECK 约束允许的 `und`（undetermined）占位；
            # `mark_answer_succeeded()` 在回答成功后会用真实探测结果覆盖它。
            response_locale=str(SourceLanguage.UND),
        )
        self._session.add(answer)
        await self._session.flush()
        return answer

    async def mark_answer_succeeded(
        self,
        answer: Answer,
        response_payload: dict[str, Any],
        *,
        elapsed_ms: int | None = None,
        response_locale: str | None = None,
    ) -> None:
        """Task 6：`answers.response_locale` 同样是 NOT NULL 无默认值列
        （Task 3）。`ChatService` 知道本轮实际生成 locale，会显式传入；
        不知道的调用点（如 `report_service.py` 的日报固定中文模板）退回按
        `response_payload["answer"]` 推断，保持既有零参数调用行为不变。
        """

        answer.processing_status = "SUCCEEDED"
        answer.response_payload = response_payload
        answer.error_payload = None
        answer.elapsed_ms = elapsed_ms
        answer.response_locale = response_locale or str(
            detect_source_language(str(response_payload.get("answer", "")))
        )
        await self._session.flush()

    async def mark_answer_failed(
        self,
        answer: Answer,
        *,
        retryable: bool,
        error_payload: dict[str, Any],
    ) -> None:
        answer.processing_status = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
        answer.error_payload = error_payload
        answer.response_payload = None
        await self._session.flush()

    async def reset_answer_processing(self, answer: Answer) -> None:
        answer.processing_status = "PROCESSING"
        answer.error_payload = None
        await self._session.flush()
