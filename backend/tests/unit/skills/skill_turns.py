"""用 Task 6 的接线组装一个带 Skill 的回合：真实闸门 + 真实 `run_loop` + 脚本化 Fake LLM。

LLM 用 `tests/unit/agent/loop/loop_doubles.py` 的 `tool_use_turn` / `end_turn` 脚本，零费用。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.agent.loop.runner import LoopOutcome, LoopRequest, run_loop
from app.llm.client import LlmMessage, LlmTurn
from app.llm.fake import FakeLlmClient
from app.skills.registry import SkillRegistry
from app.skills.tool import skill_tools
from app.tools.gates import ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import ToolRole, ToolSpec
from tests.unit.agent.loop.loop_doubles import LOOP_SPECS, limits
from tests.unit.tools.tool_doubles import (
    PRINCIPAL_SECRET,
    InMemoryProvenance,
    RecordingAudit,
    RecordingDraftSink,
    ctx_for,
    customer_session,
    merchant_session,
)


def skill_gates(
    skills: SkillRegistry,
    extra_tools: Sequence[ToolSpec] = (),
    audit: RecordingAudit | None = None,
) -> ToolGates:
    registry = ToolRegistry()
    for spec in (*LOOP_SPECS, *extra_tools, *skill_tools(skills)):
        registry.register(spec)
    return ToolGates(
        registry,
        provenance=InMemoryProvenance(),
        principal_secret=PRINCIPAL_SECRET,
        audit=audit or RecordingAudit(),
        drafts=RecordingDraftSink(),
    )


async def run_turn_with_skills(
    skills: SkillRegistry,
    script: Sequence[LlmTurn],
    *,
    role: ToolRole = ToolRole.CUSTOMER,
    max_skill_loads: int = 3,
    extra_tools: Sequence[ToolSpec] = (),
    audit: RecordingAudit | None = None,
    user_message: str = "你好",
) -> tuple[LoopOutcome, list[LlmMessage]]:
    """跑一个回合，返回结局与**最后一次**送给模型的完整消息列表。"""

    from app.services.v2 import merchant_chat, shop_chat

    customer = role is ToolRole.CUSTOMER
    session = customer_session() if customer else merchant_session()
    prompt = (shop_chat if customer else merchant_chat).build_system_prompt(skills)
    gates = skill_gates(skills, extra_tools, audit)
    llm = FakeLlmClient(turns=list(script))
    outcome = await run_loop(
        LoopRequest(context=ctx_for(session), system_prompt=prompt, user_message=user_message),
        llm=llm,
        gates=gates,
        tools=gates.registry.schemas_for(session.role),
        limits=limits(max_skill_loads=max_skill_loads),
    )
    return outcome, llm.converse_calls[-1].messages


def registry_from(root: Path, role: ToolRole = ToolRole.CUSTOMER) -> SkillRegistry:
    return SkillRegistry.from_roots({role: root})
