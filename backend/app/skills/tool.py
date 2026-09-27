"""`load_skill` 工具定义（PRD A4，N3 阶段 A Task 3、6）。

- 写策略 `READ_ONLY`、可并行：它只从启动时装好的内存表里取一份只读正文；
- 参数只有 `name`，由**护栏**校验：合法取值只来自当前会话角色的 Skill 索引。名字不在索引里
  （拼错、编造、别的角色的 Skill）按 `GuardrailRejection` 交还模型修正，回合继续、不写安全审计——
  与「编造不存在的工具名」同一处理。不用选项闸门：它失败即致命（整轮 403 + 安全审计），
  而 Skill 只读、按角色分表、名字本就公开在提示词里，判成越权换不来安全收益，
  却让用户一轮对话白白失败；
- 返回 `ToolOutput(payload=SkillSpec)`：工具循环据 payload 的**类型**与工具名走受信通道，
  正文不经 A11 围栏（§6.11「Skill 是本系统资产」），见 `app.agent.loop.runner`。

本模块由装配层（`create_app()`）注册进工具注册表；`app.tools` 不 import 这里（§5.6 依赖方向）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.skills.registry import SkillRegistry
from app.skills.spec import LOAD_SKILL_TOOL, SkillLoadError
from app.tools.errors import FatalToolError, GuardrailRejection
from app.tools.registry import tool_role_for
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy

#: 会用到 Skill 的会话角色；MCP 只读凭证不跑工具循环，没有 Skill。
_SKILL_ROLES: Final = frozenset({ToolRole.CUSTOMER, ToolRole.MERCHANT})


class LoadSkillArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


def load_skill_guardrail(
    registry: SkillRegistry,
) -> Callable[[ToolContext, LoadSkillArgs], Awaitable[None]]:
    async def guardrail(ctx: ToolContext, args: LoadSkillArgs) -> None:
        if args.name not in registry.names(tool_role_for(ctx.session.role)):
            raise GuardrailRejection(
                code="SKILL_NOT_IN_INDEX",
                current_limit="只能加载系统提示「可用 Skill」索引里列出的名字",
                remediation="从索引里原样选一个名字重新调用 load_skill，或不加载直接作答",
            )

    return guardrail


def build_load_skill_tool(registry: SkillRegistry) -> ToolSpec | None:
    """索引全空时返回 None：不注册这个工具，两端工具面与提示词都保持 N2 原样。"""

    roles = registry.roles_with_skills() & _SKILL_ROLES
    if not roles:
        return None

    async def load_skill(ctx: ToolContext, args: LoadSkillArgs) -> ToolOutput:
        try:
            spec = registry.load(tool_role_for(ctx.session.role), args.name)
        except SkillLoadError:
            # 护栏已经保证名字在当前角色的索引里；走到这里说明闸门被绕过，按越权处理（纵深防御）。
            raise FatalToolError(
                gate="options", tool_name=LOAD_SKILL_TOOL, detail="Skill 不在当前角色索引内"
            ) from None
        return ToolOutput(payload=spec, summary=f"已加载 Skill {spec.name} v{spec.version}")

    return ToolSpec(
        name=LOAD_SKILL_TOOL,
        roles=roles,
        args_model=LoadSkillArgs,
        write_policy=WritePolicy.READ_ONLY,
        parallelizable=True,
        description=(
            "按名字加载一个 Skill 的完整做法。name 只能取系统提示「可用 Skill」索引里列出的名字；"
            "加载后按其中步骤处理，单回合加载数量有上限。"
        ),
        executor=load_skill,
        guardrail=load_skill_guardrail(registry),
    )


def skill_tools(registry: SkillRegistry) -> tuple[ToolSpec, ...]:
    """装配层用：索引非空时返回 `(load_skill,)`，否则返回空元组。"""

    spec = build_load_skill_tool(registry)
    return () if spec is None else (spec,)


__all__ = [
    "LOAD_SKILL_TOOL",
    "LoadSkillArgs",
    "build_load_skill_tool",
    "load_skill_guardrail",
    "skill_tools",
]
