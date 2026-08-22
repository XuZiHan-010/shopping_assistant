# 手动记忆压缩与历史高频推荐还原计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。步骤用 `- [ ]` 跟踪。

**目标：** 还原参考项目的两处记忆相关行为——管理员手动重压记忆（`POST /api/wiki/compress`）与基于历史**高频**问题的猜你想问（`topCategoryQuestions`）。

**架构：** 沿用既有 `路由 → Service → Repository` 分层。压缩端点走 `X-Admin-Token`，复用已有的知识库后台鉴权；猜你想问在 LangGraph 节点内可选注入历史提供者，无历史时回落既有静态池。

**技术栈：** Python 3.12 / FastAPI / SQLAlchemy 2 Async / pytest。

**Spec:** `docs/yshopping-parity-audit.md`、`docs/project-progress.md`（2026-08-21 R9 对照结论）

**前置：** `plans/2026-08-21-workspace-closeout.md` 必须先完成。本计划要提交的 `audit.py`、`schemas/knowledge.py`、`test_knowledge_memory_compress.py` 由收尾计划显式移交，收尾计划不会提交它们。

---

## 1. 全局约束

- **R1** 中文；**R2** 提交需用户明确许可；**R3** 测试必须 mock LLM，全程零真实模型调用；**R4** 模型不得输出 SQL；**R5** 商家隔离与跨商家写入留痕；**R8** 参考目录只读。
- **R7 降级必须可见**：模型不可用时不得返回一个看起来成功的响应。
- **契约变更按权威顺序同步**：先改 `docs/PRD.md` 的产品路径清单，再改 `docs/backend-development-plan.md` §8 的精确契约，然后同步 `docs/frontend-development-plan.md`、`AGENTS.md` 索引、Pydantic Schema、OpenAPI / `docs/api.md`、TypeScript 类型和前后端测试。本轮端点没有 UI 消费者，前端计划须明确“仅生成类型，不新增页面入口”。
- 门禁：

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app

cd ../frontend
npm run codegen:check
```

---

## 2. 已核对的参考事实

**这一节的每条都读过源码。实现时以本节为准，不要凭调用点反推语义。**

### 2.1 压缩端点

| 项 | 参考实现 |
| --- | --- |
| 路径 | `POST /api/wiki/compress`（`ChatController.java:82`） |
| 鉴权 | **有**。`WikiAdminAuthFilter.java:36` 把 `/api/wiki/compress` 与 `/api/admin/wiki/*` 一并纳入管理员令牌过滤；令牌未配置时返回 503 `WIKI_ADMIN_DISABLED` |
| 入参 | `categoryName` + `manualMarkdown` |
| 语义 | 自动沉淀之外的人工兜底：指定商家与分类，补一段人工 Markdown 后重新压缩该商家该分类的记忆 |

> **更正记录**：本计划的前身曾写「参考实现没有鉴权体系」，该说法**错误**，已按上表更正。

### 2.2 猜你想问

`AnswerRepository.java:220-232` 的实际 SQL：

```sql
SELECT question, COUNT(*) cnt
FROM merchant_ai_answer
WHERE merchant_id = ? AND question_category_name = ?
GROUP BY question
ORDER BY cnt DESC, MAX(create_time) DESC
LIMIT ?
```

`MerchantQaLangGraph.java:336-339` 以 `(merchantId, categoryName, 3)` 调用它，`AnswerComposeService.java:135-142` 拿到非空结果即返回前 3 条，**静态分类列表只是无历史时的兜底**。

> **更正记录**：本计划的前身把它实现成「按最近回答排序后去重」，那是「最近问过的问题」，不是「高频问题」。语义完全不同：一个问题问过 5 次但都在两周前，参考实现会把它排在昨天问过一次的问题**前面**，而「最近去重」会把它排在后面。已按上面的 SQL 重写。

---

## 3. 本计划的裁定

### Ruling 1 · 保留我方 REST 路径，登记为有意偏离

2026-08-21 用户裁定：不严格还原参考路径。

| 能力 | 参考路径 | 我方路径 |
| --- | --- | --- |
| 手动压缩 | `POST /api/wiki/compress` | `POST /api/admin/knowledge/memories/compress` |

理由：压缩是管理员对知识/记忆资源的写操作，归进已有的 `/api/admin/knowledge/*` 分组更符合 REST 资源语义，也与我方已实现的知识库后台共用同一套 `X-Admin-Token` 鉴权与错误码；`wiki` 是参考项目的旧 IP 词，与本项目命名规范冲突。

**必须在 `docs/yshopping-parity-audit.md` §5 登记这条偏离**，见 Task 1 步骤 9。

### Ruling 2 · 用量归属到被操作的商家

`LlmCostGuard.__init__`（`backend/app/llm/guard.py:36-45`）要求可信 `merchant_id`，非可选。管理员压缩的 `merchant_id` 来自请求体而非商家 Token，因此：

- **用量与每日预算归属到被操作的那个商家**（`payload.merchant_id`）——记忆是该商家的资产，压缩它消耗的 token 记在它头上，口径一致；
- 该商家 id 在进入 guard 前**必须已通过 `MerchantRepository` 确认存在**，否则等于让请求体决定计费对象；
- 管理员端点**不经过商家限流**（限流按商家 Token 计），这是已知且接受的差异——`ADMIN_TOKEN` 本身是受控凭证，且每日预算熔断仍然生效。

### Ruling 3 · 先写审计，再提交记忆

审计使用独立事务（`AuditRepository` 既有设计，避免业务回滚吞掉审计）。若先提交记忆再写审计，审计失败会留下「已改记忆但无审计记录」的状态，违反 R5 的留痕要求。

**决定：先写审计，再提交记忆事务。** 审计写入失败则整体失败、不落记忆。

残留代价：记忆提交失败时会留下一条「尝试压缩」的审计记录。可接受——审计语义是「谁试图改了什么」，不是「什么改成功了」。

### Ruling 4 · `MemoryService.consolidate` 返回结构化结果

现状：`consolidate()` 用 `except Exception` 吞掉 LLM 异常并回落确定性兜底文本，只返回 `str`。调用方无法区分「模型压缩成功」与「模型没跑、这是规则兜底」。管理员会看到 200 成功响应却不知道模型没执行——违反 R7。

**决定：`consolidate()` 改为返回 `MemoryConsolidation(content, degraded, degraded_reason)`。** 唯一的既有调用方 `MemoryAgent._run()` 忽略返回值，改动安全。

---

## 4. 文件结构

**新建**

| 路径 | 职责 |
| --- | --- |
| `backend/app/services/memory_admin_service.py` | 管理员手动重压记忆的编排：校验商家 → 取历史 → 调 `MemoryService` → 写审计。不拼 SQL、不构造 LLM |
| `backend/tests/unit/services/test_memory_service_degraded.py` | `consolidate()` 降级信号的单测 |
| `backend/tests/integration/repositories/test_top_category_questions.py` | 高频问题查询的频次排序与隔离测试 |
| `backend/tests/unit/agent/test_suggest_questions_history.py` | 猜你想问节点优先历史、无历史回落 |

**修改**

| 路径 | 改动 |
| --- | --- |
| `backend/app/schemas/knowledge.py` | 修重复 `Field` 导入；`MemoryCompressResponse` 增 `degraded` / `degraded_reason` |
| `backend/app/services/memory_service.py` | `consolidate()` 返回 `MemoryConsolidation` |
| `backend/app/services/memory_agent.py` | 适配新返回值（忽略即可，但要让 mypy 通过） |
| `backend/tests/unit/services/test_memory_service.py` | 把既有 4 条字符串返回值断言迁移到 `MemoryConsolidation.content`，并补成功/降级断言 |
| `backend/app/api/dependencies.py` | 抽出 `build_guarded_llm()` 共享助手；给 `MerchantQaGraph` 注入 `history_questions` |
| `backend/app/api/routes/knowledge.py` | 新增压缩路由 |
| `backend/app/repositories/merchant.py` | 新增 `get_display_name()` |
| `backend/app/repositories/answer.py` | 新增 `top_category_questions()` |
| `backend/app/repositories/audit.py` | 提交工作区已有的 `record_admin_action()`（随其第一个消费者一起） |
| `backend/app/agent/graph.py` | `HistoryQuestionsLike` 协议；`_suggest_questions` 优先历史 |
| `docs/yshopping-parity-audit.md` | 登记路径偏离（§5）与猜你想问缺口（§3.8） |
| `docs/backend-development-plan.md` §8 | 补压缩端点的契约行 |
| `docs/PRD.md` §11 | 先补 P1 产品路径清单，保持路径权威来源完整 |
| `docs/frontend-development-plan.md` | 登记本轮 API-only：只更新生成类型，不新增管理端页面入口 |
| `AGENTS.md` | 同步 P1 路径索引与知识库路由职责摘要 |

---

## 5. Task 1：管理员手动记忆压缩端点

**Files:**

- Modify: `backend/app/schemas/knowledge.py`、`backend/app/services/memory_service.py`、`backend/app/services/memory_agent.py`、`backend/tests/unit/services/test_memory_service.py`、`backend/app/api/dependencies.py`、`backend/app/api/routes/knowledge.py`、`backend/app/repositories/merchant.py`
- Create: `backend/app/services/memory_admin_service.py`、`backend/tests/unit/services/test_memory_service_degraded.py`
- Commit-with: `backend/app/repositories/audit.py`（工作区已有 `record_admin_action`，本任务是它的第一个消费者）
- Test: `backend/tests/api/test_knowledge_memory_compress.py`（**工作区已有 4 条，当前必然红**）

**Interfaces:**

- Consumes：`AnswerRepository.recent_answers_for_category(*, merchant_id, category, limit) -> list[dict[str, Any]]`（收尾计划已提交）；`AuditRepository.record_admin_action(*, merchant_id, event_type, resource_type, resource_id, request_id, metadata=None) -> None`
- Produces：`MemoryService.consolidate(...) -> MemoryConsolidation`；`MemoryAdminService.compress(*, merchant_id, category, manual_markdown, request_id) -> MemoryCompressResponse`；`build_guarded_llm(settings, database, *, request_id, merchant_id) -> LlmClient`

- [ ] **步骤 1：跑现有测试，确认红在哪**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/api/test_knowledge_memory_compress.py -v
```

预期：4 条全红，报 404。先看见红。

- [ ] **步骤 2：写 `consolidate()` 降级信号的失败测试**

新建 `backend/tests/unit/services/test_memory_service_degraded.py`：

```python
"""consolidate() 必须让调用方看见「模型没跑」。R7：降级不能伪装成成功。"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.prompts.memory import MEMORY_MARKER
from app.services.memory_service import MemoryService

MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000000a1")


class _StubRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[UUID, str, str]] = []

    async def upsert(self, *, merchant_id: UUID, category: str, content: str) -> object:
        self.saved.append((merchant_id, category, content))
        return object()


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=1, max_tokens=4_000)


@pytest.mark.asyncio
async def test_consolidate_reports_degraded_when_model_unavailable() -> None:
    repository = _StubRepository()
    service = MemoryService(FakeLlmClient(configured=False), repository)

    result = await service.consolidate(
        merchant_id=MERCHANT_ID,
        merchant_display="测试商家",
        category="TRADE",
        manual_markdown="人工补充：大促退款按申请日计。",
        history=[],
        budget=_budget(),
    )

    assert result.degraded is True
    assert result.degraded_reason
    # 降级仍要落盘确定性兜底，人工内容不能丢
    assert "大促退款按申请日计" in result.content
    assert MEMORY_MARKER in result.content
    assert repository.saved


@pytest.mark.asyncio
async def test_consolidate_reports_not_degraded_on_success() -> None:
    repository = _StubRepository()
    service = MemoryService(
        FakeLlmClient(responses=["# TRADE\n\n## 本轮自动沉淀\n\n压缩后的画像"]),
        repository,
    )

    result = await service.consolidate(
        merchant_id=MERCHANT_ID,
        merchant_display="测试商家",
        category="TRADE",
        manual_markdown="人工补充",
        history=[{"question": "上周成交额多少", "answer": "12 万元"}],
        budget=_budget(),
    )

    assert result.degraded is False
    assert result.degraded_reason is None
    assert "压缩后的画像" in result.content
```

- [ ] **步骤 3：跑测试确认失败**

```powershell
uv run pytest tests/unit/services/test_memory_service_degraded.py -v
```

预期：`AttributeError: 'str' object has no attribute 'degraded'`。

- [ ] **步骤 4：改 `MemoryService.consolidate` 的返回类型**

在 `backend/app/services/memory_service.py` 顶部增加 `from dataclasses import dataclass`，再加数据类，并把三条退出路径都带上降级信号：

```python
@dataclass(frozen=True)
class MemoryConsolidation:
    """压缩结果。degraded 为真表示模型未参与，content 是确定性兜底文本。"""

    content: str
    degraded: bool
    degraded_reason: str | None
```

`consolidate()` 改动要点：

- `use_llm=False` → `degraded=True`，`degraded_reason="未启用模型压缩，本次写入确定性兜底文本"`；
- `result.degraded` 为真或 `result.text` 为空 → `degraded=True`，`degraded_reason="模型压缩不可用，本次写入确定性兜底文本"`；
- `except Exception` 分支 → 保留既有 `logger.warning`，同时 `degraded=True`，`degraded_reason="模型压缩调用失败，本次写入确定性兜底文本"`；
- 正常路径 → `degraded=False`，`degraded_reason=None`。

`_ensure_marker` 与 `repository.upsert` 的调用位置不变——**降级也必须落盘**，否则管理员点了压缩什么都没发生。

- [ ] **步骤 5：适配既有调用方**

`backend/app/services/memory_agent.py` 里 `await service.consolidate(...)` 现在收到的是对象而非字符串。它本就忽略返回值，但要让 mypy 通过并留下可观测性：

```python
                consolidation = await service.consolidate(...)
                if consolidation.degraded:
                    logger.info(
                        "记忆沉淀降级为确定性兜底",
                        extra={"category": category, "reason": consolidation.degraded_reason},
                    )
```

同时迁移 `backend/tests/unit/services/test_memory_service.py` 中 4 个既有调用点。这个文件当前把返回值直接当字符串；若不改，全量测试会在实现正确后失败。统一改成：

```python
result = await service.consolidate(...)
content = result.content
```

- 原成功路径继续断言 `content`，并增加 `result.degraded is False`、`result.degraded_reason is None`；
- `use_llm=False`、模型降级和空文本三条路径继续断言兜底内容，并增加 `result.degraded is True`、`result.degraded_reason` 非空；
- 不删除原有 marker、人工内容保留和落盘断言。

- [ ] **步骤 6：跑步骤 2 的测试转绿，并确认既有记忆测试没被打破**

```powershell
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/unit/services/test_memory_service.py tests/unit/services/test_memory_service_degraded.py tests/integration/services/test_memory_agent_history.py -v
```

- [ ] **步骤 7：修 schema 并补降级字段**

`backend/app/schemas/knowledge.py`：

1. 第 9 行 `from pydantic import BaseModel, Field, Field` → `from pydantic import BaseModel, Field`；把 `from uuid import UUID` 归到标准库分组；
2. 从 `app.schemas.chat` 导入 `QuestionCategory`；把请求和响应的 `category: str` 都改成 `category: QuestionCategory`。管理员端点只接受既有业务分类，拼错值应由 Pydantic 直接返回 422，不能创建任意分类记忆；
3. `MemoryCompressResponse` 增两个字段：

```python
class MemoryCompressResponse(BaseModel):
    merchant_id: UUID
    category: QuestionCategory
    content: str
    history_rows: int
    #: R7：模型未参与压缩时必须让管理员看见，不能返回一个看起来成功的响应。
    degraded: bool
    degraded_reason: str | None
```

- [ ] **步骤 8：抽出 `build_guarded_llm` 并写 MemoryAdminService**

先在 `backend/app/api/dependencies.py` 抽出共享助手，替换原地构造（原 `:144-154`）：

```python
def build_guarded_llm(
    settings: Settings,
    database: Database,
    *,
    request_id: str,
    merchant_id: UUID,
) -> LlmCostGuard:
    """构造带费用守卫的模型客户端。

    merchant_id 必须是已确认存在的商家：它决定 token 用量与每日预算的归属，
    不能直接采信请求体（R5）。
    """

    raw: LlmClient = (
        DeepSeekLlmClient(settings) if settings.llm_api_key else FakeLlmClient(configured=False)
    )
    return LlmCostGuard(
        raw,
        LlmBudgetRepository(database),
        settings,
        request_id=request_id,
        merchant_id=merchant_id,
    )
```

聊天依赖里原来那段构造改为调用它，行为不变。

`backend/app/repositories/merchant.py` 追加：

```python
    async def get_display_name(self, merchant_id: UUID) -> str | None:
        """管理端按 id 取商家展示名；不筛 is_demo，管理员操作对象可以是任意商家。"""

        return await self._session.scalar(
            select(Merchant.display_name).where(Merchant.id == merchant_id)
        )
```

新建 `backend/app/services/memory_admin_service.py`：

```python
"""管理员手动重压商家记忆。

对应参考项目 `POST /api/wiki/compress`（`ChatController.java:82`），该端点在参考项目里
同样受管理员令牌保护（`WikiAdminAuthFilter.java:36`）。我方路径按 Ruling 1 改为
`/api/admin/knowledge/memories/compress`，鉴权复用 `X-Admin-Token`。

这是管理员跨商家写入，必须留痕（R5），且审计先于记忆提交（Ruling 3）。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ResourceNotFoundError
from app.llm.client import LlmBudget, LlmClient
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.repositories.memory import MerchantMemoryRepository
from app.repositories.merchant import MerchantRepository
from app.schemas.knowledge import MemoryCompressResponse
from app.services.memory_service import MemoryService

#: 与 MemoryAgent 的自动沉淀保持同一上限，人工触发不该比自动路径更贵。
_COMPRESS_MAX_TOKENS = 4_000
#: 参考实现 recentAnswers(merchantId, 80)。
_HISTORY_LIMIT = 80


class MemoryAdminService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        llm: LlmClient,
        audit: AuditRepository,
    ) -> None:
        self._session = session
        self._llm = llm
        self._audit = audit

    async def compress(
        self,
        *,
        merchant_id: UUID,
        display_name: str,
        category: str,
        manual_markdown: str,
        request_id: str,
    ) -> MemoryCompressResponse:
        history = await AnswerRepository(self._session).recent_answers_for_category(
            merchant_id=merchant_id,
            category=category,
            limit=_HISTORY_LIMIT,
        )
        # Ruling 3：审计先于记忆提交。审计失败则整体失败，不留下无痕的记忆变更。
        await self._audit.record_admin_action(
            merchant_id=merchant_id,
            event_type="ADMIN_MEMORY_COMPRESS",
            resource_type="MERCHANT_MEMORY",
            resource_id=category,
            request_id=request_id,
            metadata={"history_rows": str(len(history))},
        )
        consolidation = await MemoryService(
            self._llm, MerchantMemoryRepository(self._session)
        ).consolidate(
            merchant_id=merchant_id,
            merchant_display=display_name,
            category=category,
            manual_markdown=manual_markdown,
            history=history,
            budget=LlmBudget(max_calls=1, max_tokens=_COMPRESS_MAX_TOKENS),
        )
        await self._session.commit()
        return MemoryCompressResponse(
            merchant_id=merchant_id,
            category=category,
            content=consolidation.content,
            history_rows=len(history),
            degraded=consolidation.degraded,
            degraded_reason=consolidation.degraded_reason,
        )
```

**注意**：商家存在性校验放在路由里而不是服务里——`merchant_id` 必须在构造 `build_guarded_llm` **之前**确认存在（Ruling 2），而 LLM 是服务的构造参数。

- [ ] **步骤 9：加路由**

在 `backend/app/api/routes/knowledge.py` 末尾追加，补齐 `Request`、`Database`、`get_database`、`build_guarded_llm`、`ResourceNotFoundError`、`MemoryCompressRequest`、`MemoryCompressResponse`、`MemoryAdminService`、`AuditRepository`、`MerchantRepository` 的 import：

```python
@router.post(
    "/memories/compress",
    response_model=MemoryCompressResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def compress_memory(
    payload: MemoryCompressRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> MemoryCompressResponse:
    # 先确认商家存在：它决定 token 用量归属，不能直接采信请求体（Ruling 2）。
    display_name = await MerchantRepository(session).get_display_name(payload.merchant_id)
    if display_name is None:
        raise ResourceNotFoundError("商家")

    service = MemoryAdminService(
        session,
        llm=build_guarded_llm(
            settings,
            database,
            request_id=str(request.state.request_id),
            merchant_id=payload.merchant_id,
        ),
        audit=AuditRepository(database),
    )
    return await service.compress(
        merchant_id=payload.merchant_id,
        display_name=display_name,
        category=payload.category.value,
        manual_markdown=payload.manual_markdown,
        request_id=str(request.state.request_id),
    )
```

- [ ] **步骤 10：跑测试转绿**

```powershell
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/api/test_knowledge_memory_compress.py -v
```

预期 4 passed。

测试里 `llm_api_key` 未配置，走 `FakeLlmClient(configured=False)`：其 `complete()` 直接抛 `LlmUnavailableError`（`backend/app/llm/fake.py:41`），被 `consolidate()` 接住回落 `build_fallback_memory()`，后者正文就是 `manual_markdown` 加 `MEMORY_MARKER`。所以那两条断言在**零真实模型调用**下成立（R3），且此时响应的 `degraded` 应为 `True`。

- [ ] **步骤 11：补一条断言降级可见的测试**

现有 4 条测试不覆盖 R7。在 `tests/api/test_knowledge_memory_compress.py` 追加：

```python
@pytest.mark.asyncio
async def test_compress_reports_degraded_when_model_unavailable(
    admin_client: AsyncClient,
    merchant: UUID,
) -> None:
    """测试环境未配置模型，压缩必然走确定性兜底——响应必须如实说出来（R7）。"""

    response = await admin_client.post(
        COMPRESS_PATH,
        json={"merchant_id": str(merchant), "category": "TRADE", "manual_markdown": "人工补充"},
    )

    body = response.json()
    assert body["degraded"] is True
    assert body["degraded_reason"]
```

再补分类枚举校验，防止拼错分类落成新的孤儿记忆：

```python
@pytest.mark.asyncio
async def test_compress_rejects_unknown_category(
    admin_client: AsyncClient,
    merchant: UUID,
) -> None:
    response = await admin_client.post(
        COMPRESS_PATH,
        json={"merchant_id": str(merchant), "category": "TRDAE", "manual_markdown": "人工补充"},
    )

    assert response.status_code == 422
```

此时该文件应为 6 条：原 4 条 + 降级可见 + 非法分类。

- [ ] **步骤 12：同步契约文档与生成物**

按项目规定的权威顺序修改，不能只改后端计划：

1. `docs/PRD.md` §11 的 P1 路径清单先补 `POST /api/admin/knowledge/memories/compress`；
2. `docs/backend-development-plan.md` §8 的 P1 接口表补同一路径，凭证列写 `X-Admin-Token`，请求 `MemoryCompressRequest`，响应 `MemoryCompressResponse`，错误 `401 403 404 422`；
3. `docs/frontend-development-plan.md` 的 F8 / API 说明登记：本轮端点是 API-only，只更新生成类型，不增加知识库页面按钮；若以后增加人工压缩入口，另立交互设计；
4. `AGENTS.md` §10.2 的 P1 路径清单与知识库路由职责同步该端点；
5. 导出与 codegen：

```powershell
cd backend
uv run python ../scripts/export_openapi.py
cd ../frontend
npm run codegen
npm run codegen:check
```

- [ ] **步骤 13：登记路径偏离**

在 `docs/yshopping-parity-audit.md` §5 新增：

```markdown
### 5.8 手动记忆压缩改走管理员知识库路径

参考项目是 `POST /api/wiki/compress`（`ChatController.java:82`），且已由
`WikiAdminAuthFilter.java:36` 纳入管理员令牌过滤。我方路径改为
`POST /api/admin/knowledge/memories/compress`。

理由：压缩是管理员对记忆资源的写操作，归进已有的 `/api/admin/knowledge/*` 分组
更符合 REST 资源语义，也与我方知识库后台共用同一套 `X-Admin-Token` 鉴权与错误码；
`wiki` 是参考项目旧 IP 词，与本项目命名规范冲突。

鉴权强度与参考一致（均要求管理员令牌），仅路径与分组不同。2026-08-21 用户裁定保留。
```

- [ ] **步骤 14：跑全量门禁**（见 §1）

- [ ] **步骤 15：提交（需许可）**

```bash
git add backend/app/repositories/audit.py backend/app/repositories/merchant.py \
  backend/app/schemas/knowledge.py backend/app/services/memory_service.py \
  backend/app/services/memory_agent.py backend/app/services/memory_admin_service.py \
  backend/app/api/dependencies.py backend/app/api/routes/knowledge.py \
  backend/tests/api/test_knowledge_memory_compress.py \
  backend/tests/unit/services/test_memory_service.py \
  backend/tests/unit/services/test_memory_service_degraded.py \
  docs/PRD.md docs/backend-development-plan.md docs/frontend-development-plan.md \
  AGENTS.md docs/yshopping-parity-audit.md \
  docs/api.md docs/api.json frontend/src/api/generated.ts
git commit -m "feat: 补齐管理员手动记忆压缩端点并让压缩降级可见"
```

---

## 6. Task 2：猜你想问用历史高频问题

**保留我方增强**：`suggestion_alternates`（换一换）是我方已有能力，参考项目的换一换在前端。历史命中时 `current` 用历史高频问题，`alternates` 仍用静态池，保证换一换不空。

**Files:**

- Modify: `backend/app/repositories/answer.py`、`backend/app/agent/graph.py`、`backend/app/api/dependencies.py`
- Create: `backend/tests/integration/repositories/test_top_category_questions.py`、`backend/tests/unit/agent/test_suggest_questions_history.py`
- Modify: `docs/yshopping-parity-audit.md`

**Interfaces:**

- Produces：`AnswerRepository.top_category_questions(*, merchant_id: UUID, category: str, limit: int) -> list[str]` —— 按出现次数降序、同次数按最近一次提问时间降序
- Produces：`MerchantQaGraph.__init__` 新增关键字参数 `history_questions: HistoryQuestionsLike | None = None`

```python
class HistoryQuestionsLike(Protocol):
    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]: ...
```

- [ ] **步骤 1：写仓储层失败测试**

新建 `backend/tests/integration/repositories/test_top_category_questions.py`。必须使用仓库实际存在的 `db_session` fixture；本测试会重复同一问题，`client_request_id` 必须每轮用 `uuid4()`，不能复用 `test_answer_history.py` 里按问题拼接 id 的 helper，否则会先撞幂等唯一约束、根本测不到频次排序。

**第一条是本任务的核心断言**——它区分「高频」与「最近」，前一版计划正是因为缺了它才让错误实现绿着通过：

```python
"""商家历史高频问题：频次排序、最近时间破同分、隔离与上限。"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.answer import AnswerRepository
from app.repositories.conversation import ConversationRepository

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000031")
OTHER_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000032")


async def _insert_merchants(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Merchant(
                id=MERCHANT_ID,
                merchant_code="top-question-one",
                display_name="高频问题商家一",
            ),
            Merchant(
                id=OTHER_MERCHANT_ID,
                merchant_code="top-question-two",
                display_name="高频问题商家二",
            ),
        ]
    )
    await db_session.flush()


async def _record_answer(
    db_session: AsyncSession,
    *,
    merchant_id: UUID,
    question: str,
    category: str,
    succeeded: bool = True,
) -> None:
    conversations = ConversationRepository(db_session)
    conversation = await conversations.create(merchant_id, question[:20])
    message = await conversations.create_message(
        merchant_id, conversation.id, "USER", question
    )
    answer = await conversations.create_processing_answer(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        user_message_id=message.id,
        client_request_id=str(uuid4()),
        request_digest="0" * 64,
    )
    if not succeeded:
        await conversations.mark_answer_failed(
            answer, retryable=False, error_payload={"code": "TEST"}
        )
    else:
        payload: dict[str, Any] = {"answer": "测试回答", "category": category}
        await conversations.mark_answer_succeeded(answer, payload)
    # PostgreSQL 的 now() 是事务开始时间；逐轮提交才能可靠测 MAX(created_at)。
    await db_session.commit()


@pytest.mark.asyncio
async def test_top_category_questions_ranks_by_frequency_not_recency(
    db_session: AsyncSession,
) -> None:
    """参考 SQL 是 GROUP BY question ORDER BY COUNT(*) DESC, MAX(create_time) DESC。

    造数刻意让「高频但久远」与「低频但最近」冲突：
      - "成交额为什么下降" 先问 3 次
      - "昨天成交额多少" 只问过 1 次，就在刚才
    按频次排，前者必须在前；按最近排，后者会在前。
    """

    await _insert_merchants(db_session)
    for _ in range(3):
        await _record_answer(
            db_session,
            merchant_id=MERCHANT_ID,
            question="成交额为什么下降",
            category="TRADE",
        )
    await _record_answer(
        db_session,
        merchant_id=MERCHANT_ID,
        question="昨天成交额多少",
        category="TRADE",
    )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert rows[0] == "成交额为什么下降"
    assert "昨天成交额多少" in rows


@pytest.mark.asyncio
async def test_top_category_questions_breaks_ties_by_most_recent(
    db_session: AsyncSession,
) -> None:
    """同为 2 次时，最近问过的排前面（参考的 MAX(create_time) DESC）。"""

    await _insert_merchants(db_session)
    for question in ["较远的两次问题"] * 2 + ["较近的两次问题"] * 2:
        await _record_answer(
            db_session,
            merchant_id=MERCHANT_ID,
            question=question,
            category="TRADE",
        )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=2
    )

    assert rows == ["较近的两次问题", "较远的两次问题"]


@pytest.mark.asyncio
async def test_top_category_questions_isolates_merchant_and_category(
    db_session: AsyncSession,
) -> None:
    await _insert_merchants(db_session)
    for merchant_id, category, question in [
        (MERCHANT_ID, "TRADE", "本家交易问题"),
        (MERCHANT_ID, "TRADE", "本家交易问题"),
        (MERCHANT_ID, "REFUND", "本家退款问题"),
        (OTHER_MERCHANT_ID, "TRADE", "别家交易问题"),
    ]:
        await _record_answer(
            db_session,
            merchant_id=merchant_id,
            question=question,
            category=category,
        )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert rows == ["本家交易问题"]
    assert "本家退款问题" not in rows
    assert "别家交易问题" not in rows


@pytest.mark.asyncio
async def test_top_category_questions_skips_unsuccessful_answers(
    db_session: AsyncSession,
) -> None:
    await _insert_merchants(db_session)
    await _record_answer(
        db_session,
        merchant_id=MERCHANT_ID,
        question="失败的问题",
        category="TRADE",
        succeeded=False,
    )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert rows == []


@pytest.mark.asyncio
async def test_top_category_questions_honours_limit(db_session: AsyncSession) -> None:
    await _insert_merchants(db_session)
    for index in range(5):
        await _record_answer(
            db_session,
            merchant_id=MERCHANT_ID,
            question=f"问题 {index}",
            category="TRADE",
        )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert len(rows) == 3
    assert len(set(rows)) == 3
```

- [ ] **步骤 2：跑测试确认失败**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/repositories/test_top_category_questions.py -v
```

预期：`AttributeError: 'AnswerRepository' object has no attribute 'top_category_questions'`。

- [ ] **步骤 3：实现仓储方法**

在 `backend/app/repositories/answer.py` 追加。聚合下推到 SQL，**不要在 Python 里数次数**——分类过滤与频次统计都能下推，取回全部历史再统计会随商家问答量线性变慢：

```python
    async def top_category_questions(
        self,
        *,
        merchant_id: UUID,
        category: str,
        limit: int,
    ) -> list[str]:
        """取该商家该分类的历史**高频**问题，用作「猜你想问」。

        对齐参考实现 ``AnswerRepository.topCategoryQuestions``（Java 版 220-232 行）：

            SELECT question, COUNT(*) cnt ... GROUP BY question
            ORDER BY cnt DESC, MAX(create_time) DESC LIMIT ?

        排序是「问得多的在前，同样多则最近问过的在前」，不是「最近问过的在前」——
        一个问过 5 次但都在两周前的问题，要排在昨天问过一次的问题前面。

        Answer 与 Message 两侧都按 ``merchant_id`` 强制过滤（R5，纵深防御）；只统计成功回答，失败轮次不进推荐。
        """

        occurrences = func.count().label("occurrences")
        latest = func.max(Answer.created_at).label("latest")
        statement = (
            select(Message.content)
            .join(Answer, Answer.user_message_id == Message.id)
            .where(
                Answer.merchant_id == merchant_id,
                Message.merchant_id == merchant_id,
                Answer.processing_status == "SUCCEEDED",
                Answer.response_payload["category"].astext == category,
                Message.content != "",
            )
            .group_by(Message.content)
            .order_by(occurrences.desc(), latest.desc())
            .limit(limit)
        )
        return [row for (row,) in (await self._session.execute(statement)).all()]
```

`func` 从 `sqlalchemy` 导入。同一次修改顺手把既有 `recent_answers_for_category()` 的 `.where(...)` 也补上 `Message.merchant_id == merchant_id`；它同样连接用户消息，不能只依赖 Answer 一侧的租户字段。集成隔离测试必须继续通过。

- [ ] **步骤 4：跑测试转绿**

```powershell
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/repositories/test_top_category_questions.py -v
```

预期 5 passed。若「频次 vs 最近」那条仍红，检查 `order_by` 的第一顺位是不是 `occurrences.desc()`。

- [ ] **步骤 5：写节点层失败测试**

新建 `backend/tests/unit/agent/test_suggest_questions_history.py`。用完整可运行的最小 graph fixture，不留“照抄”或省略步骤：

```python
"""猜你想问优先商家历史高频问题，查询异常或无历史时安全回落。"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.suggested_questions import suggestions_for

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000041")


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _NoMetric:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _StubHistory:
    def __init__(self, questions: list[str]) -> None:
        self._questions = questions
        self.calls: list[tuple[str, int]] = []

    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]:
        self.calls.append((category, limit))
        return self._questions


class _RaisingHistory:
    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]:
        raise RuntimeError("history unavailable")


def _llm() -> FakeLlmClient:
    return FakeLlmClient(
        responses=[
            json.dumps(
                {"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}
            ),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": [],
                    "filters": {},
                    "date_range": None,
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )


def _graph(
    history_questions: _StubHistory | _RaisingHistory | None,
) -> MerchantQaGraph:
    llm = _llm()
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        merchant_id=MERCHANT_ID,
        history_questions=history_questions,
    )


@pytest.mark.asyncio
async def test_suggestions_prefer_merchant_history() -> None:
    expected = ["高频问题一", "高频问题二", "高频问题三"]
    history = _StubHistory(expected)

    result = await _graph(history).run("昨天 GMV", uuid4())

    assert result.response.suggestions == expected
    assert history.calls == [("TRADE", 3)]
    assert result.response.suggestion_alternates


@pytest.mark.asyncio
async def test_suggestions_fall_back_to_presets_without_history() -> None:
    result = await _graph(_StubHistory([])).run("昨天 GMV", uuid4())

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert result.response.suggestions == expected.current
    assert result.response.suggestion_alternates == expected.alternates


@pytest.mark.asyncio
async def test_suggestions_fall_back_when_provider_absent() -> None:
    result = await _graph(None).run("昨天 GMV", uuid4())

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert result.response.suggestions == expected.current


@pytest.mark.asyncio
async def test_suggestions_fall_back_when_provider_raises() -> None:
    result = await _graph(_RaisingHistory()).run("昨天 GMV", uuid4())

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert result.response.suggestions == expected.current
```

四条测试分别锁定：命中历史、历史为空、未注入 provider、provider 查询异常。最后一条很重要：推荐问题是回答后的附加能力，历史统计库暂时不可用不能拖垮已经生成的主回答。

- [ ] **步骤 6：跑测试确认失败**

```powershell
uv run pytest tests/unit/agent/test_suggest_questions_history.py -v
```

预期：构造函数尚不接受 `history_questions`，测试失败。

- [ ] **步骤 7：改节点**

`backend/app/agent/graph.py` 增加 `import logging` 与模块级 `logger = logging.getLogger(__name__)`；构造函数追加 `history_questions: HistoryQuestionsLike | None = None` 并保存到 `self._history_questions`。`_suggest_questions` 改为：

```python
    async def _suggest_questions(self, state: AgentState) -> dict[str, object]:
        intent = _required(state["intent"])
        preset = suggestions_for(intent.category, intent.answer_mode)
        current = preset.current
        if self._history_questions is not None and self._merchant_id is not None:
            # 参考行为：该商家该分类的历史高频问题优先，静态池只作兜底。
            try:
                history = await self._history_questions.top_category_questions(
                    merchant_id=self._merchant_id,
                    category=intent.category.value,
                    limit=len(preset.current) or 3,
                )
            except Exception:
                # 推荐问题是附加能力；统计查询失败不能让已生成的主回答一起失败。
                logger.warning(
                    "历史推荐问题查询失败，回落静态推荐",
                    extra={"category": intent.category.value},
                    exc_info=True,
                )
            else:
                if history:
                    current = history
        return {
            **self._step(state, "suggest_questions"),
            "suggestions": current,
            "suggestion_alternates": preset.alternates,
        }
```

**`category` 传 `intent.category.value`**（与写入 `response_payload["category"]` 的值同源），不是中文 `display_name`。参考项目用中文分类名做匹配键是它的缺陷，`docs/yshopping-parity-audit.md` §5.1 已登记 `metric_code` 那条同类偏离。

- [ ] **步骤 8：跑测试转绿**

```powershell
uv run pytest tests/unit/agent/test_suggest_questions_history.py -v
```

预期 4 passed；其中 provider 抛异常时主回答仍成功、推荐问题回落静态池。

- [ ] **步骤 9：接线**

`backend/app/api/dependencies.py` 的 `MerchantQaGraph(...)` 调用补一行：

```python
        history_questions=AnswerRepository(session),
```

`AnswerRepository` 天然满足 `HistoryQuestionsLike`，不需要适配器。

- [ ] **步骤 10：跑全量门禁**

特别关注 `tests/api/` 下断言固定猜你想问文案的既有测试：其 fixture 无历史问答，应仍走静态兜底。若变红，说明该测试确实造了历史数据，按实际行为更新断言，**不要回退实现**。

- [ ] **步骤 11：登记缺口**

在 `docs/yshopping-parity-audit.md` §3 新增：

```markdown
### 3.8 猜你想问未使用历史高频问题

**状态：✅ 已修复（2026-08-2X）。**

**参考**：`AnswerRepository.topCategoryQuestions`（220-232 行）是
`GROUP BY question ORDER BY COUNT(*) DESC, MAX(create_time) DESC LIMIT ?`；
`MerchantQaLangGraph.suggestQuestions()` 以 `(merchantId, categoryName, 3)` 调用，
`AnswerComposeService.suggestions()` 历史非空即返回前 3 条，静态分类列表只作兜底。

**我们（修复前）**：`suggestions_for(category, answer_mode)` 纯静态配置，docstring 明写
「不参与模型决策，也不由模型生成」，历史那一路完全缺失。本条在第一轮全局审计中未被发现，
2026-08-21 复查时才对出。

**修复**：`AnswerRepository.top_category_questions()` 按频次聚合，
`MerchantQaGraph` 可选注入 `history_questions`；历史命中用历史，无历史回落静态池，
`suggestion_alternates` 始终来自静态池以保证「换一换」不空。
```

- [ ] **步骤 12：提交（需许可）**

```bash
git add backend/app/repositories/answer.py backend/app/agent/graph.py \
  backend/app/api/dependencies.py \
  backend/tests/integration/repositories/test_top_category_questions.py \
  backend/tests/unit/agent/test_suggest_questions_history.py \
  docs/yshopping-parity-audit.md
git commit -m "feat: 猜你想问改用商家历史高频问题"
```

---

## 7. 完成判据

- [ ] `POST /api/admin/knowledge/memories/compress` 有 6 条通过的 API 测试（含降级可见与非法分类各一条）；
- [ ] `consolidate()` 的降级信号有单测覆盖，且降级仍会落盘兜底文本；
- [ ] `top_category_questions` 有一条**能区分频次与最近**的测试，且它在错误实现下会红；
- [ ] 历史推荐查询异常只回落静态推荐，不会拖垮主回答；Answer 与 Message 两侧都有 `merchant_id` 过滤；
- [ ] `docs/yshopping-parity-audit.md` 同时有 §3.8（缺口已修）与 §5.8（路径偏离）两条登记；
- [ ] OpenAPI、`docs/api.md`、`frontend/src/api/generated.ts` 已重新生成且 `codegen:check` 绿；
- [ ] 全量门禁绿，全程零真实模型调用。
