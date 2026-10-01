"""Task 2 支撑：把 `EvalCase` 的多轮 turn 打到真实 ASGI 应用或白名单原语上，
并采集断言评估需要的证据（状态码/错误码、按 `request_id` 过滤的审计行、
执行前后的表快照）。

断言只针对**最后一轮**：前面的 turn 是允许产生副作用的前置步骤（例如先正常
绑定一次演示顾客，再在第二轮尝试改绑），快照与审计查询都从「最后一轮开始
执行前」算起，不把前置步骤的合法变化误判为越权副作用。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import MerchantContext
from app.core.session import SessionContext
from app.db.base import Base
from app.db.session import Database
from app.eval.cases import AssertionType, EvalCase, EvalTurn, HttpRequest
from app.eval.graders.assertions import AssertionContext, TableSnapshot, evaluate_all
from app.eval.primitives import PrimitiveContext, run_primitive
from app.models.operations import AuditLog
from app.repositories.audit import AuditRepository
from app.repositories.session import SessionRepository


@dataclass(frozen=True)
class MerchantFixture:
    """一个测试商家的可信身份三件套：用于把 YAML 里的 `actor` 名解析为真实凭证。"""

    merchant_id: UUID
    shop_slug: str
    bearer_token: str


@dataclass(frozen=True)
class CaseRunResult:
    case_id: str
    passed: bool
    failure_detail: str = ""


@dataclass(frozen=True)
class _TurnOutcome:
    status_code: int | None
    code: str | None


@dataclass(frozen=True)
class _ResolvedActor:
    session_token: str | None
    ctx: SessionContext | None
    bearer_token: str | None


def _actor_merchant_key(name: str) -> str:
    for suffix in ("_bearer",):
        name = name.removesuffix(suffix)
    if name in {"merchant_a", "customer_a"}:
        return "a"
    if name in {"merchant_b", "customer_b"}:
        return "b"
    raise KeyError(f"未知 actor：{name}；harness 只认识 merchant_*/customer_*（可选 _bearer 后缀）")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


_STATE_PLACEHOLDER = re.compile(r"\{state:(\w+)\}")


def _resolve_path(path: str, state: Mapping[str, Any]) -> str:
    """把 `request.path` 里的 `{state:key}` 占位符换成前置 PRIMITIVE turn 写入
    `state` 的运行时值——路径参数（如 `answer_id`）在用例文件里不可能预先写死，
    只能在「先造资源、再打端点」两段式用例里才知道。未登记的占位符直接报错，
    不静默留在路径里发出一个必然 404 的请求。
    """

    def _substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in state:
            raise AssertionError(
                f"路径占位符 {{state:{key}}} 没有对应的前置 turn 写入 state[{key!r}]"
            )
        return str(state[key])

    return _STATE_PLACEHOLDER.sub(_substitute, path)


def _resolve_query(query: Mapping[str, str], state: Mapping[str, Any]) -> dict[str, str]:
    """同一套 `{state:key}` 占位符规则，应用到查询参数值（例如伪造游标用例）。

    httpx 的 `params=` 会整体替换 URL 已有的查询串（空字典即清空），所以游标这类
    运行时才知道的值不能像路径那样拼进 `path` 字符串，必须经这里换成真正的查询参数。
    """

    return {key: _resolve_path(value, state) for key, value in query.items()}


class SecurityHarness:
    """安全硬门禁的执行器：真实 PostgreSQL、真实 ASGI 应用、白名单原语。"""

    def __init__(
        self,
        app: FastAPI,
        database: Database,
        *,
        merchants: Mapping[str, MerchantFixture],
    ) -> None:
        self._app = app
        self._database = database
        self._merchants = merchants
        self._audits = AuditRepository(database)

    async def run(self, case: EvalCase) -> CaseRunResult:
        try:
            return await self._run(case)
        except AssertionError as error:
            # 原语内嵌的不变量检查（例如「必须被拒绝」）直接体现为断言失败，
            # 不能被当成未预期异常吞掉——那正是「测试全绿也可能是错」的路数。
            return CaseRunResult(case.id, passed=False, failure_detail=str(error))

    async def _run(self, case: EvalCase) -> CaseRunResult:
        state: dict[str, Any] = {}
        actor_names = {turn.actor for turn in case.turns}
        actors = {name: await self._resolve_actor(name) for name in actor_names}

        *setup_turns, last_turn = case.turns
        for index, turn in enumerate(setup_turns):
            await self._execute_turn(
                turn,
                actors[turn.actor],
                request_id=f"eval-{case.id}-t{index}",
                state=state,
                locale=case.locale,
            )

        side_effect_tables = sorted(
            {a.table for a in case.assertions if a.type is AssertionType.NO_SIDE_EFFECT and a.table}
        )
        before = await self._snapshot_tables(side_effect_tables)

        request_id = f"eval-{case.id}-t{len(setup_turns)}"
        outcome = await self._execute_turn(
            last_turn,
            actors[last_turn.actor],
            request_id=request_id,
            state=state,
            locale=case.locale,
        )

        after = await self._snapshot_tables(side_effect_tables)
        audit_events = await self._audit_events(request_id)

        assertion_ctx = AssertionContext(
            status_code=outcome.status_code,
            code=outcome.code,
            audit_events=audit_events,
            side_effects={
                table: TableSnapshot(before[table], after[table]) for table in side_effect_tables
            },
        )
        result = evaluate_all(case.assertions, assertion_ctx)
        return CaseRunResult(case.id, passed=result.passed, failure_detail=result.detail)

    async def _resolve_actor(self, name: str) -> _ResolvedActor:
        if name == "anonymous":
            # 公开端点探针：不带任何凭证头，用于验证「未认证访问」本身不产生副作用。
            return _ResolvedActor(session_token=None, ctx=None, bearer_token=None)
        fixture = self._merchants[_actor_merchant_key(name)]
        if name.endswith("_bearer"):
            return _ResolvedActor(session_token=None, ctx=None, bearer_token=fixture.bearer_token)
        async with self._database.session() as session:
            repo = SessionRepository(session, default_ttl_seconds=86_400)
            if name.startswith("merchant_"):
                token, ctx = await repo.issue_merchant(
                    MerchantContext(merchant_id=fixture.merchant_id), issuer=fixture.bearer_token
                )
            elif name.startswith("customer_"):
                token, ctx = await repo.issue_customer_guest(
                    merchant_id=fixture.merchant_id, shop_slug=fixture.shop_slug
                )
            else:
                raise KeyError(f"未知 actor：{name}")
            await session.commit()
        return _ResolvedActor(session_token=token, ctx=ctx, bearer_token=None)

    async def _execute_turn(
        self,
        turn: EvalTurn,
        actor: _ResolvedActor,
        *,
        request_id: str,
        state: dict[str, Any],
        locale: str,
    ) -> _TurnOutcome:
        if turn.request is not None:
            return await self._execute_http(
                turn.request, actor, request_id=request_id, state=state, locale=locale
            )
        assert turn.primitive is not None
        if actor.ctx is None:
            raise AssertionError(f"actor {turn.actor!r} 没有已解析的会话身份，不支持原语用例")
        async with self._database.session() as session:
            primitive_ctx = PrimitiveContext(
                session=session,
                audits=self._audits,
                actor_ctx=actor.ctx,
                request_id=request_id,
                args=turn.primitive.args,
                state=state,
            )
            outcome = await run_primitive(turn.primitive.name, primitive_ctx)
            await session.commit()
        return _TurnOutcome(status_code=outcome.status_code, code=outcome.code)

    async def _execute_http(
        self,
        request: HttpRequest,
        actor: _ResolvedActor,
        *,
        request_id: str,
        state: dict[str, Any],
        locale: str,
    ) -> _TurnOutcome:
        headers = {
            key: value for key, value in request.headers.items() if key.lower() != "accept-language"
        }
        headers["Accept-Language"] = locale
        headers["X-Request-Id"] = request_id
        if actor.bearer_token is not None:
            headers["Authorization"] = f"Bearer {actor.bearer_token}"
        elif actor.session_token is not None:
            headers["X-Session-Id"] = actor.session_token
        async with AsyncClient(
            transport=ASGITransport(app=self._app), base_url="http://testserver"
        ) as client:
            response = await client.request(
                request.method,
                _resolve_path(request.path, state),
                headers=headers,
                params=_resolve_query(request.query, state),
                json=request.json_body,
            )
        code: str | None = None
        if response.content and response.headers.get("content-type", "").startswith(
            "application/json"
        ):
            try:
                code = response.json().get("code")
            except ValueError:
                code = None
        return _TurnOutcome(status_code=response.status_code, code=code)

    async def _snapshot_tables(self, tables: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        if not tables:
            return {}
        async with self._database.session() as session:
            snapshot: dict[str, list[dict[str, Any]]] = {}
            for table_name in tables:
                table = Base.metadata.tables[table_name]
                rows = (await session.execute(select(table))).mappings().all()
                jsonable_rows = [
                    {key: _jsonable(value) for key, value in row.items()} for row in rows
                ]
                snapshot[table_name] = sorted(
                    jsonable_rows, key=lambda row: json.dumps(row, sort_keys=True, default=str)
                )
            return snapshot

    async def _audit_events(self, request_id: str) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            rows = (
                (await session.execute(select(AuditLog).where(AuditLog.request_id == request_id)))
                .scalars()
                .all()
            )
            return [
                {
                    "event_type": row.event_type,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                }
                for row in rows
            ]
