# 记忆沉淀子 agent 与双知识库检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 1:1 复刻参考项目的 `MemoryConsolidationService` 与 `WikiMemoryService` 双库路由——对话结束后异步把本轮问答压缩成商家记忆，并让记忆只在人工知识库未命中时作为 fallback 参与检索。

**Architecture:** 记忆落 `merchant_memories` 新表（按商家按分类各一份，全量覆盖），与 `knowledge_documents` 物理分表构成双库。`KnowledgeRetrieval` 在构造期绑定 `merchant_id`，`load_domain` 先查人工库，命中即返回并标 `maintained`，为空才查该商家记忆并标 `memory-fallback`。沉淀任务经 FastAPI `BackgroundTasks` 在响应发出后运行，**自开数据库 Session 与 LLM 预算**，任何失败只记日志、不影响本轮回复。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 Async、Alembic、Pydantic v2、pytest

**Spec:** [docs/specs/2026-08-20-memory-and-knowledge-base-design.md](../docs/specs/2026-08-20-memory-and-knowledge-base-design.md)

## Global Constraints

- **R1**：面向用户的文案、注释、日志说明用中文；代码标识符用英文。
- **R2**：未经用户明确许可不得执行 `git commit` / `push` / `tag` / `gh pr create` / `gh pr merge`，不得使用 `git reset --hard`、`git clean`。**本计划每个 Task 末尾的 commit 步骤须先取得用户许可**。
- **R3**：单元测试必须 mock LLM。本计划**不包含**任何真实模型调用；真实验收另行申报。
- **R5**：记忆按 `merchant_id` 隔离，商家标识只能来自已验证的 `MerchantContext`，绝不从请求体取。
- **R8**：`yshopping-merchant-ai 4/` 整体只读，仅可 Read/Grep/Glob。
- **R9**：参考项目是需求基准；与我方文档冲突时改我方文档。
- **R10**：本计划产出的文档只写进 `plans/` 与 `docs/specs/`，不得新建 `superpowers/` 目录。
- **提示词契约测试**：改动任何 LLM 提示词，必须同时新增一条从 Pydantic 模型或常量推导期望值的提示词契约测试（范式见 `backend/tests/unit/intent/test_prompts.py`）。
- **记忆库常量**：`MEMORY_MARKER = "本轮自动沉淀"`，`MAX_KNOWLEDGE_CHARS = 24_000`（沿用 `app/knowledge/domains.py` 既有值，与参考项目 `MAX_WIKI_CHARS` 一致）。
- **来源标记字面量**：`"maintained"` 与 `"memory-fallback"`，逐字对应参考项目 `[LLM_WIKI_SOURCE=...]`。
- **前置**：`plans/2026-08-19-codex-remaining-development-tasks.md` 的 **T1（导入知识库）必须先完成**。`knowledge_documents` 为 0 行时，「人工库优先」行为上等同于「永远走记忆 fallback」，Task 4 的优先级断言测不出真实行为。

## 每个 Task 结束必跑的门禁

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

真实库全量跑需 `REQUIRE_INTEGRATION_DB=1`，且**须确认没有其他 agent 在同一测试容器上写数据**（历史上并发访问出现过 `TRUNCATE_ALL_TABLES` 死锁）。

---

## File Structure

| 文件 | 职责 |
| --- | --- |
| `backend/migrations/versions/20260820_0011_create_merchant_memories.py` | 建 `merchant_memories` 表 |
| `backend/app/models/knowledge.py` | 新增 `MerchantMemory` ORM 类（现有两个类不动） |
| `backend/app/repositories/memory.py` | 记忆读写，强制 `merchant_id` 过滤 |
| `backend/app/prompts/memory.py` | 记忆压缩提示词与确定性 fallback 文本 |
| `backend/app/services/memory_service.py` | 压缩、标记注入、失败兜底 |
| `backend/app/services/memory_agent.py` | 后台调度：自开 Session、自开预算、异常吞掉 |
| `backend/app/knowledge/retrieval.py` | 双库硬优先级 + 来源标记（唯一实质性修改） |
| `backend/app/agent/graph.py` | 来源透出到 `analysis_sources` |
| `backend/app/services/chat_service.py` | 回答落库后提交沉淀任务 |
| `backend/app/api/dependencies.py` | 接线 |
| `backend/tests/unit/knowledge/test_dual_library.py` | 双库优先级与来源标记 |
| `backend/tests/unit/services/test_memory_service.py` | 压缩、marker 注入、fallback |
| `backend/tests/integration/repositories/test_memory_repository.py` | 商家隔离与 upsert |
| `backend/tests/unit/services/test_memory_agent.py` | 异步不阻塞、异常不外溢、预算耗尽走 fallback |
| `backend/tests/unit/prompts/test_memory_prompt.py` | 提示词契约 |

---

## Task 1: `merchant_memories` 表与 ORM

**Files:**
- Create: `backend/migrations/versions/20260820_0011_create_merchant_memories.py`
- Modify: `backend/app/models/knowledge.py`（文件末尾追加类）
- Test: `backend/tests/unit/db/test_models.py`（追加用例）

**Interfaces:**
- Consumes: `app.models.base` 的 `Base`、`UuidPrimaryKeyMixin`、`CreatedAtMixin`、`UpdatedAtMixin`
- Produces: `MerchantMemory`，字段 `merchant_id: UUID`、`category: str`、`content: str`、`version: int`、`status: str`；唯一约束 `uq_merchant_memories_merchant_category`

- [x] **Step 1: 写失败测试**

在 `backend/tests/unit/db/test_models.py` 追加：

```python
def test_merchant_memory_isolates_by_merchant_and_category() -> None:
    from app.models.knowledge import MerchantMemory

    table = MerchantMemory.__table__
    assert table.name == "merchant_memories"
    constraint_names = {c.name for c in table.constraints}
    assert "uq_merchant_memories_merchant_category" in constraint_names
    assert table.c.merchant_id.nullable is False
    assert table.c.category.nullable is False
    # 记忆按商家隔离：外键级联删除，商家注销时记忆一并消失
    foreign_keys = {fk.target_fullname for fk in table.c.merchant_id.foreign_keys}
    assert foreign_keys == {"merchants.id"}
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/db/test_models.py::test_merchant_memory_isolates_by_merchant_and_category -v
```

预期：`ImportError: cannot import name 'MerchantMemory'`

- [x] **Step 3: 追加 ORM 类**

在 `backend/app/models/knowledge.py` 末尾追加（顶部 import 补 `ForeignKey`、`UniqueConstraint`、`UUID`、`PG_UUID`）：

```python
class MerchantMemory(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """商家级 AI 记忆。

    与 ``knowledge_documents`` 物理分表构成双知识库：人工知识永远优先，
    本表只在人工库未命中时作为 fallback 参与检索。参考实现把记忆写在
    ``memory/merchants/{商家}/{分类}.md``，用净化文件名加 UUID 摘要防路径穿越；
    数据库中不存在路径穿越，改用 (merchant_id, category) 唯一约束表达
    「每商家每分类各一份、全量覆盖」的同一语义。
    """

    __tablename__ = "merchant_memories"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "category",
            name="uq_merchant_memories_merchant_category",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_merchant_memories_status",
        ),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
```

- [x] **Step 4: 写迁移**

创建 `backend/migrations/versions/20260820_0011_create_merchant_memories.py`：

```python
"""Create merchant-scoped AI memories.

Revision ID: 20260820_0011
Revises: 20260813_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0011"
down_revision: str | Sequence[str] | None = "20260813_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "category", name="uq_merchant_memories_merchant_category"),
        sa.CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_merchant_memories_status"),
    )
    op.create_index(
        "ix_merchant_memories_merchant_status",
        "merchant_memories",
        ["merchant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_memories_merchant_status", table_name="merchant_memories")
    op.drop_table("merchant_memories")
```

- [x] **Step 5: 跑测试与迁移**

```powershell
cd backend
uv run pytest tests/unit/db/test_models.py -v
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

预期：测试 PASS；三条 alembic 命令均无报错（验证迁移可回滚）。

- [x] **Step 6: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/models/knowledge.py backend/migrations/versions/20260820_0011_create_merchant_memories.py backend/tests/unit/db/test_models.py
git commit -m "feat: 新增 merchant_memories 表，与团队知识库物理分表构成双知识库"
```

---

## Task 2: 记忆仓储与商家隔离

**Files:**
- Create: `backend/app/repositories/memory.py`
- Test: `backend/tests/integration/repositories/test_memory_repository.py`

**Interfaces:**
- Consumes: Task 1 的 `MerchantMemory`
- Produces: `MerchantMemoryRepository(session)`，方法
  `async def list_for_merchant(merchant_id: UUID, category: str) -> list[MerchantMemory]`、
  `async def upsert(*, merchant_id: UUID, category: str, content: str) -> MerchantMemory`

- [x] **Step 1: 写失败测试**

创建 `backend/tests/integration/repositories/test_memory_repository.py`：

```python
"""记忆仓储的商家隔离与覆盖写语义。"""

from __future__ import annotations

import pytest

from app.repositories.memory import MerchantMemoryRepository

pytestmark = pytest.mark.integration


async def test_upsert_overwrites_same_merchant_and_category(db_session, merchant) -> None:
    repository = MerchantMemoryRepository(db_session)

    first = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="第一版")
    await db_session.flush()
    second = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="第二版")
    await db_session.flush()

    # 参考实现 Files.writeString 是全量覆盖，不追加
    assert first.id == second.id
    assert second.content == "第二版"
    assert second.version == 2


async def test_list_for_merchant_never_returns_other_merchants(
    db_session, merchant, other_merchant
) -> None:
    repository = MerchantMemoryRepository(db_session)
    await repository.upsert(merchant_id=merchant.id, category="TRADE", content="本商家")
    await repository.upsert(merchant_id=other_merchant.id, category="TRADE", content="他人")
    await db_session.flush()

    rows = await repository.list_for_merchant(merchant.id, "TRADE")

    assert [row.content for row in rows] == ["本商家"]


async def test_archived_memory_is_not_returned(db_session, merchant) -> None:
    repository = MerchantMemoryRepository(db_session)
    memory = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="旧记忆")
    memory.status = "ARCHIVED"
    await db_session.flush()

    assert await repository.list_for_merchant(merchant.id, "TRADE") == []
```

> `db_session` / `merchant` / `other_merchant` fixture 已存在于 `backend/tests/conftest.py` 或 `backend/tests/support/`。执行前先 `grep -rn "def other_merchant" backend/tests/` 确认名称；若不存在，按同目录既有 fixture 的写法补一个，不要改现有 fixture 的语义。

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest tests/integration/repositories/test_memory_repository.py -v
```

预期：`ModuleNotFoundError: No module named 'app.repositories.memory'`

- [x] **Step 3: 实现仓储**

创建 `backend/app/repositories/memory.py`：

```python
"""商家记忆仓储。

与 ``KnowledgeRepository`` 相反，本仓储的每个查询都**必须**按 ``merchant_id``
过滤：团队知识对所有商家一致，记忆是商家私产。参考实现靠
``memory/merchants/{商家}/`` 的目录边界做隔离，我们靠 WHERE 条件，
因此不提供任何不带 ``merchant_id`` 的查询方法。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import MerchantMemory


class MerchantMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_merchant(self, merchant_id: UUID, category: str) -> list[MerchantMemory]:
        statement = (
            select(MerchantMemory)
            .where(
                MerchantMemory.merchant_id == merchant_id,
                MerchantMemory.category == category,
                MerchantMemory.status == "ACTIVE",
            )
            .order_by(MerchantMemory.category)
        )
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def upsert(
        self,
        *,
        merchant_id: UUID,
        category: str,
        content: str,
    ) -> MerchantMemory:
        """按 (商家, 分类) 全量覆盖，对应参考实现的 Files.writeString。"""

        existing = await self._session.scalar(
            select(MerchantMemory).where(
                MerchantMemory.merchant_id == merchant_id,
                MerchantMemory.category == category,
            )
        )
        if existing is None:
            memory = MerchantMemory(
                merchant_id=merchant_id,
                category=category,
                content=content,
                status="ACTIVE",
            )
            self._session.add(memory)
            return memory

        existing.content = content
        existing.status = "ACTIVE"
        existing.version += 1
        return existing
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest tests/integration/repositories/test_memory_repository.py -v
```

预期：3 passed

- [x] **Step 5: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/repositories/memory.py backend/tests/integration/repositories/test_memory_repository.py
git commit -m "feat: 记忆仓储强制 merchant_id 过滤并实现按分类全量覆盖"
```

---

## Task 3: 记忆压缩提示词与 MemoryService

**Files:**
- Create: `backend/app/prompts/memory.py`
- Create: `backend/app/services/memory_service.py`
- Test: `backend/tests/unit/prompts/test_memory_prompt.py`
- Test: `backend/tests/unit/services/test_memory_service.py`

**Interfaces:**
- Consumes: `app.llm.client` 的 `LlmClient` / `LlmBudget` / `LlmResult`；Task 2 的 `MerchantMemoryRepository`
- Produces:
  - `MEMORY_MARKER: str`、`MEMORY_SYSTEM_PROMPT: str`、`build_memory_prompt(...) -> str`、`build_fallback_memory(...) -> str`
  - `MemoryService(llm, repository)`，方法
    `async def consolidate(*, merchant_id: UUID, merchant_display: str, category: str, manual_markdown: str, history: list[dict[str, object]], budget: LlmBudget, use_llm: bool = True) -> str`
    —— `merchant_display` 进提示词（参考实现把商家 ID 写进 prompt，我方改用展示名避免把内部 UUID 喂给模型）；`use_llm=False` 时跳过模型直接写确定性兜底，供 Task 6 在每日预算耗尽时调用

- [x] **Step 1: 写提示词契约的失败测试**

创建 `backend/tests/unit/prompts/test_memory_prompt.py`：

```python
"""记忆压缩提示词的契约测试。

FakeLlmClient 返回预写好的合法内容，因此「提示词有没有告诉模型该输出什么」
在其他测试里完全不可见。本文件是唯一能拦住提示词退化的地方。
"""

from __future__ import annotations

from app.prompts.memory import (
    MEMORY_MARKER,
    MEMORY_SYSTEM_PROMPT,
    build_fallback_memory,
    build_memory_prompt,
)


def test_prompt_carries_all_four_reference_constraints() -> None:
    prompt = build_memory_prompt(
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="## 本轮自动沉淀",
        history=[{"question": "上月成交额", "category": "TRADE"}],
    )

    # 逐条对应参考实现 WikiMemoryService.compressToWiki 提示词里的四条要求
    assert "只沉淀当前商家" in prompt
    assert "不要编造数据库字段" in prompt
    assert "优先保留人工补充" in prompt
    assert "不得引用" in prompt and "其他商家" in prompt


def test_prompt_pins_merchant_and_category() -> None:
    prompt = build_memory_prompt(
        merchant_display="Borough商家100",
        category="REFUND",
        manual_markdown="",
        history=[],
    )

    assert "Borough商家100" in prompt
    assert "REFUND" in prompt


def test_system_prompt_declares_independent_memory_role() -> None:
    assert "记忆" in MEMORY_SYSTEM_PROMPT
    # 参考实现的系统提示词强调这是「独立记忆整理员」，不得改写人工维护知识
    assert "独立" in MEMORY_SYSTEM_PROMPT


def test_fallback_always_carries_marker() -> None:
    fallback = build_fallback_memory(category="TRADE", manual_markdown="正文")

    assert MEMORY_MARKER in fallback
    assert "正文" in fallback


def test_brand_never_leaks_legacy_ip() -> None:
    prompt = build_memory_prompt(
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="",
        history=[],
    )

    assert "yshopping" not in prompt.lower()
    assert "Borough" in prompt
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/prompts/test_memory_prompt.py -v
```

预期：`ModuleNotFoundError: No module named 'app.prompts.memory'`

- [x] **Step 3: 实现提示词模块**

创建 `backend/app/prompts/memory.py`：

```python
"""记忆压缩提示词。

四条约束逐条对应参考实现 ``WikiMemoryService.compressToWiki``。品牌按
AGENTS.md「命名与品牌」改写为 Borough，其余语义 1:1。
"""

from __future__ import annotations

from datetime import datetime

MEMORY_MARKER = "本轮自动沉淀"

MEMORY_SYSTEM_PROMPT = "你是 Borough 商家 AI 助手的独立记忆整理员。"

_PROMPT_TEMPLATE = """请把以下 Borough 商家 AI 助手历史问答压缩成可复用的记忆。
这是独立的历史记忆库，不得修改或假设人工维护的业务知识库。
要求：
1. 只沉淀当前商家、当前业务分类的用户意图、可用表、字段、口径和推荐回复话术。
2. 信息要短、准、可复用，不要编造数据库字段。
3. 如果人工补充内容存在，优先保留人工补充。
4. 不得引用、推测或合并其他商家和其他业务分类的信息。

商家：{merchant_display}
分类：{category}

人工补充：
{manual_markdown}

历史问答：
{history}
"""


def build_memory_prompt(
    *,
    merchant_display: str,
    category: str,
    manual_markdown: str,
    history: list[dict[str, object]],
) -> str:
    return _PROMPT_TEMPLATE.format(
        merchant_display=merchant_display,
        category=category,
        manual_markdown=manual_markdown,
        history=history,
    )


def build_fallback_memory(*, category: str, manual_markdown: str, now: datetime | None = None) -> str:
    """LLM 不可用时的确定性记忆文本，对应参考实现的 fallback 分支。"""

    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"# {category}\n\n"
        f"## {MEMORY_MARKER}\n\n"
        f"{manual_markdown}\n\n"
        f"更新时间：{timestamp}\n"
    )
```

- [x] **Step 4: 跑提示词测试确认通过**

```powershell
cd backend
uv run pytest tests/unit/prompts/test_memory_prompt.py -v
```

预期：5 passed

- [x] **Step 5: 写 MemoryService 的失败测试**

创建 `backend/tests/unit/services/test_memory_service.py`：

```python
"""记忆压缩服务：标记注入、失败兜底、分类隔离。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.llm.client import LlmBudget, LlmResult, LlmUnavailableError
from app.prompts.memory import MEMORY_MARKER
from app.services.memory_service import MemoryService


class _StubLlm:
    def __init__(self, text: str = "压缩后的记忆", *, raises: Exception | None = None) -> None:
        self._text = text
        self._raises = raises
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def complete(self, *, system, user, fallback, budget) -> LlmResult:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return LlmResult(text=self._text, tokens=120, degraded=False)


class _StubRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str]] = []

    async def upsert(self, *, merchant_id, category, content):
        self.saved.append((category, content))
        return None


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=2, max_tokens=8000)


async def test_marker_is_injected_when_model_output_lacks_it() -> None:
    repository = _StubRepository()
    service = MemoryService(_StubLlm("模型没写标记"), repository)

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="补充",
        history=[],
        budget=_budget(),
    )

    # 参考实现：内容不含标记时，前置补上标题与标记
    assert MEMORY_MARKER in content
    assert content.startswith("# TRADE")
    assert repository.saved == [("TRADE", content)]


async def test_model_output_with_marker_is_kept_verbatim() -> None:
    text = f"# TRADE\n\n## {MEMORY_MARKER}\n\n已经带标记"
    service = MemoryService(_StubLlm(text), _StubRepository())

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="",
        history=[],
        budget=_budget(),
    )

    assert content == text


@pytest.mark.parametrize(
    "failure",
    [LlmUnavailableError("no key"), RuntimeError("boom")],
)
async def test_llm_failure_falls_back_to_deterministic_text(failure: Exception) -> None:
    repository = _StubRepository()
    service = MemoryService(_StubLlm(raises=failure), repository)

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="REFUND",
        manual_markdown="人工补充正文",
        history=[],
        budget=_budget(),
    )

    assert MEMORY_MARKER in content
    assert "人工补充正文" in content
    assert "更新时间：" in content
    assert repository.saved[0][0] == "REFUND"


async def test_blank_model_output_falls_back() -> None:
    service = MemoryService(_StubLlm("   "), _StubRepository())

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="补充",
        history=[],
        budget=_budget(),
    )

    assert "补充" in content
    assert MEMORY_MARKER in content
```

- [x] **Step 6: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/services/test_memory_service.py -v
```

预期：`ModuleNotFoundError: No module named 'app.services.memory_service'`

- [x] **Step 7: 实现 MemoryService**

创建 `backend/app/services/memory_service.py`：

```python
"""记忆压缩服务。

对应参考实现 ``WikiMemoryService.compressToWiki``：调用模型压缩历史问答，
模型不可用或输出为空时写确定性 fallback，并在写入前强制保证内容带
``本轮自动沉淀`` 标记——该标记是双库防污染的写侧不变量。
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from app.llm.client import LlmBudget, LlmClient
from app.prompts.memory import (
    MEMORY_MARKER,
    MEMORY_SYSTEM_PROMPT,
    build_fallback_memory,
    build_memory_prompt,
)

logger = logging.getLogger(__name__)


class _MemoryRepositoryLike(Protocol):
    async def upsert(self, *, merchant_id: UUID, category: str, content: str) -> object: ...


class MemoryService:
    def __init__(self, llm: LlmClient, repository: _MemoryRepositoryLike) -> None:
        self._llm = llm
        self._repository = repository

    async def consolidate(
        self,
        *,
        merchant_id: UUID,
        merchant_display: str,
        category: str,
        manual_markdown: str,
        history: list[dict[str, object]],
        budget: LlmBudget,
        use_llm: bool = True,
    ) -> str:
        fallback = build_fallback_memory(category=category, manual_markdown=manual_markdown)
        content = fallback
        if use_llm:
            prompt = build_memory_prompt(
                merchant_display=merchant_display,
                category=category,
                manual_markdown=manual_markdown,
                history=history,
            )
            try:
                result = await self._llm.complete(
                    system=MEMORY_SYSTEM_PROMPT,
                    user=prompt,
                    fallback=fallback,
                    budget=budget,
                )
                if result.text.strip():
                    content = result.text
            except Exception:  # noqa: BLE001 — 记忆沉淀失败不得影响主链路
                logger.warning(
                    "记忆压缩调用模型失败，改写确定性兜底文本",
                    extra={"category": category},
                    exc_info=True,
                )

        content = _ensure_marker(content, category)
        await self._repository.upsert(
            merchant_id=merchant_id,
            category=category,
            content=content,
        )
        return content


def _ensure_marker(content: str, category: str) -> str:
    """写侧不变量：记忆内容必须带标记，否则读侧无法与人工知识区分。"""

    if MEMORY_MARKER in content:
        return content
    return f"# {category}\n\n## {MEMORY_MARKER}\n\n{content}"
```

- [x] **Step 8: 跑测试确认通过**

```powershell
cd backend
uv run pytest tests/unit/services/test_memory_service.py tests/unit/prompts/test_memory_prompt.py -v
```

预期：9 passed

- [x] **Step 9: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/prompts/memory.py backend/app/services/memory_service.py backend/tests/unit/prompts/test_memory_prompt.py backend/tests/unit/services/test_memory_service.py
git commit -m "feat: 记忆压缩服务复刻参考提示词四约束并强制注入沉淀标记"
```

---

## Task 4: 双库硬优先级检索与来源标记

**Files:**
- Modify: `backend/app/knowledge/retrieval.py`
- Test: `backend/tests/unit/knowledge/test_dual_library.py`

**Interfaces:**
- Consumes: Task 2 的 `MerchantMemoryRepository`
- Produces:
  - `KnowledgeSource` StrEnum：`MAINTAINED = "maintained"`、`MEMORY_FALLBACK = "memory-fallback"`、`NONE = "none"`
  - `KnowledgeResult` 新增字段 `source: KnowledgeSource`
  - `KnowledgeRetrieval(repository, *, memories=None, merchant_id=None)`；**`load_index()` 与 `load_domain()` 签名不变**

- [x] **Step 1: 写失败测试**

创建 `backend/tests/unit/knowledge/test_dual_library.py`：

```python
"""双知识库硬优先级。

参考实现 WikiMemoryService.loadRelevantWiki：人工库非空即直接返回，
记忆完全不参与；人工库为空才取该商家记忆做 fallback。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from app.knowledge.retrieval import KnowledgeRetrieval, KnowledgeSource
from app.schemas.chat import QuestionCategory


@dataclass
class _Doc:
    source_path: str
    title: str
    content: str
    is_complete: bool = True


@dataclass
class _Memory:
    category: str
    content: str


class _KnowledgeRepo:
    def __init__(self, documents: list[_Doc]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_Doc]:
        return self._documents


class _MemoryRepo:
    def __init__(self, memories: list[_Memory]) -> None:
        self._memories = memories
        self.queried_merchants: list[UUID] = []

    async def list_for_merchant(self, merchant_id: UUID, category: str) -> list[_Memory]:
        self.queried_merchants.append(merchant_id)
        return [m for m in self._memories if m.category == category]


def _trade_document() -> _Doc:
    return _Doc("业务/交易/业务流程/下单.md", "下单", "交易订单的下单流程说明")


async def test_maintained_hit_excludes_memory_entirely() -> None:
    memory_repo = _MemoryRepo([_Memory("TRADE", "记忆内容不应出现")])
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([_trade_document()]),
        memories=memory_repo,
        merchant_id=uuid4(),
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.MAINTAINED
    assert "记忆内容不应出现" not in result.text
    # 人工库命中时根本不查记忆库
    assert memory_repo.queried_merchants == []


async def test_memory_is_used_only_when_maintained_is_empty() -> None:
    merchant_id = uuid4()
    memory_repo = _MemoryRepo([_Memory("TRADE", "去年双十一问过成交额")])
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]),
        memories=memory_repo,
        merchant_id=merchant_id,
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.MEMORY_FALLBACK
    assert "去年双十一问过成交额" in result.text
    assert result.matched is True
    assert memory_repo.queried_merchants == [merchant_id]


async def test_source_marker_is_rendered_verbatim() -> None:
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([_trade_document()]),
        memories=_MemoryRepo([]),
        merchant_id=uuid4(),
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    # 逐字对应参考实现 render() 的 [LLM_WIKI_SOURCE=...] 头
    assert result.text.startswith("[LLM_WIKI_SOURCE=maintained]")


async def test_both_empty_reports_none() -> None:
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]),
        memories=_MemoryRepo([]),
        merchant_id=uuid4(),
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.NONE
    assert result.matched is False
    assert result.text == ""


async def test_memory_is_skipped_when_not_wired() -> None:
    """未接线记忆库时行为与改造前完全一致，不得报错。"""

    retrieval = KnowledgeRetrieval(_KnowledgeRepo([]))

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.NONE


async def test_index_layer_never_falls_back_to_memory() -> None:
    """索引层对应参考实现 UNKNOWN 分类，只服务拆词，不得混入记忆。"""

    memory_repo = _MemoryRepo([_Memory("UNKNOWN", "记忆")])
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]),
        memories=memory_repo,
        merchant_id=uuid4(),
    )

    result = await retrieval.load_index()

    assert result.source is KnowledgeSource.NONE
    assert memory_repo.queried_merchants == []
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/knowledge/test_dual_library.py -v
```

预期：`ImportError: cannot import name 'KnowledgeSource'`

- [x] **Step 3: 改造 retrieval.py**

在 `backend/app/knowledge/retrieval.py` 中：

顶部新增 import 与枚举：

```python
from enum import StrEnum
from uuid import UUID


class KnowledgeSource(StrEnum):
    """检索命中来源，逐字对应参考实现的 [LLM_WIKI_SOURCE=...] 取值。"""

    MAINTAINED = "maintained"
    MEMORY_FALLBACK = "memory-fallback"
    NONE = "none"
```

`KnowledgeResult` 增加字段，`_EMPTY` 同步：

```python
@dataclass(frozen=True)
class KnowledgeResult:
    text: str
    hits: tuple[KnowledgeHit, ...]
    matched: bool
    has_incomplete: bool
    source: KnowledgeSource = KnowledgeSource.NONE


_EMPTY = KnowledgeResult(
    text="", hits=(), matched=False, has_incomplete=False, source=KnowledgeSource.NONE
)
```

新增记忆仓储协议：

```python
class _MemoryLike(Protocol):
    category: str
    content: str


class _MemoryRepositoryLike(Protocol):
    async def list_for_merchant(
        self, merchant_id: UUID, category: str
    ) -> Sequence[_MemoryLike]: ...
```

构造函数改为构造期绑定商家（与 `MerchantQaGraph(merchant_id=...)` 同一模式）：

```python
class KnowledgeRetrieval:
    def __init__(
        self,
        repository: _RepositoryLike,
        *,
        memories: _MemoryRepositoryLike | None = None,
        merchant_id: UUID | None = None,
    ) -> None:
        self._repository = repository
        self._memories = memories
        self._merchant_id = merchant_id
```

`load_index` 的 return 改为带来源：

```python
        return _render(
            [
                document
                for document in documents
                if any(marker in document.source_path.lower() for marker in INDEX_PATH_MARKERS)
            ],
            KnowledgeSource.MAINTAINED,
        )
```

`load_domain` 末尾替换原来的 `return _render(hits)`：

```python
        # 硬优先级：人工知识库命中即返回，记忆完全不参与。
        # 对应参考实现 WikiMemoryService.loadRelevantWiki 的 maintained 分支。
        if hits:
            return _render(hits, KnowledgeSource.MAINTAINED)
        return await self._load_memory_fallback(category)

    async def _load_memory_fallback(self, category: QuestionCategory) -> KnowledgeResult:
        """人工库未命中时才取该商家记忆，且必须带商家标识。"""

        if self._memories is None or self._merchant_id is None:
            return _EMPTY
        memories = await self._memories.list_for_merchant(self._merchant_id, str(category))
        if not memories:
            return _EMPTY
        return _render_memories(memories, category)
```

`_render` 增加来源参数并渲染来源头：

```python
def _render(documents: list[_DocumentLike], source: KnowledgeSource) -> KnowledgeResult:
    if not documents:
        return _EMPTY

    header = f"[LLM_WIKI_SOURCE={source.value}]\n"
    # ...（原有 chunks/hits 逻辑不变）

    return KnowledgeResult(
        text=(header + "\n".join(chunks))[:MAX_KNOWLEDGE_CHARS],
        hits=tuple(hits),
        matched=True,
        has_incomplete=any(not hit.is_complete for hit in hits),
        source=source,
    )


def _render_memories(
    memories: Sequence[_MemoryLike], category: QuestionCategory
) -> KnowledgeResult:
    header = f"[LLM_WIKI_SOURCE={KnowledgeSource.MEMORY_FALLBACK.value}]\n"
    blocks = [f"## {memory.category}\n{memory.content}\n" for memory in memories]
    hits = tuple(
        KnowledgeHit(
            source_path=f"memory/{category}",
            title=str(category),
            content=memory.content,
            is_complete=True,
        )
        for memory in memories
    )
    return KnowledgeResult(
        text=(header + "\n".join(blocks))[:MAX_KNOWLEDGE_CHARS],
        hits=hits,
        matched=True,
        has_incomplete=False,
        source=KnowledgeSource.MEMORY_FALLBACK,
    )
```

同时删除 `load_domain` 里那条已兑现的注释：

```python
        # 团队知识未命中后的商家记忆回退属于 P1/B8；当前必须显式表明未命中。
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd backend
uv run pytest tests/unit/knowledge/ -v
```

预期：新增 6 条 PASS，**且既有知识检索测试全绿**。若既有测试红了，说明改动破坏了原有路径——不要改测试去迁就实现，回头修实现。

- [x] **Step 5: 接线**

`backend/app/api/dependencies.py:154` 改为：

```python
        retrieval=KnowledgeRetrieval(
            KnowledgeRepository(session),
            memories=MerchantMemoryRepository(session),
            merchant_id=context.merchant_id,
        ),
```

顶部补 import：`from app.repositories.memory import MerchantMemoryRepository`

- [x] **Step 6: 跑全量门禁**

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

- [x] **Step 7: 按用户授权延后统一提交**

```bash
git add backend/app/knowledge/retrieval.py backend/app/api/dependencies.py backend/tests/unit/knowledge/test_dual_library.py
git commit -m "feat: 知识检索改为人工库硬优先、记忆仅作未命中回退并透出来源标记"
```

---

## Task 5: 来源透出到 `analysis_sources`

**Files:**
- Modify: `backend/app/agent/graph.py`
- Test: `backend/tests/unit/agent/test_analysis_sources.py`（若已存在则追加用例）

**Interfaces:**
- Consumes: Task 4 的 `KnowledgeResult.source`
- Produces: 无新符号；`ChatResponse.analysis_sources` 在记忆回退时含 `AnalysisSource.MEMORY`

**背景**：`AnalysisSource.MEMORY` 已存在于 `app/schemas/chat.py:38`，**契约无需改动，无需重跑 codegen**。

- [x] **Step 1: 写失败测试**

```python
async def test_memory_fallback_surfaces_memory_analysis_source() -> None:
    """R7：降级与来源必须对用户可见，不得把记忆包装成团队知识。"""

    # 装配一个人工库为空、记忆库有内容的图，提出 TRADE 类问题
    response = await _run_graph_with_memory_only()

    assert AnalysisSource.MEMORY in response.analysis_sources
    assert AnalysisSource.KNOWLEDGE not in response.analysis_sources


async def test_maintained_hit_reports_knowledge_not_memory() -> None:
    response = await _run_graph_with_maintained_knowledge()

    assert AnalysisSource.KNOWLEDGE in response.analysis_sources
    assert AnalysisSource.MEMORY not in response.analysis_sources
```

> 先 `grep -rn "analysis_sources" backend/tests/unit/agent/` 找到既有的图装配 helper 并复用；不要新建第二套装配方式。

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/agent/ -k "memory" -v
```

预期：FAIL，`AnalysisSource.MEMORY` 不在列表中

- [x] **Step 3: 在 `_retrieve_knowledge_detail` 之后的来源装配处区分两种来源**

在 `graph.py` 中定位 `analysis_sources` 的装配点（`grep -n "analysis_sources" backend/app/agent/graph.py`），把原本无条件写 `AnalysisSource.KNOWLEDGE` 的分支改为按 `detail.source` 分流：

```python
if detail.source is KnowledgeSource.MEMORY_FALLBACK:
    sources.append(AnalysisSource.MEMORY)
elif detail.source is KnowledgeSource.MAINTAINED:
    sources.append(AnalysisSource.KNOWLEDGE)
```

同时把 `_retrieve_knowledge_detail` 里那条「未命中知识资料」的备注改为区分表述：

```python
        if not detail.matched:
            notes.append("未命中与当前问题相关的知识资料")
        elif detail.source is KnowledgeSource.MEMORY_FALLBACK:
            notes.append("团队知识库未命中，本次依据该商家的历史记忆作答")
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd backend
uv run pytest tests/unit/agent/ -v
```

- [x] **Step 5: 跑门禁；按用户授权延后统一提交**

```bash
git add backend/app/agent/graph.py backend/tests/unit/agent/
git commit -m "feat: 记忆回退在 analysis_sources 与质量备注中对用户可见"
```

---

## Task 6: 后台异步沉淀接入

**Files:**
- Create: `backend/app/services/memory_agent.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/unit/services/test_memory_agent.py`

**Interfaces:**
- Consumes: Task 3 的 `MemoryService`；`app.db.session.Database`；`app.core.config.Settings`
- Produces:
  - `build_manual_markdown(*, question: str, category: str, source_tables: list[str], quality_notes: list[str], suggestions: list[str], export_id: str | None, answer: str) -> str`
  - `MemoryAgent(*, background, database, settings, merchant_id: UUID, merchant_display: str, daily_cap_hit: bool)`，方法
    `def submit(*, category: str, question: str, answer: str, source_tables: list[str], quality_notes: list[str], suggestions: list[str], export_id: str | None) -> None`

**字段名对照**：参考实现的人工补充块用 `doris_tables`，我方数据源是 PostgreSQL，字段名改为 `source_tables`，语义（本轮回答依据了哪些数据来源）不变。

**三个必须处理的陷阱：**

1. **请求 Session 不能复用**。`get_db_session` 在请求结束时关闭，后台任务再用它必然报错。任务内部必须 `async with database.session() as session` 自开。
2. **单请求预算不能复用**。本轮 `LlmBudget` 已被问答链路消耗，且请求已结束。沉淀任务自开一个 `LlmBudget(max_calls=1, max_tokens=...)`。
3. **每日预算必须尊重**。`cost_guard.daily_cap_hit` 为真时跳过模型调用，直接写确定性 fallback（`use_llm=False`）。

- [x] **Step 1: 写失败测试**

创建 `backend/tests/unit/services/test_memory_agent.py`：

```python
"""后台记忆沉淀：不阻塞、不外溢、尊重每日预算。"""

from __future__ import annotations

from uuid import uuid4

from app.services.memory_agent import MemoryAgent, build_manual_markdown


class _RecordingBackground:
    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.tasks.append((func, args, kwargs))

    async def run_all(self) -> None:
        for func, args, kwargs in self.tasks:
            await func(*args, **kwargs)


def test_manual_markdown_carries_all_reference_fields() -> None:
    markdown = build_manual_markdown(
        question="上月成交额",
        category="TRADE",
        source_tables=["orders"],
        quality_notes=["无"],
        suggestions=["看看退款"],
        export_id="exp-1",
        answer="上月成交额为 X",
    )

    # 逐条对应参考实现 MemoryConsolidationService.buildManualMarkdown
    for field in ("question", "category", "source_tables", "quality_notes",
                  "suggested_questions", "csv_export"):
        assert field in markdown
    assert markdown.lstrip().startswith("## 本轮自动沉淀")
    assert "上月成交额为 X" in markdown


def test_submit_does_not_run_inline() -> None:
    background = _RecordingBackground()
    agent = MemoryAgent(
        background=background,
        database=None,
        settings=None,
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        daily_cap_hit=False,
    )

    agent.submit(
        category="TRADE",
        question="上月成交额",
        answer="X",
        source_tables=[],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )

    # 提交只登记任务，绝不在本轮请求内执行
    assert len(background.tasks) == 1


def test_submit_is_skipped_for_unknown_category() -> None:
    """参考实现按 question_category_name 过滤；无分类的轮次不沉淀。"""

    background = _RecordingBackground()
    agent = MemoryAgent(
        background=background,
        database=None,
        settings=None,
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        daily_cap_hit=False,
    )

    agent.submit(
        category="UNKNOWN",
        question="你好",
        answer="你好",
        source_tables=[],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )

    assert background.tasks == []


async def test_task_failure_never_escapes() -> None:
    """参考实现 catch(Exception) 后只 log.warn，主链路不受影响。"""

    background = _RecordingBackground()

    class _ExplodingDatabase:
        def session(self):
            raise RuntimeError("数据库炸了")

    agent = MemoryAgent(
        background=background,
        database=_ExplodingDatabase(),
        settings=None,
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        daily_cap_hit=False,
    )
    agent.submit(
        category="TRADE",
        question="上月成交额",
        answer="X",
        source_tables=[],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )

    await background.run_all()  # 不得抛出
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd backend
uv run pytest tests/unit/services/test_memory_agent.py -v
```

预期：`ModuleNotFoundError: No module named 'app.services.memory_agent'`

- [x] **Step 3: 实现 MemoryAgent**

创建 `backend/app/services/memory_agent.py`：

```python
"""后台记忆沉淀调度。

对应参考实现 ``MemoryConsolidationService``：回答落库后提交任务，本轮请求
立即返回。三处与参考实现不同但必须做对的地方——任务自开数据库 Session
（请求级 Session 已随响应关闭）、自开单次 LLM 预算（本轮预算已耗尽且请求已结束）、
每日预算耗尽时跳过模型直接写确定性兜底。
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from app.llm.client import LlmBudget
from app.prompts.memory import MEMORY_MARKER

logger = logging.getLogger(__name__)

_MEMORY_TASK_MAX_TOKENS = 4_000
_SKIPPED_CATEGORIES = frozenset({"UNKNOWN", ""})

_MANUAL_TEMPLATE = """## {marker}

- question: {question}
- category: {category}
- source_tables: {source_tables}
- quality_notes: {quality_notes}
- suggested_questions: {suggestions}
- csv_export: {export_id}

### answer
{answer}
"""


def build_manual_markdown(
    *,
    question: str,
    category: str,
    source_tables: list[str],
    quality_notes: list[str],
    suggestions: list[str],
    export_id: str | None,
    answer: str,
) -> str:
    """六字段加正文，逐条对应参考实现 buildManualMarkdown。"""

    return _MANUAL_TEMPLATE.format(
        marker=MEMORY_MARKER,
        question=question,
        category=category,
        source_tables=source_tables,
        quality_notes=quality_notes,
        suggestions=suggestions,
        export_id=export_id or "",
        answer=answer,
    )


class _BackgroundLike(Protocol):
    def add_task(self, func, *args, **kwargs) -> None: ...


class MemoryAgent:
    def __init__(
        self,
        *,
        background: _BackgroundLike,
        database,
        settings,
        merchant_id: UUID,
        merchant_display: str,
        daily_cap_hit: bool,
    ) -> None:
        self._background = background
        self._database = database
        self._settings = settings
        self._merchant_id = merchant_id
        self._merchant_display = merchant_display
        self._daily_cap_hit = daily_cap_hit

    def submit(
        self,
        *,
        category: str,
        question: str,
        answer: str,
        source_tables: list[str],
        quality_notes: list[str],
        suggestions: list[str],
        export_id: str | None,
    ) -> None:
        if category in _SKIPPED_CATEGORIES:
            return
        manual = build_manual_markdown(
            question=question,
            category=category,
            source_tables=source_tables,
            quality_notes=quality_notes,
            suggestions=suggestions,
            export_id=export_id,
            answer=answer,
        )
        self._background.add_task(self._consolidate, category, manual)

    async def _consolidate(self, category: str, manual: str) -> None:
        try:
            from app.llm.deepseek import DeepSeekLlmClient
            from app.llm.fake import FakeLlmClient
            from app.repositories.memory import MerchantMemoryRepository
            from app.services.memory_service import MemoryService

            llm = (
                DeepSeekLlmClient(self._settings)
                if self._settings is not None and self._settings.llm_api_key
                else FakeLlmClient(configured=False)
            )
            async with self._database.session() as session:
                service = MemoryService(llm, MerchantMemoryRepository(session))
                await service.consolidate(
                    merchant_id=self._merchant_id,
                    merchant_display=self._merchant_display,
                    category=category,
                    manual_markdown=manual,
                    history=[],
                    budget=LlmBudget(max_calls=1, max_tokens=_MEMORY_TASK_MAX_TOKENS),
                    use_llm=not self._daily_cap_hit,
                )
                await session.commit()
            logger.info("记忆沉淀完成", extra={"category": category})
        except Exception:  # noqa: BLE001 — 沉淀失败不得影响已返回的回答
            logger.warning("记忆沉淀失败", extra={"category": category}, exc_info=True)
```

> `DeepSeekLlmClient` / `FakeLlmClient` 的实际导入路径以 `backend/app/api/dependencies.py` 顶部的既有 import 为准，执行时照抄，不要凭记忆写。

- [x] **Step 4: 跑测试确认通过**

```powershell
cd backend
uv run pytest tests/unit/services/test_memory_agent.py -v
```

预期：4 passed

- [x] **Step 5: 接入 ChatService**

`chat_service.py` 的 `__init__` 追加可选参数 `memory_agent=None` 并存字段。在 `_run_agent` 中 `create_message` 成功之后（与参考实现在 persist 节点提交的位置一致）追加：

```python
            if self._memory_agent is not None:
                self._memory_agent.submit(
                    category=str(response.category),
                    question=request.message,
                    answer=response.answer,
                    source_tables=_queried_tables(result.query_result),
                    quality_notes=list(response.quality_notes),
                    suggestions=list(response.suggested_questions),
                    export_id=response.export.id if response.export else None,
                )
```

`_queried_tables` 取本轮真实查过的表名，对应参考实现的 `pendingAnswer.getDorisTables()`：

```python
def _queried_tables(query_result: QueryResult | None) -> list[str]:
    """本轮回答实际依据的经营表，对应参考实现的 pendingAnswer.getDorisTables()。"""

    if query_result is None:
        return []
    return list(query_result.source_tables)
```

`QueryResult.source_tables: tuple[str, ...]` 已存在于 `backend/app/services/safe_query.py:92`，**无需新增字段**。

> 执行前核对 `ChatResponse` 的字段名：`grep -n "class ChatResponse" -A 60 backend/app/schemas/chat.py`，确认 `category` / `suggested_questions` / `export` 的实际名称，不要照抄本计划。

- [x] **Step 6: 接线依赖**

`dependencies.py` 的 `get_chat_service` 签名追加 `background: BackgroundTasks`（FastAPI 支持在依赖函数中注入，且会自动挂到响应上，SSE 的 `StreamingResponse` 同样生效），构造 `MemoryAgent` 传入 `ChatService`：

```python
    memory_agent = MemoryAgent(
        background=background,
        database=database,
        settings=settings,
        merchant_id=context.merchant_id,
        merchant_display=context.merchant_name,
        daily_cap_hit=guard.daily_cap_hit,
    )
```

> `context.merchant_name` 以 `MerchantContext` 实际字段为准，执行前核对。

- [x] **Step 7: 写 SSE 路径的回归测试**

在 `backend/tests/api/` 既有的 chat 测试文件中追加：

```python
async def test_sse_path_registers_memory_task_without_blocking(client, demo_token) -> None:
    """SSE 流结束后后台任务才跑，不得让 done 事件等待沉淀完成。"""

    async with client.stream(
        "POST", "/api/chat",
        json={"message": "上月成交额", "session_id": None},
        headers={"Authorization": f"Bearer {demo_token}"},
    ) as response:
        events = [line async for line in response.aiter_lines()]

    assert any("event: done" in line for line in events)
```

- [x] **Step 8: 跑全量门禁**

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

- [x] **Step 9: 按用户授权延后统一提交**

```bash
git add backend/app/services/memory_agent.py backend/app/services/chat_service.py backend/app/api/dependencies.py backend/tests/
git commit -m "feat: 回答落库后经 BackgroundTasks 异步沉淀记忆，自开会话与预算且失败不外溢"
```

---

## Task 7: 防污染不变量与商家隔离反例

**Files:**
- Test: `backend/tests/unit/knowledge/test_dual_library_invariants.py`

**Interfaces:**
- Consumes: Task 1–6 的全部产物
- Produces: 无新符号，纯回归防线

这些测试的作用是：**任何人日后想让记忆写进团队知识库，都会红。**

- [x] **Step 1: 写不变量测试**

```python
"""双库防污染的四条不变量。

参考实现靠目录边界 + 标记 + 路径策略实现，我们靠表边界 + 标记 + 类型约束。
这些断言一旦变红，说明有人打通了本该单向的写入方向。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import app.services.memory_service as memory_service_module
from app.prompts.memory import MEMORY_MARKER


def test_memory_service_never_touches_knowledge_documents() -> None:
    """写侧单向：记忆服务不得引用团队知识的任何符号。"""

    source = inspect.getsource(memory_service_module)
    assert "KnowledgeDocument" not in source
    assert "KnowledgeRepository" not in source


def test_memory_agent_never_touches_knowledge_documents() -> None:
    source = Path("app/services/memory_agent.py").read_text(encoding="utf-8")
    assert "KnowledgeDocument" not in source
    assert "KnowledgeRepository" not in source


def test_knowledge_repository_exposes_no_memory_write_path() -> None:
    """读侧单向：团队知识仓储不得提供任何写记忆的方法。"""

    source = Path("app/repositories/knowledge.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert not any("memor" in name.lower() for name in method_names)


def test_marker_constant_matches_reference_literal() -> None:
    """标记字面量变了，参考实现导出的历史记忆就读不出来了。"""

    assert MEMORY_MARKER == "本轮自动沉淀"
```

- [x] **Step 2: 跑测试确认全绿**

```powershell
cd backend
uv run pytest tests/unit/knowledge/test_dual_library_invariants.py -v
```

预期：4 passed（这些是防御性断言，实现正确时应一次通过；若红说明前面的 Task 实现串了边界）

- [x] **Step 3: 按用户授权延后统一提交**

```bash
git add backend/tests/unit/knowledge/test_dual_library_invariants.py
git commit -m "test: 固化双知识库单向写入与标记字面量的四条不变量"
```

---

## Task 8: 文档同步

**Files:**
- Modify: `docs/yshopping-parity-audit.md`
- Modify: `docs/project-progress.md`
- Modify: `AGENTS.md`
- Modify: `docs/backend-development-plan.md`

- [x] **Step 1: 结清 parity-audit 的两项挂账**

`docs/yshopping-parity-audit.md` §6「待核实」表格中，把 `WikiMemoryService`（441 行）一行移出待核实，在 §9 能力表追加一行：

| 能力 | 参考证据 | 输入、校验、输出与失败语义 | 我方状态 |
| --- | --- | --- | --- |
| 双知识库与记忆沉淀 | `WikiMemoryService`、`MemoryConsolidationService`、`MerchantQaLangGraph` | 人工库命中即返回且记忆不参与；未命中才取该商家记忆；记忆强制带 `本轮自动沉淀` 标记；沉淀异步且失败只记日志 | ✅ 已实现，来源经 `analysis_sources` 的 `MEMORY` 对用户可见 |

- [x] **Step 2: 登记两项有意偏离**

在 §5「有意偏离」追加：

- **5.4 记忆存储介质：文件系统 → PostgreSQL**。依据 AGENTS.md §8.7；参考实现的 `ensureNoSymbolicLinks` 无对应物，不实现，其余路径校验在 Task「知识库后台」中保留。
- **5.5 记忆文件名 `isolatedPathSegment()` → `(merchant_id, category)` 唯一约束**。数据库中不存在路径穿越，同一语义用约束表达。

- [x] **Step 3: 更新 AGENTS.md 索引**

§8.4 业务服务表中 `memory_service.py` 一行的状态由 [规划] 改为已实现；§9.1 核心表清单里 `[P1] merchant_memories` 标为已落地。

- [x] **Step 4: 更新进度快照**

`docs/project-progress.md` 更新「最后更新」日期为实施当日，在「已完成」追加本轮成果，在「当前阶段」的 P1 状态一行中把「商家记忆闭环」从未实现改为已实现，并如实写明**记忆压缩的真实模型验收尚未执行**（R3，需单独申报）。

- [x] **Step 5: 按用户授权延后统一提交**

```bash
git add docs/ AGENTS.md
git commit -m "docs: 结清双知识库与记忆沉淀的还原度挂账并登记两项有意偏离"
```

---

## 出口判据

- [x] 全量门禁在真实 PostgreSQL 上通过：`REQUIRE_INTEGRATION_DB=1 uv run pytest` 零失败零跳过，且执行期间无其他 agent 并发写同一测试容器。
- [x] `ruff check` / `ruff format --check` / `mypy app` 全绿。
- [x] 人工库有内容时，`analysis_sources` 出现 `KNOWLEDGE` 而**不出现** `MEMORY`；人工库为空且记忆有内容时相反。两种情形各有一条测试。
- [x] 记忆沉淀失败（数据库异常、LLM 异常、每日预算耗尽）三种情形均不影响本轮回答返回，各有一条测试。
- [x] `merchant_memories` 的跨商家读取反例测试通过。
- [x] Task 7 的四条不变量全绿。
- [x] 迁移可 `upgrade → downgrade → upgrade` 往返。
- [x] 文档四处已同步，parity-audit 中 `WikiMemoryService` 不再挂在「待核实」。

**不在本计划范围**：真实模型的记忆压缩验收（R3，需单独申报费用）；知识库维护后台（见
`plans/2026-08-20-knowledge-admin-backend.md`）；`GET/PATCH/DELETE /api/memories` 三个
商家自助记忆端点（P1，属知识库后台计划之后的独立切片）。
