"""四类闸门与工具调用管线（§6.9，A3）。

一次工具调用的完整顺序，**固定且前一道不过不进下一道**：

```text
工具名 → 工具面 → 身份参数 → 参数校验 → 来源闸门 → 选项闸门 → 护栏闸门 → 审批闸门 → executor
└可修正┘ └──── 致命 ────┘   └ 可修正 ┘   └──── 致命 ────┘   └ 可修正 ┘
```

- 工具名不存在是模型的错误，返回 `INVALID_REQUEST` 交还模型；
- 工具面（真实存在但不属于当前角色）、身份参数、来源、选项失败是**致命错误**：
  写安全日志与审计后抛 `FatalToolError`，
  终止整个回合，对所有角色只有中性说明（O5）；
- 参数校验与护栏失败返回 `ToolResult(ok=False)`，模型可以据公开原因码修正；
- 整条管线**零 LLM**：本模块不依赖任何模型客户端。

`admit()` 与 `execute()` 分开，是为了让循环先把一批调用**全部**过完闸门、再执行其中任何一个：
第二个调用撞上致命闸门时，第一个调用的副作用还没有发生。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, NoReturn, Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.core.errors import ErrorCode
from app.core.metrics import OperationalMetrics
from app.core.session import SessionContext, SessionRole, principal_digest
from app.db.session import Database
from app.repositories.audit import AuditRepository
from app.repositories.provenance import ConversationProvenanceRepository
from app.schemas.v2.drafts import INITIAL_DRAFT_VERSION, DraftKind
from app.tools.errors import FatalToolError, GuardrailRejection
from app.tools.registry import IDENTITY_FIELDS, ToolRegistry
from app.tools.types import (
    DISPLAY_STATUS,
    ConfirmationPreview,
    DraftProposal,
    ObjectRef,
    ToolContext,
    ToolDisplay,
    ToolOutcome,
    ToolOutput,
    ToolResult,
    ToolSpec,
    WritePolicy,
    display_tool_name,
)

#: 安全日志：内部闸门名与规则只写这里（O5），不进响应、SSE 或模型上下文。
security_log = logging.getLogger("app.security.tools")

_INVALID_ARGUMENTS_SUMMARY = "工具参数不合法"
_CONFIRMATION_SUMMARY = "需要顾客在界面确认后才会执行"
_UNKNOWN_TOOL_SUMMARY = "没有这个工具，请只使用给出的工具"
#: 直接调用闸门（测试或非循环调用方）时的占位调用 ID；循环总是传模型给出的 ID。
DIRECT_CALL_ID = "direct"


# --- 来源状态端口 ----------------------------------------------------------------


@dataclass(frozen=True)
class ProvenanceScope:
    """来源状态的隔离键：登录主体 + 店铺 + 对话 ID（D8④、O2）。"""

    principal_kind: str
    principal_id: str
    merchant_id: UUID
    conversation_id: str


def principal_owner(session: SessionContext, *, principal_secret: bytes) -> tuple[str, str]:
    """访客用内部会话记录 ID；已绑定顾客与商家用与幂等域同一个主体摘要（不存原始 buyer_key）。

    来源状态与对话归属（`conversations.owner_kind / owner_id`）共用这一套口径。
    """

    if session.role is SessionRole.CUSTOMER and session.buyer_key is None:
        return "GUEST_SESSION", str(session.session_record_id)
    return "BOUND_PRINCIPAL", principal_digest(session, secret=principal_secret)


def provenance_scope(ctx: ToolContext, *, principal_secret: bytes) -> ProvenanceScope:
    kind, principal = principal_owner(ctx.session, principal_secret=principal_secret)
    return ProvenanceScope(kind, principal, ctx.session.merchant_id, ctx.conversation_id)


class ProvenanceStore(Protocol):
    async def has(self, scope: ProvenanceScope, ref: ObjectRef) -> bool: ...

    async def record(self, scope: ProvenanceScope, refs: Sequence[ObjectRef]) -> None: ...


class DatabaseProvenanceStore:
    """每次读写各开一个会话：并行的只读工具不得共享同一个 `AsyncSession`。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def has(self, scope: ProvenanceScope, ref: ObjectRef) -> bool:
        async with self._database.session() as session:
            return await ConversationProvenanceRepository(session).has(
                **_scope_kwargs(scope), object_type=ref.object_type, object_id=ref.object_id
            )

    async def record(self, scope: ProvenanceScope, refs: Sequence[ObjectRef]) -> None:
        if not refs:
            return
        async with self._database.session() as session:
            repo = ConversationProvenanceRepository(session)
            for ref in refs:
                await repo.record(
                    **_scope_kwargs(scope), object_type=ref.object_type, object_id=ref.object_id
                )
            await session.commit()


def _scope_kwargs(scope: ProvenanceScope) -> dict[str, Any]:
    return {
        "principal_kind": scope.principal_kind,
        "principal_id": scope.principal_id,
        "merchant_id": scope.merchant_id,
        "conversation_id": scope.conversation_id,
    }


# --- 审计与草稿端口 ---------------------------------------------------------------


class SecurityAudit(Protocol):
    async def record_tool_block(self, ctx: ToolContext, *, tool_name: str, gate: str) -> None: ...


class AuditRepositorySecurityAudit:
    """致命拦截写入 `audit_logs`；只记内部标识、角色与闸门名，不记参数、buyer_key 或会话凭证。"""

    EVENT_TYPE = "TOOL_CALL_BLOCKED"

    def __init__(self, audits: AuditRepository) -> None:
        self._audits = audits

    async def record_tool_block(self, ctx: ToolContext, *, tool_name: str, gate: str) -> None:
        await self._audits.record_event(
            merchant_id=ctx.session.merchant_id,
            event_type=self.EVENT_TYPE,
            resource_type="tool",
            resource_id=tool_name[:64],
            request_id=ctx.request_id,
            metadata={"gate": gate, "role": ctx.session.role.value},
        )


class DraftSink(Protocol):
    """商家草稿的唯一落点（D9）：返回公开草稿 ID，绝不产生已批准状态。"""

    async def stage(self, ctx: ToolContext, *, kind: DraftKind, proposal: DraftProposal) -> str: ...


# --- 管线 ------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmittedCall:
    """已通过工具面、参数校验、来源、选项与护栏闸门，等待审批闸门与执行。"""

    spec: ToolSpec
    args: BaseModel
    call_id: str


class ToolGates:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        provenance: ProvenanceStore,
        principal_secret: bytes,
        audit: SecurityAudit,
        drafts: DraftSink | None = None,
        observer: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.perf_counter,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        if drafts is None and any(
            spec.write_policy is WritePolicy.MERCHANT_DRAFT for spec in registry.specs()
        ):
            raise ValueError("注册表含 MERCHANT_DRAFT 工具时必须提供 DraftSink")
        self._registry = registry
        self._provenance = provenance
        self._principal_secret = principal_secret
        self._audit = audit
        self._drafts = drafts
        self._observe = observer or (lambda _stage: None)
        self._clock = clock
        self._metrics = metrics

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def scope_for(self, ctx: ToolContext) -> ProvenanceScope:
        return provenance_scope(ctx, principal_secret=self._principal_secret)

    async def invoke(
        self,
        ctx: ToolContext,
        tool_name: str,
        raw_args: str | Mapping[str, Any],
        *,
        call_id: str = DIRECT_CALL_ID,
    ) -> ToolResult:
        admitted = await self.admit(ctx, tool_name, raw_args, call_id=call_id)
        if isinstance(admitted, ToolResult):
            return admitted
        return await self.execute(ctx, admitted)

    async def admit(
        self,
        ctx: ToolContext,
        tool_name: str,
        raw_args: str | Mapping[str, Any],
        *,
        call_id: str = DIRECT_CALL_ID,
    ) -> AdmittedCall | ToolResult:
        """工具面 → 身份参数 → 参数校验 → 来源 → 选项 → 护栏。致命失败直接抛出。

        准入阶段就失败（被拦截或被拒）的调用在这里计一次失败；放行的调用留给 `execute` 计数，
        每次调用只计一次（运维看板的工具错误率，PRD §10.4）。
        """

        try:
            admitted = await self._admit(ctx, tool_name, raw_args, call_id=call_id)
        except FatalToolError:
            self._count(ok=False)
            raise
        if isinstance(admitted, ToolResult):
            self._count(ok=False)
        return admitted

    def _count(self, *, ok: bool) -> None:
        if self._metrics is not None:
            self._metrics.record_tool_call(ok=ok)

    async def _admit(
        self,
        ctx: ToolContext,
        tool_name: str,
        raw_args: str | Mapping[str, Any],
        *,
        call_id: str,
    ) -> AdmittedCall | ToolResult:

        started = self._clock()
        spec = self._registry.find(tool_name)
        if spec is None:
            # 编出一个不存在的工具名是模型的错误，不是越权：交还模型修正，不终止回合。
            # 真实存在、只是不属于当前角色的工具才是安全事件（下一步）。
            security_log.info(
                "tool_call_unknown_name role=%s request_id=%s",
                ctx.session.role.value,
                ctx.request_id,
            )
            return self._rejected(
                display_tool_name(tool_name),
                call_id,
                started,
                ErrorCode.INVALID_REQUEST,
                ToolOutcome.INVALID_ARGUMENTS,
                _UNKNOWN_TOOL_SUMMARY,
            )
        surface = {s.name for s in self._registry.surface_for(ctx.session.role)}
        if spec.name not in surface:
            await self._block(ctx, spec.name, "surface", "工具不在当前角色的工具面")

        parsed = _parse_arguments(raw_args)
        if parsed is not None and IDENTITY_FIELDS & set(parsed):
            await self._block(ctx, spec.name, "identity", "模型参数企图携带可信身份字段")
        args = _validate(spec, parsed)
        if args is None:
            return self._rejected(
                spec.name,
                call_id,
                started,
                ErrorCode.INVALID_REQUEST,
                ToolOutcome.INVALID_ARGUMENTS,
                _INVALID_ARGUMENTS_SUMMARY,
            )

        self._observe("provenance")
        await self._check_provenance(ctx, spec, args)
        self._observe("options")
        await self._check_options(ctx, spec, args)
        self._observe("guardrail")
        if spec.guardrail is not None:
            try:
                await spec.guardrail(ctx, args)
            except GuardrailRejection as rejection:
                return self._guardrail_rejected(spec, call_id, started, rejection)
        return AdmittedCall(spec, args, call_id)

    async def execute(self, ctx: ToolContext, call: AdmittedCall) -> ToolResult:
        """审批闸门按写策略分派；草稿与界面确认在这里被「截住」，不会直接写目标对象。"""

        try:
            result = await self._execute(ctx, call)
        except FatalToolError:
            self._count(ok=False)
            raise
        self._count(ok=result.ok)
        return result

    async def _execute(self, ctx: ToolContext, call: AdmittedCall) -> ToolResult:

        spec, started = call.spec, self._clock()
        execution_ctx = replace(ctx, tool_call_id=call.call_id)
        self._observe("approval")
        self._observe("execute")
        try:
            outcome = await spec.executor(execution_ctx, call.args)
        except FatalToolError as fatal:
            # executor 自己的归属检查（例如订单不属于当前顾客）同样按致命错误处理。
            await self._log_and_audit(ctx, spec.name, fatal.gate, fatal.detail)
            raise
        except GuardrailRejection as rejection:
            return self._guardrail_rejected(spec, call.call_id, started, rejection)

        scope = self.scope_for(ctx)
        if spec.write_policy is WritePolicy.MERCHANT_DRAFT:
            proposal = _expect(spec, outcome, DraftProposal)
            assert self._drafts is not None and spec.draft_kind is not None
            draft_id = await self._drafts.stage(
                execution_ctx, kind=spec.draft_kind, proposal=proposal
            )
            await self._provenance.record(scope, [ObjectRef("DRAFT", draft_id)])
            return ToolResult(
                ok=True,
                # 带上草稿版本：上下文压缩后模型仍需知道自己引用的是哪一版（PRD A5、D9⑦）。
                payload={
                    "draft_id": draft_id,
                    "kind": spec.draft_kind.value,
                    "draft_version": INITIAL_DRAFT_VERSION,
                },
                display=self._display(spec.name, call.call_id, started, ToolOutcome.DRAFT_CREATED),
                reason_code=None,
                outcome=ToolOutcome.DRAFT_CREATED,
                summary=proposal.summary,
            )
        if spec.write_policy is WritePolicy.CUSTOMER_CONFIRMATION:
            preview = _expect(spec, outcome, ConfirmationPreview)
            await self._provenance.record(scope, preview.produced)
            return ToolResult(
                ok=False,  # 写入没有发生：要等顾客在界面上确认（§8.7.9）
                payload=preview.payload,
                display=self._display(
                    spec.name, call.call_id, started, ToolOutcome.AWAITING_CONFIRMATION
                ),
                reason_code=ErrorCode.CONFIRMATION_REQUIRED,
                outcome=ToolOutcome.AWAITING_CONFIRMATION,
                summary=preview.summary or _CONFIRMATION_SUMMARY,
            )
        output = _expect(spec, outcome, ToolOutput)
        await self._provenance.record(scope, output.produced)
        return ToolResult(
            ok=True,
            payload=output.payload,
            display=self._display(
                spec.name, call.call_id, started, ToolOutcome.SUCCEEDED, output.row_count
            ),
            reason_code=None,
            outcome=ToolOutcome.SUCCEEDED,
            summary=output.summary,
            chart_data=output.chart_data,
            grounds_numbers=spec.grounds_numbers,
        )

    # --- 闸门 --------------------------------------------------------------------

    async def _check_provenance(self, ctx: ToolContext, spec: ToolSpec, args: BaseModel) -> None:
        if not spec.provenance_refs:
            return
        scope = self.scope_for(ctx)
        for ref in spec.provenance_refs:
            for value in _values(getattr(args, ref.arg)):
                if not await self._provenance.has(scope, ObjectRef(ref.object_type, value)):
                    await self._block(
                        ctx, spec.name, "provenance", f"{ref.object_type} 未在本对话中由工具返回过"
                    )

    async def _check_options(self, ctx: ToolContext, spec: ToolSpec, args: BaseModel) -> None:
        if spec.option_source is None:
            return
        allowed_by_field = await spec.option_source(ctx)
        for field_name, allowed in allowed_by_field.items():
            if field_name not in type(args).model_fields:
                raise RuntimeError(f"{spec.name}：选项来源引用了不存在的参数 {field_name}")
            if any(value not in allowed for value in _values(getattr(args, field_name))):
                await self._block(ctx, spec.name, "options", f"{field_name} 不在后端给出的选项内")

    # --- 结果构造 ----------------------------------------------------------------

    async def _block(self, ctx: ToolContext, tool_name: str, gate: str, detail: str) -> NoReturn:
        await self._log_and_audit(ctx, tool_name, gate, detail)
        raise FatalToolError(gate=gate, tool_name=tool_name, detail=detail)

    async def _log_and_audit(
        self, ctx: ToolContext, tool_name: str, gate: str, detail: str
    ) -> None:
        security_log.warning(
            "tool_call_blocked gate=%s tool=%s role=%s request_id=%s detail=%s",
            gate,
            tool_name[:64],
            ctx.session.role.value,
            ctx.request_id,
            detail,
        )
        await self._audit.record_tool_block(ctx, tool_name=tool_name, gate=gate)

    def _display(
        self,
        tool_name: str,
        call_id: str,
        started: float,
        outcome: ToolOutcome,
        row_count: int | None = None,
    ) -> ToolDisplay:
        return ToolDisplay(
            tool_name=tool_name,
            call_id=call_id,
            status=DISPLAY_STATUS[outcome],
            duration_ms=max(0, round((self._clock() - started) * 1000)),
            row_count=row_count,
        )

    def _rejected(
        self,
        tool_name: str,
        call_id: str,
        started: float,
        code: ErrorCode,
        outcome: ToolOutcome,
        summary: str,
    ) -> ToolResult:
        return ToolResult(
            ok=False,
            payload=None,
            display=self._display(tool_name, call_id, started, outcome),
            reason_code=code,
            outcome=outcome,
            summary=summary,
        )

    def _guardrail_rejected(
        self, spec: ToolSpec, call_id: str, started: float, rejection: GuardrailRejection
    ) -> ToolResult:
        check = rejection.check
        return ToolResult(
            ok=False,
            payload=None,
            display=self._display(spec.name, call_id, started, ToolOutcome.REJECTED),
            reason_code=ErrorCode.GUARDRAIL_REJECTED,
            outcome=ToolOutcome.REJECTED,
            summary=check.current_limit or check.code,
            guardrail=check,
        )


def _parse_arguments(raw: str | Mapping[str, Any]) -> dict[str, Any] | None:
    """解析失败返回 None：畸形参数交给校验步骤统一转成 INVALID_REQUEST，而不是当成空字典。"""

    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _validate(spec: ToolSpec, parsed: dict[str, Any] | None) -> BaseModel | None:
    if parsed is None:
        return None
    try:
        return spec.args_model.model_validate(parsed)
    except ValidationError:
        return None


def _values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value]
    return [str(value)]


def _expect[T](spec: ToolSpec, outcome: object, expected: type[T]) -> T:
    if not isinstance(outcome, expected):
        # 注册期已按注解自检；运行期再核一次，防止注解与实际返回不符的 executor 绕过审批闸门。
        raise TypeError(
            f"{spec.name}：executor 返回了 {type(outcome).__name__}，应为 {expected.__name__}"
        )
    return outcome
