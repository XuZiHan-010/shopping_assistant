"""工具注册、自检与按角色出工具面（§6.9，A3）。

自检在**注册时**执行，而注册发生在进程启动（`build_tool_registry()` 由 `create_app()` 调用）：
错误的工具定义应该让服务起不来，而不是在某个顾客提问时才暴露。
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final, get_type_hints

from pydantic import BaseModel

from app.core.session import SessionRole
from app.llm.client import ToolSchema
from app.tools.types import (
    ConfirmationPreview,
    DraftProposal,
    ToolContext,
    ToolOutput,
    ToolRole,
    ToolSpec,
    WritePolicy,
)

#: 由注册表从 `SessionContext` 注入的可信身份；模型可见的参数里出现即为契约错误。
IDENTITY_FIELDS: Final = frozenset({"merchant_id", "buyer_key"})

_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: 登录角色 → 工具面的穷尽映射。MCP 凭证不经此表，直接用 `surface_for_mcp()`（§6.10）。
_SESSION_SURFACE: Final[Mapping[SessionRole, ToolRole]] = {
    SessionRole.CUSTOMER: ToolRole.CUSTOMER,
    SessionRole.MERCHANT: ToolRole.MERCHANT,
}
if set(_SESSION_SURFACE) != set(SessionRole):  # pragma: no cover - 新增角色时在导入期失败
    raise RuntimeError("SessionRole 与工具面映射不再穷尽，先补 _SESSION_SURFACE")


def tool_role_for(role: SessionRole) -> ToolRole:
    """登录角色对应的工具面；Skill 索引按同一张表取角色，不另建第三种角色枚举。"""

    return _SESSION_SURFACE[role]

#: executor 的返回类型随写策略固定：草稿工具在类型上就拿不到「直接写目标对象」这条路。
_RETURN_TYPE: Final[Mapping[WritePolicy, type]] = {
    WritePolicy.READ_ONLY: ToolOutput,
    WritePolicy.CUSTOMER_DIRECT: ToolOutput,
    WritePolicy.CUSTOMER_CONFIRMATION: ConfirmationPreview,
    WritePolicy.MERCHANT_DRAFT: DraftProposal,
}

#: 顾客写只能落在顾客工具面，商家草稿只能落在商家工具面（PRD SEC6：两类写不得混用）。
_POLICY_ROLES: Final[Mapping[WritePolicy, frozenset[ToolRole]]] = {
    WritePolicy.CUSTOMER_DIRECT: frozenset({ToolRole.CUSTOMER}),
    WritePolicy.CUSTOMER_CONFIRMATION: frozenset({ToolRole.CUSTOMER}),
    WritePolicy.MERCHANT_DRAFT: frozenset({ToolRole.MERCHANT}),
}


#: 顾客 Agent 不得有下单或支付能力（PRD C2「不可以下单或扣款」）。按下划线切词做**前缀**匹配：
#: `submit_order`、`pay_order`、`create_payment`、`checkout` 都拦下，`display_*` 里的 pay 不算。
#: 只读工具不拦（顾客查询自己的订单不是下单能力）。这只是兜底——主防线是这些工具根本
#: 不被写出来；提交订单、支付、取消只走带 `client_request_id` 的界面路由。
_CUSTOMER_FORBIDDEN_TOKEN_PREFIXES: Final = ("order", "pay", "checkout")


class ToolRegistrationError(RuntimeError):
    """工具定义违反 §6.9 契约；在启动期抛出，阻止服务带病运行。"""


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        _self_check(spec)
        if spec.name in self._specs:
            raise ToolRegistrationError(f"工具名称重复：{spec.name}")
        self._specs[spec.name] = spec

    def find(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def get(self, name: str) -> ToolSpec:
        return self._specs[name]

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def surface_for(self, role: SessionRole) -> list[ToolSpec]:
        """会话角色决定可见工具面：顾客看不到商家工具，反之亦然。"""

        tool_role = tool_role_for(role)
        return [spec for spec in self._specs.values() if tool_role in spec.roles]

    def surface_for_mcp(self) -> list[ToolSpec]:
        """MCP 凭证只见商家工具集的只读子集（A8）；注册自检保证它不含写工具。"""

        return [spec for spec in self._specs.values() if ToolRole.MCP_READONLY in spec.roles]

    def schemas_for(self, role: SessionRole) -> list[ToolSchema]:
        return [to_tool_schema(spec) for spec in self.surface_for(role)]


def to_tool_schema(spec: ToolSpec) -> ToolSchema:
    return ToolSchema(
        name=spec.name,
        description=spec.description,
        parameters=spec.args_model.model_json_schema(),
    )


def build_tool_registry(specs: Iterable[ToolSpec] = ()) -> ToolRegistry:
    """生产工具面的唯一装配点，进程启动时调用。

    N2 模块 A 只建内核，尚无业务工具；`n2-trade-closed-loop`（顾客工具）与
    `n2-merchant-drafts-and-inventory`（商家工具）在这里登记各自的工具。
    """

    registry = ToolRegistry()
    for spec in specs:
        registry.register(spec)
    return registry


# --- 自检 ------------------------------------------------------------------------


def _self_check(spec: ToolSpec) -> None:
    if not _NAME_PATTERN.fullmatch(spec.name):
        raise ToolRegistrationError(f"工具名称不合法（须为小写蛇形）：{spec.name!r}")
    if not spec.roles:
        raise ToolRegistrationError(f"{spec.name}：至少声明一个角色")
    if not spec.description.strip():
        raise ToolRegistrationError(f"{spec.name}：description 不得为空")
    _check_args_model(spec)
    _check_policy(spec)
    _check_executor(spec)
    _check_provenance_refs(spec)


def _check_args_model(spec: ToolSpec) -> None:
    model = spec.args_model
    if not (inspect.isclass(model) and issubclass(model, BaseModel)):
        raise ToolRegistrationError(f"{spec.name}：args_model 必须是 Pydantic 模型")
    if model.model_config.get("extra") != "forbid":
        # 默认 extra="ignore" 会静默吞掉模型塞进来的越权字段，闸门就看不到它们了。
        raise ToolRegistrationError(f"{spec.name}：args_model 必须设置 extra='forbid'")
    leaked = _identity_fields_in(model.model_json_schema())
    if leaked:
        raise ToolRegistrationError(
            f"{spec.name}：args_model 不得包含 {', '.join(sorted(leaked))}，"
            "可信身份由注册表从会话注入"
        )


def _identity_fields_in(schema: Any) -> set[str]:
    """递归扫描 JSON Schema（含 `$defs` 与嵌套模型、别名），不只看顶层字段。"""

    found: set[str] = set()
    if isinstance(schema, Mapping):
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            found |= IDENTITY_FIELDS & set(properties)
        for value in schema.values():
            found |= _identity_fields_in(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _identity_fields_in(item)
    return found


def _check_policy(spec: ToolSpec) -> None:
    if spec.parallelizable and spec.write_policy is not WritePolicy.READ_ONLY:
        raise ToolRegistrationError(f"{spec.name}：parallelizable=True 只允许与 READ_ONLY 组合")
    if ToolRole.MCP_READONLY in spec.roles and (
        spec.write_policy is not WritePolicy.READ_ONLY or ToolRole.MERCHANT not in spec.roles
    ):
        raise ToolRegistrationError(f"{spec.name}：MCP_READONLY 只能是商家工具集里的只读工具")
    if (
        ToolRole.CUSTOMER in spec.roles
        and spec.write_policy is not WritePolicy.READ_ONLY
        and any(
            token.startswith(_CUSTOMER_FORBIDDEN_TOKEN_PREFIXES) for token in spec.name.split("_")
        )
    ):
        raise ToolRegistrationError(
            f"{spec.name}：顾客工具面不得出现下单或支付类工具，下单、支付与取消只走界面路由"
        )
    allowed_roles = _POLICY_ROLES.get(spec.write_policy)
    if allowed_roles is not None and not spec.roles <= allowed_roles:
        raise ToolRegistrationError(
            f"{spec.name}：{spec.write_policy.value} 只允许角色 {', '.join(sorted(allowed_roles))}"
        )
    is_draft = spec.write_policy is WritePolicy.MERCHANT_DRAFT
    if is_draft and spec.draft_kind is None:
        raise ToolRegistrationError(f"{spec.name}：MERCHANT_DRAFT 工具必须声明 draft_kind")
    if not is_draft and spec.draft_kind is not None:
        raise ToolRegistrationError(f"{spec.name}：只有 MERCHANT_DRAFT 工具可以声明 draft_kind")


def _check_executor(spec: ToolSpec) -> None:
    executor = spec.executor
    if not inspect.iscoroutinefunction(executor):
        raise ToolRegistrationError(f"{spec.name}：executor 必须是 async 函数")
    try:
        hints = get_type_hints(executor)
    except Exception as exc:
        raise ToolRegistrationError(
            f"{spec.name}：executor 的类型注解无法解析（须显式标注 ToolContext 与 args_model）"
        ) from exc
    params = list(inspect.signature(executor).parameters)
    if len(params) != 2 or hints.get(params[0]) is not ToolContext:
        # §6.9：executor 明确接收 SessionContext（经 ToolContext），不得靠全局变量取身份。
        raise ToolRegistrationError(
            f"{spec.name}：executor 签名须为 (ctx: ToolContext, args: <args_model>)"
        )
    if hints.get(params[1]) is not spec.args_model:
        raise ToolRegistrationError(
            f"{spec.name}：executor 第二个参数的注解必须是 args_model {spec.args_model.__name__}"
        )
    expected = _RETURN_TYPE[spec.write_policy]
    if hints.get("return") is not expected:
        raise ToolRegistrationError(
            f"{spec.name}：{spec.write_policy.value} 工具的 executor 必须返回 {expected.__name__}"
        )


def _check_provenance_refs(spec: ToolSpec) -> None:
    fields = spec.args_model.model_fields
    for ref in spec.provenance_refs:
        if ref.arg not in fields:
            raise ToolRegistrationError(
                f"{spec.name}：provenance_refs 引用了不存在的参数 {ref.arg!r}"
            )
        if not ref.object_type.strip():
            raise ToolRegistrationError(f"{spec.name}：provenance_refs 的 object_type 不得为空")
