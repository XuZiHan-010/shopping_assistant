# Chat BI 衡量层实施计划

> **执行状态（2026-08-24）**：Task 1–10 的功能、文档和验证步骤已完成；真实 PostgreSQL
> 全量回归为 1049 passed，前端 Vitest 为 295 passed、Playwright 为 29 passed。各 Task 最后的
> `git commit` 步骤仍未执行，因为 `AGENTS.md` R2 要求用户对发布操作另行明确授权。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已经落在 `answers` / `feedback` / `llm_usage` 里的问答数据，聚合成一张日粒度汇总表和五项北极星指标，并提供一个管理员看板页面。

**Architecture:** 三层。① 事实层：给 `answers` 补一个 `elapsed_ms` 列，补齐唯一缺失的原始事实；② 汇总层：新增 `chatbi_qa_daily`（日期 × 商家 × 问题分类），**只存可加的计数，不存比率**，由幂等 Rollup Job 从明细重算并 upsert；③ 服务层：读汇总表、在应用层算比率，经 `X-Admin-Token` 保护的 `/api/admin/analytics/chatbi/*` 提供给新增的 `/ops-dashboard` 页面。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 Async / Alembic / PostgreSQL；Vue 3 + TypeScript / Pinia / ECharts / Vitest / Playwright。

**Spec:** 本文件 §0。本轮不单独建 `docs/specs/` 文档——设计裁定只有三条且全部来自用户当面裁定，写在计划正文里比拆成两份文档更不容易脱节。若后续范围扩大再抽出独立 spec。

**上游：** `plans/2026-08-22-parity-and-resume-roadmap.md` §9「Chat BI 衡量仪表盘（B 类自研）」。该路线图把本能力定为 B 类自研并写下「**口径没定不开工**」，同时列出设计说明必须回答的四个问题。本计划 §0 逐条回答：

| 路线图要求回答的问题 | 本计划的答复 | 位置 |
| --- | --- | --- |
| 五个指标各自的精确口径（分子/分母/时间窗/是否按商家分组） | 六项（准确率拆成双口径）的分子分母、`Asia/Shanghai` 日粒度、按商家 × 分类存储后上卷 | §0.1 |
| 出口是 `GET /api/admin/ops/chatbi` 还是扩 `ops/status` | **两者都不是**，另起 `/api/admin/analytics/chatbi/*`。理由见下 | §0.4、Task 6 |
| 前端走新路由还是并进 `KnowledgeBaseView` | 新路由 `/ops-dashboard`，复用 `AdminTokenDialog` | §0.4、Task 9 |
| 是否需要单独问答记录表 | **不新建问答记录表**，只新建聚合表。理由见下 | §0.2、Task 2 |

两处需要明确说明的取舍：

1. **为什么不挂在 `ops/status` 下**。路线图正确地指出「既有契约明确禁止运维端点返回商家经营数据」。`ops/status` 是运行时健康快照（预算余量、限流命中、降级计数），语义是「系统现在怎么样」；Chat BI 是历史质量分析，语义是「这段时间回答得怎么样」。塞进同一个端点会让那条禁令变得难以维护。独立到 `analytics` 前缀后，禁令仍然完整成立：本计划的响应里没有 `merchant_id`、没有问题原文、没有回答正文，Task 6 有专门的用例（`test_response_contains_no_merchant_identifiers`）钉住这一点。

2. **`chatbi_qa_daily` 不违反「不要新建冗余表」**。路线图那句警告针对的是「为对齐简历措辞，再建一张和 `answers` 重复的问答记录表」——这个警告完全正确，本计划**没有**建那种表。`answers` 依然是唯一的问答记录，`chatbi_qa_daily` 存的是它的日粒度聚合计数，不含任何问答内容，且可以随时从 `answers` 完整重算（Task 4 的幂等 Rollup 就是这个重算）。删掉这张表不会丢失任何信息，只会让看板变慢——这正是聚合表与冗余记录表的分界。用户已于本轮明确裁定采用 ADS 日汇总表形态。

---

## Global Constraints

以下为项目级约束，**每个 Task 的要求都隐含包含本节**，不再逐条重复：

- **R1** 面向用户的内容（页面文案、错误提示、注释、文档）一律中文；代码标识符英文。
- **R2** 未经用户明确许可，不执行 `git commit` / `git push` / `git tag` / `gh pr create` / `gh pr merge`，也不使用 `git reset --hard`、`git clean`。**本计划各 Task 末尾的 Commit 步骤，需用户逐次授权后才执行。**
- **R3** 本计划**全程不需要真实 LLM 调用**。所有测试 mock LLM。如果任何一步看起来需要调模型，说明实现跑偏了，停下来检查。
- **R4** LLM 不生成也不执行 SQL。本计划新增的所有 SQL 都是后端固定模板 + 绑定参数。
- **R5** 商家数据隔离。`chatbi_qa_daily` 的最细粒度带 `merchant_id`；**全平台汇总只允许出现在管理员端点**，商家侧接口不得读该表。
- **R6** 密钥只来自环境变量。本计划不新增任何密钥，复用既有 `ADMIN_TOKEN`。
- **R7** 降级必须可见。指标分母为 0 时返回 `null` 并在页面显示「样本不足」，**不得渲染成 0%**。
- **R10** 本文件属实施计划，放 `plans/`；不新建 `docs/superpowers/` 或任何以技能命名的目录。
- **契约同步**：接口字段变化必须同步 ① `docs/backend-development-plan.md` §8 → ② Pydantic Schema → ③ OpenAPI 与 `docs/api.md` → ④ TypeScript 类型 → ⑤ 前端渲染 → ⑥ 后端与端到端测试。新增接口路径必须先改 `docs/PRD.md` §11，再改 `AGENTS.md` §10。见 Task 8。
- **前端字段流向单向**：`OpenAPI → api/generated.ts → api/adapters/*.ts → types/*.ts → Store → 组件`。组件**不得**直接消费 `generated.ts`，也不得自行做字段转换。
- **管理员令牌不复用 `Authorization`**：`/api/admin/*` 只认 `X-Admin-Token`。
- **迁移链**：当前 head 是 `20260821_0012`。本计划新增两个迁移，`20260823_0013`（`elapsed_ms`）与 `20260823_0014`（`chatbi_qa_daily`），必须串在这条链上，**不得产生第二个 head**。
- **验证命令**（每个 Task 的「跑测试」步骤都用这套）：

  ```powershell
  cd backend
  uv run pytest <具体路径> -v
  uv run ruff check .
  uv run mypy .
  ```

  ```powershell
  cd frontend
  npm run test
  npm run lint
  npm run typecheck
  ```

---

## §0 设计裁定（本计划的 Spec）

### 0.1 五项北极星指标的精确口径

**基准集合**：窗口内 `answers.processing_status = 'SUCCEEDED'` 的回答，记为 `answer_total`。
所有日期按业务时区 `Asia/Shanghai` 归日，复用既有 `app.analytics.dates` 的同一时区来源。

| 指标 | 分子 | 分母 | 分母为 0 时 |
| --- | --- | --- | --- |
| 回复采纳率 `adoption_rate` | `feedback.is_adopted = true` 的回答数 | `answer_total` | `null` |
| 用户侧准确率 `user_accuracy_rate` | `feedback.reaction = 'LIKE'` | `LIKE + DISLIKE` | `null` |
| 系统侧准确率 `system_accuracy_rate` | `quality_status = 'PASSED'` 且 `quality_attempts = 1` | `answer_total` | `null` |
| 平均思考时长 `avg_thinking_ms` | `SUM(elapsed_ms)` | `COUNT(elapsed_ms IS NOT NULL)` | `null` |
| 问题命中率 `hit_rate` | `answer_mode NOT IN ('CHAT','INVALID')` 且 `analysis_sources` 不等于 `['NONE']` | `answer_mode != 'CHAT'` 的回答数（`business_question_total`） | `null` |
| 回答失效率 `failure_rate` | `degraded = true` 或 `quality_status IN ('DEGRADED','FAILED')` | `answer_total` | `null` |

用到的枚举取值（来自 `backend/app/schemas/chat.py`，不要凭记忆改写）：

- `AnswerMode`：`METRIC` / `DETAIL` / `RULE` / `IDENTITY` / `CHAT` / `INVALID` / `ATTACHMENT`
- `QualityStatus`：`PASSED` / `DEGRADED` / `FAILED` / `NOT_RUN`
- `AnalysisSource`：`DATABASE` / `KNOWLEDGE` / `ATTACHMENT` / `MEMORY` / `FALLBACK` / `NONE`
- `QuestionCategory`：`PLATFORM_RULE` / `TRADE` / `REFUND` / `CS_TICKET` / `COMPENSATION` / `COUPON` / `GOODS` / `MERCHANT_OTHER` / `IDENTITY` / `SCM` / `UNKNOWN`

**为什么准确率是双口径**：我们没有人工标注的正确答案，算不出真准确率。用户侧衡量「商家满不满意」，样本少但真实；系统侧衡量「Reviewer 一次放行率」，样本全但只是模型自评。两个数分开展示、分开命名，**任何一个都不冒充「准确率」**。

**为什么问题命中率的分母排除 CHAT**：打招呼本来就不该命中任何数据或知识资产，把它算进分母会让命中率随闲聊量漂移，失去衡量意义。`INVALID` 留在分母里——那正是「没命中」。

**为什么分母为 0 返回 `null` 而不是 0**：R7。`0%` 和「没有样本」在看板上是完全不同的结论，混为一谈会误导。

### 0.2 汇总表只存计数，不存比率

`chatbi_qa_daily` 只存分子分母的**计数**，比率一律在应用层算。原因是**比率不可加**：三天的采纳率不是三个日采纳率的平均，必须先把分子分母各自求和再相除。存计数则任意时间窗、任意商家、任意分类的上卷都只是 `SUM`。

同理，表的最细粒度固定为 `(stat_date, merchant_id, category)` 三元组，**不存「全平台」「全分类」这类汇总行**。PostgreSQL 里 `NULL != NULL`，用 `NULL` 当「全部」的哨兵会让唯一约束失效、允许写进重复汇总行；上卷交给查询时的 `SUM` 更安全也更像真实数仓的 ADS 层。

### 0.3 物化由幂等 Job 负责，可任意重跑

`app/jobs/chatbi_rollup.py` 接受一个日期区间，从 `answers` / `feedback` 重算该区间的计数并 `ON CONFLICT DO UPDATE` 覆盖写入。**重跑同一天必须得到同一结果**，这样补数、修口径、修 Bug 之后重刷历史都是安全操作。管理员可通过 `POST /api/admin/analytics/chatbi/rollup` 手动触发（便于演示和补数），Railway Cron 亦可直接跑 CLI。

### 0.4 看板位置与鉴权

新增 `/ops-dashboard` 路由，复用知识库后台已有的 `AdminTokenDialog` 内存令牌流程（令牌只进内存与请求头，不落 localStorage / URL / 日志 / 构建产物）。接口走 `/api/admin/analytics/chatbi/*`，只认 `X-Admin-Token`。

---

## File Structure

**后端新建**

| 路径 | 职责 |
| --- | --- |
| `backend/migrations/versions/20260823_0013_answer_elapsed_ms.py` | 给 `answers` 加 `elapsed_ms` |
| `backend/migrations/versions/20260823_0014_create_chatbi_qa_daily.py` | 建汇总表 |
| `backend/app/models/chatbi.py` | `ChatBiQaDaily` ORM |
| `backend/app/analytics/chatbi_metrics.py` | 计数 → 比率的**纯函数**，不碰数据库 |
| `backend/app/repositories/chatbi.py` | 汇总表的写（upsert）与读（上卷查询） |
| `backend/app/jobs/chatbi_rollup.py` | 幂等物化 Job + CLI 入口 |
| `backend/app/services/chatbi_service.py` | 组装 overview / categories 响应 |
| `backend/app/schemas/analytics.py` | 三个端点的响应 Schema |
| `backend/app/api/routes/analytics.py` | 三个管理员端点 |

**后端修改**

| 路径 | 改什么 |
| --- | --- |
| `backend/app/models/answer.py` | `Answer` 加 `elapsed_ms` 列 |
| `backend/app/repositories/conversation.py:214` | `mark_answer_succeeded` 增加 `elapsed_ms` 入参 |
| `backend/app/services/chat_service.py:234` | 计时并传入 `elapsed_ms` |
| `backend/app/api/router.py` | 注册 analytics 路由 |
| `backend/app/db/base.py` | 导入新 ORM，让 Alembic 能发现 |

**前端新建**

| 路径 | 职责 |
| --- | --- |
| `frontend/src/api/analytics.ts` | 三个端点的调用 |
| `frontend/src/api/adapters/analytics.ts` | 生成类型 → 领域模型的唯一转换点 |
| `frontend/src/types/analytics.ts` | 看板领域模型 |
| `frontend/src/stores/analytics.ts` | 令牌、窗口、加载态、数据 |
| `frontend/src/views/OpsDashboardView.vue` | 看板页 |
| `frontend/src/components/analytics/NorthStarCards.vue` | 六张指标卡（含样本不足态） |
| `frontend/src/components/analytics/TrendChart.vue` | ECharts 日趋势，异步加载 |
| `frontend/src/components/analytics/CategoryTable.vue` | 按问题分类下钻表 |

**前端修改**：`frontend/src/router/index.ts` 加一条懒加载路由。

**文档修改**：`docs/PRD.md` §11、`docs/backend-development-plan.md` §8、`docs/api.md`（导出）、`AGENTS.md` §10.2 与文件索引、`docs/project-progress.md`、`docs/yshopping-parity-audit.md`（登记为我方增强）。

---

## Task 1: `answers.elapsed_ms` —— 补齐唯一缺失的原始事实

五项指标里只有「平均思考时长」在库里没有原始数据。`ThinkingStep` 只有 `label` 和 `node` 两个字段，不带耗时；`OperationalMetrics.agent_node_average_ms` 是进程内存里的滑动平均，重启即丢，也无法按日期/商家/分类切分。所以必须落一列。

**Files:**
- Create: `backend/migrations/versions/20260823_0013_answer_elapsed_ms.py`
- Modify: `backend/app/models/answer.py`
- Modify: `backend/app/repositories/conversation.py:214-222`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/unit/services/test_chat_service.py`（追加）

**Interfaces:**
- Consumes: 无（本计划第一个 Task）
- Produces:
  - `Answer.elapsed_ms: Mapped[int | None]`
  - `ConversationRepository.mark_answer_succeeded(answer: Answer, response_payload: dict[str, Any], *, elapsed_ms: int | None = None) -> None`

- [ ] **Step 1: 写失败的单元测试**

先读 `backend/tests/unit/services/test_chat_service.py` 已有的 fixture 与假 Repository 名称并复用，不要新造一套装配。在该文件末尾追加：

```python
@pytest.mark.asyncio
async def test_chat_service_records_elapsed_ms(chat_service_harness) -> None:
    """一轮成功问答必须把耗时写进 answers.elapsed_ms。"""
    harness = chat_service_harness
    await harness.service.handle(harness.request, harness.context)

    assert harness.conversations.last_elapsed_ms is not None
    assert harness.conversations.last_elapsed_ms >= 0
```

同时给该文件里的假 Repository 的 `mark_answer_succeeded` 补上记录：

```python
    async def mark_answer_succeeded(
        self, answer, response_payload, *, elapsed_ms=None
    ) -> None:
        self.last_elapsed_ms = elapsed_ms
        ...
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd backend; uv run pytest tests/unit/services/test_chat_service.py::test_chat_service_records_elapsed_ms -v`
Expected: FAIL，`TypeError: mark_answer_succeeded() got an unexpected keyword argument 'elapsed_ms'`

- [ ] **Step 3: 写迁移**

创建 `backend/migrations/versions/20260823_0013_answer_elapsed_ms.py`：

```python
"""Add per-answer elapsed milliseconds for the Chat BI thinking-time metric.

Revision ID: 20260823_0013
Revises: 20260821_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0013"
down_revision: str | Sequence[str] | None = "20260821_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("elapsed_ms", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_answers_elapsed_ms_nonnegative",
        "answers",
        "elapsed_ms IS NULL OR elapsed_ms >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_answers_elapsed_ms_nonnegative", "answers", type_="check")
    op.drop_column("answers", "elapsed_ms")
```

列**可空**：历史回答没有耗时，回填一个假值会污染平均值。指标计算的分母只数非空行（§0.1）。

- [ ] **Step 4: 加 ORM 列**

在 `backend/app/models/answer.py` 的 `Answer` 类里，`error_payload` 之后追加：

```python
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

把 `Integer` 加进该文件顶部的 `from sqlalchemy import (...)` 导入列表。在 `Answer.__table_args__` 里追加约束，让 ORM 与迁移一致：

```python
        CheckConstraint(
            "elapsed_ms IS NULL OR elapsed_ms >= 0",
            name="ck_answers_elapsed_ms_nonnegative",
        ),
```

- [ ] **Step 5: 改 Repository**

`backend/app/repositories/conversation.py` 的 `mark_answer_succeeded` 改为：

```python
    async def mark_answer_succeeded(
        self,
        answer: Answer,
        response_payload: dict[str, Any],
        *,
        elapsed_ms: int | None = None,
    ) -> None:
        answer.processing_status = "SUCCEEDED"
        answer.response_payload = response_payload
        answer.error_payload = None
        answer.elapsed_ms = elapsed_ms
        await self._session.flush()
```

`elapsed_ms` 给默认值，`backend/app/services/report_service.py:126` 的既有调用不用改——日报是确定性物化、不经过 Agent，没有「思考时长」这个概念，让它保持 `None` 是正确语义。

- [ ] **Step 6: 在 ChatService 里计时**

`backend/app/services/chat_service.py`。文件顶部导入：

```python
from time import monotonic
```

在**调用 Agent 之前**（不是函数最开头，避免把幂等查重和会话装配算进「思考时长」）插入：

```python
            started_at = monotonic()
```

在 `chat_service.py:234` 的 `mark_answer_succeeded` 调用处补参数：

```python
            await self._conversations.mark_answer_succeeded(
                answer,
                response_payload,
                elapsed_ms=int((monotonic() - started_at) * 1000),
            )
```

用 `monotonic()` 而不是 `datetime.now()`：系统时钟回拨会让墙钟差变成负数，`monotonic` 不会。

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend; uv run pytest tests/unit/services/test_chat_service.py -v`
Expected: PASS，包含新增用例

- [ ] **Step 8: 跑迁移并确认单 head**

```powershell
cd backend
uv run alembic upgrade head
uv run alembic heads
```

Expected: `alembic heads` 只输出一个 head，且是 `20260823_0013`

- [ ] **Step 9: 全量回归**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest -q
uv run ruff check .
uv run mypy .
```

Expected: 全绿，无新增 skip

- [ ] **Step 10: 提交（需用户授权，见 R2）**

```bash
git add backend/migrations/versions/20260823_0013_answer_elapsed_ms.py backend/app/models/answer.py backend/app/repositories/conversation.py backend/app/services/chat_service.py backend/tests/unit/services/test_chat_service.py
git commit -m "feat: 记录每轮回答耗时，为 Chat BI 思考时长指标补齐事实"
```

---

## Task 2: `chatbi_qa_daily` 汇总表

**Files:**
- Create: `backend/migrations/versions/20260823_0014_create_chatbi_qa_daily.py`
- Create: `backend/app/models/chatbi.py`
- Modify: `backend/app/db/base.py`
- Test: `backend/tests/integration/test_chatbi_qa_daily_schema.py`

**Interfaces:**
- Consumes: Task 1 的迁移 head `20260823_0013`
- Produces: ORM 类 `ChatBiQaDaily`，字段名见 Step 4。后续所有 Task 都按这些名字读写：
  `stat_date` / `merchant_id` / `category` / `answer_total` / `adopted_count` / `like_count` /
  `dislike_count` / `first_pass_count` / `business_question_total` / `hit_count` /
  `degraded_count` / `thinking_sample_count` / `thinking_ms_sum`

- [ ] **Step 1: 写失败的集成测试**

集成测试的 PostgreSQL session fixture 叫 **`db_session: AsyncSession`**（见 `backend/tests/integration/repositories/test_answer_history.py`），商家由用例自己插入、没有现成的商家 fixture。照这个约定创建 `backend/tests/integration/test_chatbi_qa_daily_schema.py`：

```python
"""chatbi_qa_daily 的表结构与唯一约束。"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000031")


async def _insert_merchant(session: AsyncSession) -> None:
    session.add(
        Merchant(
            id=MERCHANT_ID,
            merchant_code="chatbi-schema-merchant",
            display_name="Chat BI 结构测试商家",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_unique_grain_rejects_duplicate(db_session: AsyncSession) -> None:
    """同一 (日期, 商家, 分类) 只能有一行，重复写入必须被唯一约束拦下。"""
    await _insert_merchant(db_session)
    insert_sql = text(
        "INSERT INTO chatbi_qa_daily "
        "(id, stat_date, merchant_id, category, answer_total) "
        "VALUES (gen_random_uuid(), DATE '2026-08-20', :mid, 'TRADE', 1)"
    )
    await db_session.execute(insert_sql, {"mid": MERCHANT_ID})
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(insert_sql, {"mid": MERCHANT_ID})
        await db_session.flush()


@pytest.mark.asyncio
async def test_counter_rejects_negative(db_session: AsyncSession) -> None:
    """计数列不允许为负，避免错误的 rollup 静默写入脏数据。"""
    await _insert_merchant(db_session)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO chatbi_qa_daily "
                "(id, stat_date, merchant_id, category, answer_total) "
                "VALUES (gen_random_uuid(), DATE '2026-08-21', :mid, 'TRADE', -1)"
            ),
            {"mid": MERCHANT_ID},
        )
        await db_session.flush()
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd backend; $env:REQUIRE_INTEGRATION_DB="1"; uv run pytest tests/integration/test_chatbi_qa_daily_schema.py -v`
Expected: FAIL，`relation "chatbi_qa_daily" does not exist`

- [ ] **Step 3: 写迁移**

创建 `backend/migrations/versions/20260823_0014_create_chatbi_qa_daily.py`：

```python
"""Create the Chat BI daily rollup table.

Revision ID: 20260823_0014
Revises: 20260823_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0014"
down_revision: str | Sequence[str] | None = "20260823_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COUNTER_COLUMNS = (
    "answer_total",
    "adopted_count",
    "like_count",
    "dislike_count",
    "first_pass_count",
    "business_question_total",
    "hit_count",
    "degraded_count",
    "thinking_sample_count",
)


def upgrade() -> None:
    op.create_table(
        "chatbi_qa_daily",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        *(
            sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False)
            for name in _COUNTER_COLUMNS
        ),
        sa.Column("thinking_ms_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stat_date", "merchant_id", "category", name="uq_chatbi_qa_daily_grain"
        ),
        *(
            sa.CheckConstraint(f"{name} >= 0", name=f"ck_chatbi_qa_daily_{name}_nonnegative")
            for name in _COUNTER_COLUMNS
        ),
        sa.CheckConstraint(
            "thinking_ms_sum >= 0", name="ck_chatbi_qa_daily_thinking_ms_sum_nonnegative"
        ),
    )
    op.create_index("ix_chatbi_qa_daily_stat_date", "chatbi_qa_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_index("ix_chatbi_qa_daily_stat_date", table_name="chatbi_qa_daily")
    op.drop_table("chatbi_qa_daily")
```

**没有比率列**，理由见 §0.2。`thinking_ms_sum` 用 `BigInteger`：毫秒和累积起来会超 `Integer` 上限。

- [ ] **Step 4: 写 ORM**

创建 `backend/app/models/chatbi.py`：

```python
"""Chat BI 日粒度汇总 ORM。只存可加计数，比率由应用层计算。"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin

COUNTER_COLUMNS = (
    "answer_total",
    "adopted_count",
    "like_count",
    "dislike_count",
    "first_pass_count",
    "business_question_total",
    "hit_count",
    "degraded_count",
    "thinking_sample_count",
)


class ChatBiQaDaily(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """(日期 × 商家 × 问题分类) 的问答计数。

    刻意不存「全平台」「全分类」汇总行：PostgreSQL 里 NULL != NULL，用 NULL 当
    「全部」的哨兵会让唯一约束失效并允许写进重复汇总行。上卷交给查询时的 SUM。

    也刻意不存比率：比率不可加，三天的采纳率不是三个日采纳率的平均。
    """

    __tablename__ = "chatbi_qa_daily"
    __table_args__ = (
        UniqueConstraint("stat_date", "merchant_id", "category", name="uq_chatbi_qa_daily_grain"),
        Index("ix_chatbi_qa_daily_stat_date", "stat_date"),
        *(
            CheckConstraint(f"{name} >= 0", name=f"ck_chatbi_qa_daily_{name}_nonnegative")
            for name in COUNTER_COLUMNS
        ),
        CheckConstraint(
            "thinking_ms_sum >= 0", name="ck_chatbi_qa_daily_thinking_ms_sum_nonnegative"
        ),
    )

    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)

    answer_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    adopted_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    dislike_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    first_pass_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    business_question_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    degraded_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    thinking_sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    thinking_ms_sum: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
```

- [ ] **Step 5: 让 Alembic 发现新模型**

在 `backend/app/db/base.py` 的模型导入区追加（照抄该文件既有的导入写法）：

```python
from app.models.chatbi import ChatBiQaDaily  # noqa: F401
```

- [ ] **Step 6: 跑迁移和测试确认通过**

```powershell
cd backend
uv run alembic upgrade head
uv run alembic heads
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest tests/integration/test_chatbi_qa_daily_schema.py -v
```

Expected: `alembic heads` 只有 `20260823_0014` 一个；两条测试 PASS

- [ ] **Step 7: 确认 ORM 与迁移无漂移**

```powershell
cd backend
uv run alembic check
```

Expected: 无待生成的差异。若报告有差异，说明 ORM 和迁移的列定义没对齐，修到一致为止。

- [ ] **Step 8: 提交（需用户授权）**

```bash
git add backend/migrations/versions/20260823_0014_create_chatbi_qa_daily.py backend/app/models/chatbi.py backend/app/db/base.py backend/tests/integration/test_chatbi_qa_daily_schema.py
git commit -m "feat: 建立 Chat BI 日粒度汇总表"
```

---

## Task 3: 计数 → 比率的纯函数

把比率计算单独隔离成不碰数据库的纯函数。这样「分母为 0 返回 null」「比率不可加所以先合并计数再相除」这两条最容易写错的规则，可以用毫秒级的纯单测钉死，不需要 PostgreSQL。

**Files:**
- Create: `backend/app/analytics/chatbi_metrics.py`
- Test: `backend/tests/unit/analytics/test_chatbi_metrics.py`

**Interfaces:**
- Consumes: Task 2 的列名（作为 `QaCounters` 的字段名，一一对应）
- Produces:
  - `QaCounters` 冻结 dataclass，字段与 `chatbi_qa_daily` 计数列同名
  - `QaCounters.merge(other: QaCounters) -> QaCounters`
  - `QaCounters.zero() -> QaCounters`（类方法）
  - `NorthStarMetrics` 冻结 dataclass，字段：`adoption_rate` / `user_accuracy_rate` / `system_accuracy_rate` / `avg_thinking_ms` / `hit_rate` / `failure_rate`，全部 `float | None`
  - `compute_north_star(counters: QaCounters) -> NorthStarMetrics`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/unit/analytics/test_chatbi_metrics.py`：

```python
"""Chat BI 北极星指标的计算口径。"""

from __future__ import annotations

import pytest

from app.analytics.chatbi_metrics import QaCounters, compute_north_star


def _counters(**overrides: int) -> QaCounters:
    base = dict(
        answer_total=100,
        adopted_count=40,
        like_count=30,
        dislike_count=10,
        first_pass_count=80,
        business_question_total=90,
        hit_count=72,
        degraded_count=5,
        thinking_sample_count=100,
        thinking_ms_sum=250_000,
    )
    base.update(overrides)
    return QaCounters(**base)


def test_computes_all_six_rates() -> None:
    metrics = compute_north_star(_counters())

    assert metrics.adoption_rate == pytest.approx(0.40)
    assert metrics.user_accuracy_rate == pytest.approx(0.75)
    assert metrics.system_accuracy_rate == pytest.approx(0.80)
    assert metrics.hit_rate == pytest.approx(0.80)
    assert metrics.failure_rate == pytest.approx(0.05)
    assert metrics.avg_thinking_ms == pytest.approx(2500.0)


def test_zero_denominator_returns_none_not_zero() -> None:
    """R7：没有样本和 0% 是完全不同的结论，不得混为一谈。"""
    metrics = compute_north_star(QaCounters.zero())

    assert metrics.adoption_rate is None
    assert metrics.user_accuracy_rate is None
    assert metrics.system_accuracy_rate is None
    assert metrics.hit_rate is None
    assert metrics.failure_rate is None
    assert metrics.avg_thinking_ms is None


def test_user_accuracy_denominator_is_like_plus_dislike_only() -> None:
    """没人点赞点踩时，用户侧准确率是 null，而不是被 answer_total 稀释成 0。"""
    metrics = compute_north_star(_counters(like_count=0, dislike_count=0))

    assert metrics.user_accuracy_rate is None
    assert metrics.adoption_rate == pytest.approx(0.40)


def test_thinking_average_ignores_answers_without_elapsed() -> None:
    """历史回答没有耗时，不能把它们当成 0 毫秒拉低平均值。"""
    metrics = compute_north_star(
        _counters(thinking_sample_count=50, thinking_ms_sum=250_000)
    )

    assert metrics.avg_thinking_ms == pytest.approx(5000.0)


def test_merge_sums_counters_then_divides() -> None:
    """比率不可加：两天合并的采纳率必须是 (40+0)/(100+100)，不是 (0.4+0.0)/2。"""
    day_one = _counters()
    day_two = _counters(adopted_count=0)

    merged = day_one.merge(day_two)

    assert merged.answer_total == 200
    assert merged.adopted_count == 40
    assert compute_north_star(merged).adoption_rate == pytest.approx(0.20)
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd backend; uv run pytest tests/unit/analytics/test_chatbi_metrics.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.analytics.chatbi_metrics'`

- [ ] **Step 3: 写实现**

创建 `backend/app/analytics/chatbi_metrics.py`：

```python
"""Chat BI 北极星指标：从可加计数推导不可加比率。

这里刻意不碰数据库。比率的全部口径规则集中在本模块，用纯单测钉死，
数据库层只负责把计数取对。
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class QaCounters:
    """窗口内的可加计数。字段与 ``chatbi_qa_daily`` 的计数列一一同名。"""

    answer_total: int
    adopted_count: int
    like_count: int
    dislike_count: int
    first_pass_count: int
    business_question_total: int
    hit_count: int
    degraded_count: int
    thinking_sample_count: int
    thinking_ms_sum: int

    @classmethod
    def zero(cls) -> QaCounters:
        return cls(**{field.name: 0 for field in fields(cls)})

    def merge(self, other: QaCounters) -> QaCounters:
        """逐字段相加。上卷永远是「先合并计数」，绝不是「平均比率」。"""
        return replace(
            self,
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            },
        )


@dataclass(frozen=True)
class NorthStarMetrics:
    """六项对外指标。``None`` 表示样本不足，**不是** 0。"""

    adoption_rate: float | None
    user_accuracy_rate: float | None
    system_accuracy_rate: float | None
    avg_thinking_ms: float | None
    hit_rate: float | None
    failure_rate: float | None


def _ratio(numerator: int, denominator: int) -> float | None:
    """分母为 0 时返回 None。

    返回 0.0 会让看板把「这段时间没人提问」显示成「采纳率 0%」，
    那是两个完全不同的结论（R7）。
    """
    if denominator <= 0:
        return None
    return numerator / denominator


def compute_north_star(counters: QaCounters) -> NorthStarMetrics:
    return NorthStarMetrics(
        adoption_rate=_ratio(counters.adopted_count, counters.answer_total),
        user_accuracy_rate=_ratio(
            counters.like_count, counters.like_count + counters.dislike_count
        ),
        system_accuracy_rate=_ratio(counters.first_pass_count, counters.answer_total),
        avg_thinking_ms=_ratio(counters.thinking_ms_sum, counters.thinking_sample_count),
        hit_rate=_ratio(counters.hit_count, counters.business_question_total),
        failure_rate=_ratio(counters.degraded_count, counters.answer_total),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend; uv run pytest tests/unit/analytics/test_chatbi_metrics.py -v`
Expected: 6 passed

- [ ] **Step 5: 静态检查**

```powershell
cd backend
uv run ruff check .
uv run mypy .
```

Expected: 全绿

- [ ] **Step 6: 提交（需用户授权）**

```bash
git add backend/app/analytics/chatbi_metrics.py backend/tests/unit/analytics/test_chatbi_metrics.py
git commit -m "feat: 实现 Chat BI 北极星指标的计数到比率换算"
```

---

## Task 4: Rollup 仓储与幂等物化 Job

**Files:**
- Create: `backend/app/repositories/chatbi.py`
- Create: `backend/app/jobs/chatbi_rollup.py`
- Test: `backend/tests/integration/repositories/test_chatbi_rollup.py`

**Interfaces:**
- Consumes: `ChatBiQaDaily`（Task 2）、`QaCounters`（Task 3）
- Produces:
  - `ChatBiRepository(database: Database)`
  - `ChatBiRepository.rollup_range(*, start_date: date, end_date: date) -> int`（返回写入行数）
  - `ChatBiRepository.load_daily(*, start_date: date, end_date: date) -> list[DailyRow]`
  - `DailyRow` 冻结 dataclass：`stat_date: date`、`merchant_id: UUID`、`category: str`、`counters: QaCounters`
  - `run_rollup(settings, *, start_date, end_date) -> int`（Job 入口）

- [ ] **Step 1: 写失败的集成测试**

创建 `backend/tests/integration/repositories/test_chatbi_rollup.py`。用真实 session fixture `db_session`，商家和明细都由用例自己插入（与 `test_answer_history.py` 同款）：

```python
"""Rollup 的正确性与幂等性。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation
from app.models.merchant import Merchant
from app.repositories.chatbi import ChatBiRepository

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000041")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000042")
STAT_DAY = date(2026, 8, 20)
# 12:00 本地时间，确保按 Asia/Shanghai 归日后仍落在 STAT_DAY，不受 UTC 偏移影响。
CREATED_AT = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
SUCCEEDED_COUNT = 3


def _payload(answer_mode: str, quality_status: str, sources: list[str]) -> dict[str, object]:
    return {
        "answer_mode": answer_mode,
        "category": "TRADE",
        "quality_status": quality_status,
        "quality_attempts": 1,
        "analysis_sources": sources,
        "degraded": False,
    }


async def _seed(session: AsyncSession) -> None:
    session.add(
        Merchant(
            id=MERCHANT_ID,
            merchant_code="chatbi-rollup-merchant",
            display_name="Chat BI 汇总测试商家",
        )
    )
    session.add(Conversation(id=CONVERSATION_ID, merchant_id=MERCHANT_ID, title="汇总测试"))
    await session.flush()

    specs = [
        ("METRIC", "PASSED", ["DATABASE"], True, "LIKE", 1200),
        ("RULE", "PASSED", ["KNOWLEDGE"], False, "DISLIKE", 800),
        ("CHAT", "NOT_RUN", ["NONE"], False, None, 400),
    ]
    for index, (mode, status, sources, adopted, reaction, elapsed) in enumerate(specs):
        answer = Answer(
            id=uuid4(),
            merchant_id=MERCHANT_ID,
            conversation_id=CONVERSATION_ID,
            client_request_id=f"rollup-{index}",
            request_digest=f"digest-{index}",
            processing_status="SUCCEEDED",
            response_payload=_payload(mode, status, sources),
            elapsed_ms=elapsed,
            created_at=CREATED_AT,
        )
        session.add(answer)
        await session.flush()
        session.add(
            Feedback(
                id=uuid4(),
                merchant_id=MERCHANT_ID,
                answer_id=answer.id,
                is_adopted=adopted,
                reaction=reaction,
            )
        )
    await session.commit()


@pytest.fixture
def chatbi_repository(test_database: Database) -> ChatBiRepository:
    return ChatBiRepository(test_database)


@pytest.mark.asyncio
async def test_rollup_counts_match_source(
    db_session: AsyncSession, chatbi_repository: ChatBiRepository
) -> None:
    """汇总表的计数必须与明细一致，且 CHAT 不进业务提问分母。"""
    await _seed(db_session)

    await chatbi_repository.rollup_range(start_date=STAT_DAY, end_date=STAT_DAY)
    rows = await chatbi_repository.load_daily(start_date=STAT_DAY, end_date=STAT_DAY)

    assert sum(row.counters.answer_total for row in rows) == SUCCEEDED_COUNT
    assert sum(row.counters.business_question_total for row in rows) == 2
    assert sum(row.counters.hit_count for row in rows) == 2
    assert sum(row.counters.adopted_count for row in rows) == 1
    assert sum(row.counters.like_count for row in rows) == 1
    assert sum(row.counters.dislike_count for row in rows) == 1
    assert sum(row.counters.thinking_ms_sum for row in rows) == 2400


@pytest.mark.asyncio
async def test_rollup_is_idempotent(
    db_session: AsyncSession, chatbi_repository: ChatBiRepository
) -> None:
    """重跑同一天必须得到同一结果，且不产生重复行。"""
    await _seed(db_session)
    window = {"start_date": STAT_DAY, "end_date": STAT_DAY}

    await chatbi_repository.rollup_range(**window)
    first = await chatbi_repository.load_daily(**window)

    await chatbi_repository.rollup_range(**window)
    second = await chatbi_repository.load_daily(**window)

    assert len(first) == len(second)
    assert [row.counters for row in first] == [row.counters for row in second]


@pytest.mark.asyncio
async def test_rollup_excludes_unsucceeded_answers(
    db_session: AsyncSession, chatbi_repository: ChatBiRepository
) -> None:
    """PROCESSING / FAILED 的回答不进分母，否则失效率会被自己稀释。"""
    await _seed(db_session)
    await db_session.execute(
        text(
            "UPDATE answers SET processing_status = 'FAILED_FINAL' "
            "WHERE id = (SELECT id FROM answers WHERE processing_status = 'SUCCEEDED' LIMIT 1)"
        )
    )
    await db_session.commit()

    await chatbi_repository.rollup_range(start_date=STAT_DAY, end_date=STAT_DAY)
    rows = await chatbi_repository.load_daily(start_date=STAT_DAY, end_date=STAT_DAY)

    assert sum(row.counters.answer_total for row in rows) == SUCCEEDED_COUNT - 1


@pytest.mark.asyncio
async def test_rollup_removes_stale_rows(
    db_session: AsyncSession, chatbi_repository: ChatBiRepository
) -> None:
    """明细被删干净后重跑，旧汇总行必须清掉，不能留下幽灵数据。"""
    await _seed(db_session)
    window = {"start_date": STAT_DAY, "end_date": STAT_DAY}
    await chatbi_repository.rollup_range(**window)
    assert await chatbi_repository.load_daily(**window) != []

    await db_session.execute(text("DELETE FROM feedback"))
    await db_session.execute(text("DELETE FROM answers"))
    await db_session.commit()

    await chatbi_repository.rollup_range(**window)
    assert await chatbi_repository.load_daily(**window) == []
```

`test_database` 这个 `Database` 实例的 fixture 名以 `backend/tests/conftest.py` 里的实际名字为准（同文件已有 `postgres_url` / `migrated_postgres` 系列）；若不存在现成的，就在本文件里用 `postgres_url` 构造一个 `Database`，**不要改动全局 conftest**。

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd backend; $env:REQUIRE_INTEGRATION_DB="1"; uv run pytest tests/integration/test_chatbi_rollup.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.repositories.chatbi'`

- [ ] **Step 3: 写仓储**

创建 `backend/app/repositories/chatbi.py`：

```python
"""Chat BI 汇总表的写入与读取。

写入是「按窗口重算 + 覆盖」而不是「增量累加」：重算可以任意重跑，
增量累加一旦漏跑或重跑就会永久偏差且无法自愈。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Date, and_, case, cast, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert

from app.analytics.chatbi_metrics import QaCounters
from app.db.session import Database
from app.models.answer import Answer, Feedback
from app.models.chatbi import ChatBiQaDaily


@dataclass(frozen=True)
class DailyRow:
    stat_date: date
    merchant_id: UUID
    category: str
    counters: QaCounters


class ChatBiRepository:
    def __init__(self, database: Database, *, business_timezone: str = "Asia/Shanghai") -> None:
        self._database = database
        self._timezone = business_timezone

    def _stat_date(self):
        """把 created_at 按业务时区归日。

        直接对 UTC 时间戳取 date 会让 08:00 之前的问答被算到前一天，
        整张表的日粒度都会偏移。
        """
        return cast(func.timezone(self._timezone, Answer.created_at), Date)

    def _source_select(self, start_date: date, end_date: date):
        payload = Answer.response_payload
        stat_date = self._stat_date().label("stat_date")

        is_business = payload["answer_mode"].astext != literal("CHAT")
        is_hit = and_(
            payload["answer_mode"].astext.notin_(("CHAT", "INVALID")),
            payload["analysis_sources"].astext != literal('["NONE"]'),
        )
        is_first_pass = and_(
            payload["quality_status"].astext == literal("PASSED"),
            payload["quality_attempts"].astext == literal("1"),
        )
        is_failure = func.coalesce(
            payload["degraded"].astext == literal("true"), literal(False)
        ) | payload["quality_status"].astext.in_(("DEGRADED", "FAILED"))

        return (
            select(
                stat_date,
                Answer.merchant_id.label("merchant_id"),
                func.coalesce(payload["category"].astext, literal("UNKNOWN")).label("category"),
                func.count().label("answer_total"),
                func.count().filter(Feedback.is_adopted.is_(True)).label("adopted_count"),
                func.count().filter(Feedback.reaction == "LIKE").label("like_count"),
                func.count().filter(Feedback.reaction == "DISLIKE").label("dislike_count"),
                func.count().filter(is_first_pass).label("first_pass_count"),
                func.count().filter(is_business).label("business_question_total"),
                func.count().filter(is_hit).label("hit_count"),
                func.count().filter(is_failure).label("degraded_count"),
                func.count().filter(Answer.elapsed_ms.isnot(None)).label("thinking_sample_count"),
                func.coalesce(func.sum(Answer.elapsed_ms), 0).label("thinking_ms_sum"),
            )
            .select_from(Answer)
            .outerjoin(Feedback, Feedback.answer_id == Answer.id)
            .where(
                Answer.processing_status == "SUCCEEDED",
                stat_date >= start_date,
                stat_date <= end_date,
            )
            .group_by(stat_date, Answer.merchant_id, func.coalesce(payload["category"].astext, literal("UNKNOWN")))
        )

    async def rollup_range(self, *, start_date: date, end_date: date) -> int:
        """重算窗口内每一天的计数并覆盖写入。同窗口重跑结果不变。"""
        async with self._database.session() as session, session.begin():
            rows = (await session.execute(self._source_select(start_date, end_date))).all()

            # 先清空该窗口的旧汇总：明细被删或口径变化后，
            # 只 upsert 会留下不再有对应明细的幽灵行。
            await session.execute(
                delete(ChatBiQaDaily).where(
                    ChatBiQaDaily.stat_date >= start_date,
                    ChatBiQaDaily.stat_date <= end_date,
                )
            )
            if not rows:
                return 0

            await session.execute(
                insert(ChatBiQaDaily).values(
                    [
                        {
                            "id": uuid4(),
                            "stat_date": row.stat_date,
                            "merchant_id": row.merchant_id,
                            "category": row.category,
                            "answer_total": row.answer_total,
                            "adopted_count": row.adopted_count,
                            "like_count": row.like_count,
                            "dislike_count": row.dislike_count,
                            "first_pass_count": row.first_pass_count,
                            "business_question_total": row.business_question_total,
                            "hit_count": row.hit_count,
                            "degraded_count": row.degraded_count,
                            "thinking_sample_count": row.thinking_sample_count,
                            "thinking_ms_sum": row.thinking_ms_sum,
                        }
                        for row in rows
                    ]
                )
            )
            return len(rows)

    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]:
        async with self._database.session() as session:
            result = await session.execute(
                select(ChatBiQaDaily)
                .where(
                    ChatBiQaDaily.stat_date >= start_date,
                    ChatBiQaDaily.stat_date <= end_date,
                )
                .order_by(ChatBiQaDaily.stat_date, ChatBiQaDaily.category)
            )
            return [
                DailyRow(
                    stat_date=row.stat_date,
                    merchant_id=row.merchant_id,
                    category=row.category,
                    counters=QaCounters(
                        answer_total=row.answer_total,
                        adopted_count=row.adopted_count,
                        like_count=row.like_count,
                        dislike_count=row.dislike_count,
                        first_pass_count=row.first_pass_count,
                        business_question_total=row.business_question_total,
                        hit_count=row.hit_count,
                        degraded_count=row.degraded_count,
                        thinking_sample_count=row.thinking_sample_count,
                        thinking_ms_sum=row.thinking_ms_sum,
                    ),
                )
                for row in result.scalars()
            ]
```

未使用的 `case` 导入若被 Ruff 报出，删掉即可。

- [ ] **Step 4: 写 Job 与 CLI**

创建 `backend/app/jobs/chatbi_rollup.py`。CLI 形状照 `backend/app/jobs/seed_demo_rolling.py` 的 `argparse` + `asyncio.run` 写法：

```python
"""Chat BI 汇总的物化 Job。可任意重跑，用于每日调度与历史补数。"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from app.analytics.dates import business_today
from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.repositories.chatbi import ChatBiRepository

logger = logging.getLogger(__name__)
DEFAULT_WINDOW_DAYS = 7


def default_window(settings: Settings) -> tuple[date, date]:
    """默认重刷「含今天在内的最近 7 天」。

    包含今天是因为当天的问答还在持续产生；重刷昨天及更早是因为
    反馈（采纳/点赞点踩）会在回答落库之后才到达，只刷当天会永久漏掉迟到的反馈。
    """
    end = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    return end - timedelta(days=DEFAULT_WINDOW_DAYS - 1), end


async def run_rollup(settings: Settings, *, start_date: date, end_date: date) -> int:
    if start_date > end_date:
        raise ValueError("start_date 不得晚于 end_date")
    database = Database(settings)
    try:
        repository = ChatBiRepository(database, business_timezone=settings.business_timezone)
        written = await repository.rollup_range(start_date=start_date, end_date=end_date)
        logger.info(
            "chatbi rollup 完成", extra={"start_date": str(start_date), "end_date": str(end_date), "rows": written}
        )
        return written
    finally:
        await database.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="重算 Chat BI 日粒度汇总")
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    configure_event_loop_policy()
    settings = Settings()
    start, end = default_window(settings)
    asyncio.run(
        run_rollup(
            settings,
            start_date=args.start_date or start,
            end_date=args.end_date or end,
        )
    )


if __name__ == "__main__":
    main()
```

`Settings.business_timezone` 已确认存在（`backend/app/core/config.py:40`，默认 `Asia/Shanghai`），直接用，不需要新增配置项。

- [ ] **Step 5: 跑测试确认通过**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest tests/integration/test_chatbi_rollup.py -v
```

Expected: 4 passed

- [ ] **Step 6: 手工跑一次 CLI**

```powershell
cd backend
uv run python -m app.jobs.chatbi_rollup --start-date 2026-08-01 --end-date 2026-08-23
```

Expected: 正常退出，日志打出写入行数；再跑一次行数相同（幂等）

- [ ] **Step 7: 静态检查与提交（需用户授权）**

```powershell
cd backend
uv run ruff check .
uv run mypy .
```

```bash
git add backend/app/repositories/chatbi.py backend/app/jobs/chatbi_rollup.py backend/tests/integration/test_chatbi_rollup.py
git commit -m "feat: 实现 Chat BI 汇总的幂等物化"
```

---

## Task 5: ChatBiService —— 组装 overview 与 categories

**Files:**
- Create: `backend/app/services/chatbi_service.py`
- Test: `backend/tests/unit/services/test_chatbi_service.py`

**Interfaces:**
- Consumes: `ChatBiRepository.load_daily`、`DailyRow`（Task 4）；`QaCounters` / `compute_north_star`（Task 3）
- Produces:
  - `ChatBiOverview` 冻结 dataclass：`start_date` / `end_date` / `counters: QaCounters` / `metrics: NorthStarMetrics` / `daily: list[DailyPoint]`
  - `DailyPoint` 冻结 dataclass：`stat_date: date` / `answer_total: int` / `metrics: NorthStarMetrics`
  - `CategoryBreakdown` 冻结 dataclass：`category: str` / `counters: QaCounters` / `metrics: NorthStarMetrics`
  - `ChatBiService.overview(*, start_date, end_date) -> ChatBiOverview`
  - `ChatBiService.categories(*, start_date, end_date) -> list[CategoryBreakdown]`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/unit/services/test_chatbi_service.py`。用假仓储，不连数据库：

```python
"""ChatBiService 的上卷逻辑。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.analytics.chatbi_metrics import QaCounters
from app.repositories.chatbi import DailyRow
from app.services.chatbi_service import ChatBiService

MERCHANT_A = uuid4()
MERCHANT_B = uuid4()


def _counters(answer_total: int, adopted: int) -> QaCounters:
    return QaCounters(
        answer_total=answer_total,
        adopted_count=adopted,
        like_count=0,
        dislike_count=0,
        first_pass_count=answer_total,
        business_question_total=answer_total,
        hit_count=answer_total,
        degraded_count=0,
        thinking_sample_count=answer_total,
        thinking_ms_sum=answer_total * 1000,
    )


class FakeChatBiRepository:
    def __init__(self, rows: list[DailyRow]) -> None:
        self._rows = rows

    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]:
        return [row for row in self._rows if start_date <= row.stat_date <= end_date]


@pytest.mark.asyncio
async def test_overview_rolls_up_across_merchants_and_categories() -> None:
    """窗口总览必须跨商家跨分类先合并计数，再算比率。"""
    rows = [
        DailyRow(date(2026, 8, 20), MERCHANT_A, "TRADE", _counters(10, 5)),
        DailyRow(date(2026, 8, 20), MERCHANT_B, "REFUND", _counters(10, 1)),
    ]
    service = ChatBiService(FakeChatBiRepository(rows))

    overview = await service.overview(start_date=date(2026, 8, 20), end_date=date(2026, 8, 20))

    assert overview.counters.answer_total == 20
    assert overview.metrics.adoption_rate == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_overview_daily_points_are_one_per_date() -> None:
    """趋势按日聚合，同一天的多商家多分类合成一个点。"""
    rows = [
        DailyRow(date(2026, 8, 20), MERCHANT_A, "TRADE", _counters(10, 5)),
        DailyRow(date(2026, 8, 20), MERCHANT_B, "REFUND", _counters(10, 1)),
        DailyRow(date(2026, 8, 21), MERCHANT_A, "TRADE", _counters(4, 2)),
    ]
    service = ChatBiService(FakeChatBiRepository(rows))

    overview = await service.overview(start_date=date(2026, 8, 20), end_date=date(2026, 8, 21))

    assert [point.stat_date for point in overview.daily] == [date(2026, 8, 20), date(2026, 8, 21)]
    assert overview.daily[0].answer_total == 20
    assert overview.daily[1].metrics.adoption_rate == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_empty_window_returns_none_metrics_not_zero() -> None:
    """窗口内没有任何问答时，六项指标全为 None，趋势为空数组。"""
    service = ChatBiService(FakeChatBiRepository([]))

    overview = await service.overview(start_date=date(2026, 8, 20), end_date=date(2026, 8, 21))

    assert overview.counters.answer_total == 0
    assert overview.metrics.adoption_rate is None
    assert overview.daily == []


@pytest.mark.asyncio
async def test_categories_group_by_category_sorted_by_volume() -> None:
    """分类下钻按问答量降序，方便一眼看到最集中的业务域。"""
    rows = [
        DailyRow(date(2026, 8, 20), MERCHANT_A, "TRADE", _counters(3, 1)),
        DailyRow(date(2026, 8, 20), MERCHANT_B, "REFUND", _counters(9, 3)),
        DailyRow(date(2026, 8, 21), MERCHANT_A, "TRADE", _counters(2, 0)),
    ]
    service = ChatBiService(FakeChatBiRepository(rows))

    breakdown = await service.categories(
        start_date=date(2026, 8, 20), end_date=date(2026, 8, 21)
    )

    assert [item.category for item in breakdown] == ["REFUND", "TRADE"]
    assert breakdown[1].counters.answer_total == 5
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd backend; uv run pytest tests/unit/services/test_chatbi_service.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.chatbi_service'`

- [ ] **Step 3: 写实现**

创建 `backend/app/services/chatbi_service.py`：

```python
"""Chat BI 看板的应用层：把日粒度汇总上卷成窗口总览与分类下钻。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.analytics.chatbi_metrics import (
    NorthStarMetrics,
    QaCounters,
    compute_north_star,
)
from app.repositories.chatbi import DailyRow


class ChatBiRepositoryLike(Protocol):
    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]: ...


@dataclass(frozen=True)
class DailyPoint:
    stat_date: date
    answer_total: int
    metrics: NorthStarMetrics


@dataclass(frozen=True)
class ChatBiOverview:
    start_date: date
    end_date: date
    counters: QaCounters
    metrics: NorthStarMetrics
    daily: list[DailyPoint]


@dataclass(frozen=True)
class CategoryBreakdown:
    category: str
    counters: QaCounters
    metrics: NorthStarMetrics


def _merge_all(items: list[QaCounters]) -> QaCounters:
    merged = QaCounters.zero()
    for item in items:
        merged = merged.merge(item)
    return merged


class ChatBiService:
    def __init__(self, repository: ChatBiRepositoryLike) -> None:
        self._repository = repository

    async def overview(self, *, start_date: date, end_date: date) -> ChatBiOverview:
        rows = await self._repository.load_daily(start_date=start_date, end_date=end_date)

        by_date: dict[date, list[QaCounters]] = defaultdict(list)
        for row in rows:
            by_date[row.stat_date].append(row.counters)

        daily = []
        for stat_date in sorted(by_date):
            merged = _merge_all(by_date[stat_date])
            daily.append(
                DailyPoint(
                    stat_date=stat_date,
                    answer_total=merged.answer_total,
                    metrics=compute_north_star(merged),
                )
            )

        total = _merge_all([row.counters for row in rows])
        return ChatBiOverview(
            start_date=start_date,
            end_date=end_date,
            counters=total,
            metrics=compute_north_star(total),
            daily=daily,
        )

    async def categories(self, *, start_date: date, end_date: date) -> list[CategoryBreakdown]:
        rows = await self._repository.load_daily(start_date=start_date, end_date=end_date)

        by_category: dict[str, list[QaCounters]] = defaultdict(list)
        for row in rows:
            by_category[row.category].append(row.counters)

        breakdown = [
            CategoryBreakdown(
                category=category,
                counters=(merged := _merge_all(items)),
                metrics=compute_north_star(merged),
            )
            for category, items in by_category.items()
        ]
        # 量大的排前面；同量按分类名稳定排序，避免同一份数据两次请求顺序不同。
        breakdown.sort(key=lambda item: (-item.counters.answer_total, item.category))
        return breakdown
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend; uv run pytest tests/unit/services/test_chatbi_service.py -v`
Expected: 4 passed

- [ ] **Step 5: 静态检查与提交（需用户授权）**

```powershell
cd backend
uv run ruff check .
uv run mypy .
```

```bash
git add backend/app/services/chatbi_service.py backend/tests/unit/services/test_chatbi_service.py
git commit -m "feat: 实现 Chat BI 看板的窗口上卷与分类下钻"
```

---

## Task 6: 三个管理员端点

**Files:**
- Create: `backend/app/schemas/analytics.py`
- Create: `backend/app/api/routes/analytics.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/api/test_chatbi_analytics.py`

**Interfaces:**
- Consumes: `ChatBiService`（Task 5）、`ChatBiRepository`（Task 4）、`require_admin_token`（既有 `app/api/dependencies.py:119`）
- Produces: HTTP 契约
  - `GET /api/admin/analytics/chatbi/overview?start_date=&end_date=` → `ChatBiOverviewResponse`
  - `GET /api/admin/analytics/chatbi/categories?start_date=&end_date=` → `ChatBiCategoriesResponse`
  - `POST /api/admin/analytics/chatbi/rollup` → `ChatBiRollupResponse`

- [ ] **Step 1: 写失败的 API 测试**

创建 `backend/tests/api/test_chatbi_analytics.py`。装配照抄 `backend/tests/api/test_admin_ops.py`（同为 `X-Admin-Token` 端点）：**该文件在用例内自建 app**，用 `Settings(app_env=AppEnvironment.TEST, admin_token=...)` + `AsyncClient(transport=ASGITransport(app))`，并从 `tests.conftest` 取 `MERCHANT_ONE_TOKEN`。下面的 `admin_client` / `admin_headers` / `merchant_token` 请按同款方式在本文件里定义为 fixture，**不要往全局 conftest 加**：

```python
"""Chat BI 管理员端点的鉴权与契约。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app
from tests.conftest import MERCHANT_ONE_TOKEN

ADMIN_TOKEN = "test-only-admin-token-value"
OVERVIEW = "/api/admin/analytics/chatbi/overview"
CATEGORIES = "/api/admin/analytics/chatbi/categories"
ROLLUP = "/api/admin/analytics/chatbi/rollup"
WINDOW = {"start_date": "2026-08-17", "end_date": "2026-08-23"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture
def merchant_token() -> str:
    return MERCHANT_ONE_TOKEN


@pytest_asyncio.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
    )
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_overview_requires_admin_token(admin_client: AsyncClient) -> None:
    response = await admin_client.get(OVERVIEW, params=WINDOW)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_overview_rejects_merchant_authorization_header(
    admin_client: AsyncClient, merchant_token: str
) -> None:
    """管理员端点不认 Authorization，商家令牌不得越权进管理接口。"""
    response = await admin_client.get(
        OVERVIEW, params=WINDOW, headers={"Authorization": f"Bearer {merchant_token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_overview_returns_all_six_metrics(admin_client, admin_headers) -> None:
    response = await admin_client.get(OVERVIEW, params=WINDOW, headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    for key in (
        "adoption_rate",
        "user_accuracy_rate",
        "system_accuracy_rate",
        "avg_thinking_ms",
        "hit_rate",
        "failure_rate",
    ):
        assert key in payload, f"缺少指标字段 {key}"
    assert "daily" in payload
    assert "answer_total" in payload


@pytest.mark.asyncio
async def test_overview_rejects_reversed_window(admin_client, admin_headers) -> None:
    response = await admin_client.get(
        OVERVIEW,
        params={"start_date": "2026-08-23", "end_date": "2026-08-17"},
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_overview_rejects_oversized_window(admin_client, admin_headers) -> None:
    """窗口上限 180 天，避免一次请求扫穿整张表。"""
    response = await admin_client.get(
        OVERVIEW,
        params={"start_date": "2025-08-23", "end_date": "2026-08-23"},
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_categories_requires_admin_token(admin_client) -> None:
    response = await admin_client.get(CATEGORIES, params=WINDOW)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rollup_requires_admin_token(admin_client) -> None:
    response = await admin_client.post(ROLLUP, json=WINDOW)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rollup_returns_written_rows(admin_client, admin_headers) -> None:
    response = await admin_client.post(ROLLUP, json=WINDOW, headers=admin_headers)

    assert response.status_code == 200
    assert "rows_written" in response.json()


@pytest.mark.asyncio
async def test_response_contains_no_merchant_identifiers(admin_client, admin_headers) -> None:
    """看板是全平台聚合视图，响应里不得出现任何商家标识或问题原文。"""
    response = await admin_client.get(OVERVIEW, params=WINDOW, headers=admin_headers)

    body = response.text
    assert "merchant_id" not in body
    assert "question" not in body
```

三条会真正落到数据层的用例（`..._returns_all_six_metrics`、`..._rollup_returns_written_rows`、`..._contains_no_merchant_identifiers`）需要可用的数据源。照 `test_admin_ops.py` 的做法用 `monkeypatch.setattr("app.api.routes.analytics.ChatBiRepository", FakeChatBiRepository)` 注入一个返回固定 `DailyRow` 列表的假仓储，**不要让 API 层测试依赖真实 PostgreSQL**——真实数据库的覆盖已经由 Task 4 的集成测试承担。

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd backend; uv run pytest tests/api/test_chatbi_analytics.py -v`
Expected: 全部 FAIL，404（路由不存在）

- [ ] **Step 3: 写 Schema**

创建 `backend/app/schemas/analytics.py`：

```python
"""Chat BI 看板的 API 契约。

比率一律 ``float | None``：``null`` 表示样本不足，前端必须显示「样本不足」
而不是 0%（R7）。
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

MAX_WINDOW_DAYS = 180


class ChatBiWindow(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_window(self) -> ChatBiWindow:
        if self.start_date > self.end_date:
            raise ValueError("start_date 不得晚于 end_date")
        if (self.end_date - self.start_date).days + 1 > MAX_WINDOW_DAYS:
            raise ValueError(f"查询窗口不得超过 {MAX_WINDOW_DAYS} 天")
        return self


class NorthStarPayload(BaseModel):
    """六项北极星指标。``None`` 表示样本不足。"""

    adoption_rate: float | None
    user_accuracy_rate: float | None
    system_accuracy_rate: float | None
    avg_thinking_ms: float | None
    hit_rate: float | None
    failure_rate: float | None


class ChatBiDailyPoint(NorthStarPayload):
    stat_date: date
    answer_total: int = Field(ge=0)


class ChatBiOverviewResponse(NorthStarPayload):
    """扁平 snake_case，与项目其余契约保持同一形状。"""

    start_date: date
    end_date: date
    answer_total: int = Field(ge=0)
    business_question_total: int = Field(ge=0)
    feedback_total: int = Field(ge=0)
    thinking_sample_count: int = Field(ge=0)
    daily: list[ChatBiDailyPoint] = Field(default_factory=list)


class ChatBiCategoryItem(NorthStarPayload):
    category: str
    category_display_name: str
    answer_total: int = Field(ge=0)


class ChatBiCategoriesResponse(BaseModel):
    start_date: date
    end_date: date
    items: list[ChatBiCategoryItem] = Field(default_factory=list)


class ChatBiRollupResponse(BaseModel):
    start_date: date
    end_date: date
    rows_written: int = Field(ge=0)
```

`category_display_name` 复用 `backend/app/schemas/chat.py:96` 的 `CATEGORY_DISPLAY_NAMES`，不要另写一份。

- [ ] **Step 4: 写路由**

创建 `backend/app/api/routes/analytics.py`：

```python
"""Chat BI 看板端点：全平台聚合，仅限管理员令牌访问。

响应刻意不含 merchant_id、问题原文和回答正文——看板衡量的是整体质量，
不是查看具体商家的经营内容。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_app_settings, get_database, require_admin_token
from app.core.config import Settings
from app.core.errors import error_responses
from app.db.session import Database
from app.repositories.chatbi import ChatBiRepository
from app.schemas.analytics import (
    ChatBiCategoriesResponse,
    ChatBiCategoryItem,
    ChatBiDailyPoint,
    ChatBiOverviewResponse,
    ChatBiRollupResponse,
    ChatBiWindow,
)
from app.schemas.chat import CATEGORY_DISPLAY_NAMES, QuestionCategory
from app.services.chatbi_service import ChatBiService

router = APIRouter(prefix="/admin/analytics/chatbi", tags=["admin"])


def _service(settings: Settings, database: Database) -> ChatBiService:
    return ChatBiService(
        ChatBiRepository(database, business_timezone=settings.business_timezone)
    )


@router.get(
    "/overview",
    response_model=ChatBiOverviewResponse,
    responses=error_responses(401, 403, 422),
)
async def chatbi_overview(
    window: Annotated[ChatBiWindow, Query()],
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> ChatBiOverviewResponse:
    overview = await _service(settings, database).overview(
        start_date=window.start_date, end_date=window.end_date
    )
    counters = overview.counters
    metrics = overview.metrics
    return ChatBiOverviewResponse(
        start_date=overview.start_date,
        end_date=overview.end_date,
        answer_total=counters.answer_total,
        business_question_total=counters.business_question_total,
        feedback_total=counters.like_count + counters.dislike_count,
        thinking_sample_count=counters.thinking_sample_count,
        adoption_rate=metrics.adoption_rate,
        user_accuracy_rate=metrics.user_accuracy_rate,
        system_accuracy_rate=metrics.system_accuracy_rate,
        avg_thinking_ms=metrics.avg_thinking_ms,
        hit_rate=metrics.hit_rate,
        failure_rate=metrics.failure_rate,
        daily=[
            ChatBiDailyPoint(
                stat_date=point.stat_date,
                answer_total=point.answer_total,
                adoption_rate=point.metrics.adoption_rate,
                user_accuracy_rate=point.metrics.user_accuracy_rate,
                system_accuracy_rate=point.metrics.system_accuracy_rate,
                avg_thinking_ms=point.metrics.avg_thinking_ms,
                hit_rate=point.metrics.hit_rate,
                failure_rate=point.metrics.failure_rate,
            )
            for point in overview.daily
        ],
    )


@router.get(
    "/categories",
    response_model=ChatBiCategoriesResponse,
    responses=error_responses(401, 403, 422),
)
async def chatbi_categories(
    window: Annotated[ChatBiWindow, Query()],
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> ChatBiCategoriesResponse:
    breakdown = await _service(settings, database).categories(
        start_date=window.start_date, end_date=window.end_date
    )
    return ChatBiCategoriesResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        items=[
            ChatBiCategoryItem(
                category=item.category,
                category_display_name=_display_name(item.category),
                answer_total=item.counters.answer_total,
                adoption_rate=item.metrics.adoption_rate,
                user_accuracy_rate=item.metrics.user_accuracy_rate,
                system_accuracy_rate=item.metrics.system_accuracy_rate,
                avg_thinking_ms=item.metrics.avg_thinking_ms,
                hit_rate=item.metrics.hit_rate,
                failure_rate=item.metrics.failure_rate,
            )
            for item in breakdown
        ],
    )


@router.post(
    "/rollup",
    response_model=ChatBiRollupResponse,
    responses=error_responses(401, 403, 422),
)
async def chatbi_rollup(
    window: ChatBiWindow,
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> ChatBiRollupResponse:
    """手动重刷汇总。幂等，可任意重跑，用于演示与历史补数。"""
    repository = ChatBiRepository(database, business_timezone=settings.business_timezone)
    rows = await repository.rollup_range(
        start_date=window.start_date, end_date=window.end_date
    )
    return ChatBiRollupResponse(
        start_date=window.start_date, end_date=window.end_date, rows_written=rows
    )


def _display_name(category: str) -> str:
    try:
        return CATEGORY_DISPLAY_NAMES[QuestionCategory(category)]
    except (KeyError, ValueError):
        return category
```

`CATEGORY_DISPLAY_NAMES` 已确认存在于 `backend/app/schemas/chat.py:96`，直接导入使用，不要另写一份中文映射。

- [ ] **Step 5: 注册路由**

在 `backend/app/api/router.py` 里按既有写法追加：

```python
from app.api.routes import analytics

...
api_router.include_router(analytics.router)
```

注意 `admin.py` 的 `/api/admin/ops/status` 在未配置 `ADMIN_TOKEN` 时整体不挂载路由。**analytics 路由沿用同一策略**：读 `router.py` 里 admin 路由的挂载条件，照抄，不要让未配置令牌的部署裸奔一个管理端点。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend; uv run pytest tests/api/test_chatbi_analytics.py -v`
Expected: 9 passed

- [ ] **Step 7: 全量后端回归**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest -q
uv run ruff check .
uv run mypy .
```

Expected: 全绿

- [ ] **Step 8: 提交（需用户授权）**

```bash
git add backend/app/schemas/analytics.py backend/app/api/routes/analytics.py backend/app/api/router.py backend/tests/api/test_chatbi_analytics.py
git commit -m "feat: 交付 Chat BI 看板的三个管理员端点"
```

---

## Task 7: 契约同步 —— 文档、OpenAPI、前端类型

新增了接口路径，必须按项目既定顺序把六处同步到位，否则 `codegen:check` 和契约测试会在后续 Task 里炸掉。

**Files:**
- Modify: `docs/PRD.md` §11
- Modify: `docs/backend-development-plan.md` §8
- Modify: `AGENTS.md` §10.2、§8.2 文件索引、§8.4 文件索引
- Regenerate: `docs/api.json`、`docs/api.md`
- Regenerate: `frontend/src/api/generated.ts`
- Test: `backend/tests/api/test_openapi_chat_contract.py`（追加路径断言）

**Interfaces:**
- Consumes: Task 6 的三个路径与响应模型
- Produces: `frontend/src/api/generated.ts` 中的 `components['schemas']['ChatBiOverviewResponse']`、`['ChatBiCategoriesResponse']`、`['ChatBiRollupResponse']`

- [ ] **Step 1: 先改 PRD**

在 `docs/PRD.md` §11 的 P1 接口清单里追加三行，并注明凭证为 `X-Admin-Token`：

```text
GET    /api/admin/analytics/chatbi/overview
GET    /api/admin/analytics/chatbi/categories
POST   /api/admin/analytics/chatbi/rollup
```

同时在 PRD 里补一小节说明双口径准确率的理由（照抄本计划 §0.1 的那段），避免以后有人把两个准确率合并成一个。

- [ ] **Step 2: 改后端开发计划 §8**

在 `docs/backend-development-plan.md` §8 追加这三个端点的字段契约，字段清单直接引用 `app/schemas/analytics.py`，并写明「比率为 `null` 表示样本不足，前端必须区分于 0」。

- [ ] **Step 3: 改 AGENTS.md**

- §10.2 P1 接口清单追加三条路径
- §10.2.1 的凭证表无需改（已覆盖 `X-Admin-Token`）
- §8.2 API 路由索引追加 `backend/app/api/routes/analytics.py`
- §8.4 业务服务索引追加 `backend/app/services/chatbi_service.py` 与 `backend/app/jobs/chatbi_rollup.py`
- §9.1 核心表清单追加 `[P1] chatbi_qa_daily`

- [ ] **Step 4: 重新导出 OpenAPI**

```powershell
cd backend
uv run python ../scripts/export_openapi.py
```

若该脚本的实际调用方式不同，照 `AGENTS.md` 里记载的方式执行（`docs/api.md` 由 `scripts/export_openapi.py` 从 FastAPI 自动导出）。

Expected: `docs/api.json` 与 `docs/api.md` 出现三个新路径

- [ ] **Step 5: 重新生成前端类型**

```powershell
cd frontend
npm run codegen
npm run codegen:check
```

Expected: `codegen:check` 通过，`generated.ts` 里出现三个新 schema

- [ ] **Step 6: 补契约测试的路径断言**

在 `backend/tests/api/test_openapi_chat_contract.py` 的路径断言里追加三条新路径为**必须存在**。该文件已有「永久禁止暴露某些路径」的断言，不要动那部分。

```python
def test_openapi_exposes_chatbi_analytics_paths(openapi_schema) -> None:
    """看板端点是 P1 契约的一部分，不得被误删。"""
    for path in (
        "/api/admin/analytics/chatbi/overview",
        "/api/admin/analytics/chatbi/categories",
        "/api/admin/analytics/chatbi/rollup",
    ):
        assert path in openapi_schema["paths"], f"OpenAPI 缺少 {path}"
```

- [ ] **Step 7: 跑测试确认通过**

```powershell
cd backend
uv run pytest tests/api/test_openapi_chat_contract.py -v
```

Expected: PASS

- [ ] **Step 8: 提交（需用户授权）**

```bash
git add docs/PRD.md docs/backend-development-plan.md docs/api.json docs/api.md AGENTS.md frontend/src/api/generated.ts backend/tests/api/test_openapi_chat_contract.py
git commit -m "docs: 同步 Chat BI 看板端点的产品、契约与生成类型"
```

---

## Task 8: 前端 API 层、Adapter 与 Store

**Files:**
- Create: `frontend/src/types/analytics.ts`
- Create: `frontend/src/api/adapters/analytics.ts`
- Create: `frontend/src/api/analytics.ts`
- Create: `frontend/src/stores/analytics.ts`
- Test: `frontend/src/api/adapters/analytics.spec.ts`
- Test: `frontend/src/stores/analytics.spec.ts`

**Interfaces:**
- Consumes: Task 7 的 `generated.ts` schema
- Produces:
  - `types/analytics.ts`：`NorthStarMetrics`（六个 `number | null`）、`ChatBiOverview`、`ChatBiDailyPoint`、`ChatBiCategoryRow`
  - `api/analytics.ts`：`getChatBiOverview(window, signal)`、`getChatBiCategories(window, signal)`、`triggerChatBiRollup(window, signal)`
  - `stores/analytics.ts`：`useAnalyticsStore()`，暴露 `overview` / `categories` / `loading` / `errorMessage` / `窗口天数` / `load()` / `refreshRollup()`

- [ ] **Step 1: 写失败的 Adapter 测试**

创建 `frontend/src/api/adapters/analytics.spec.ts`：

```typescript
import { describe, expect, it } from 'vitest'

import { toChatBiCategories, toChatBiOverview } from './analytics'

describe('Chat BI adapter', () => {
  it('把 null 比率原样保留，不当成 0', () => {
    const overview = toChatBiOverview({
      start_date: '2026-08-17',
      end_date: '2026-08-23',
      answer_total: 0,
      business_question_total: 0,
      feedback_total: 0,
      thinking_sample_count: 0,
      adoption_rate: null,
      user_accuracy_rate: null,
      system_accuracy_rate: null,
      avg_thinking_ms: null,
      hit_rate: null,
      failure_rate: null,
      daily: [],
    })

    expect(overview.metrics.adoptionRate).toBeNull()
    expect(overview.metrics.adoptionRate).not.toBe(0)
    expect(overview.daily).toEqual([])
  })

  it('把扁平 snake_case 映射成领域模型的 camelCase', () => {
    const overview = toChatBiOverview({
      start_date: '2026-08-17',
      end_date: '2026-08-23',
      answer_total: 100,
      business_question_total: 90,
      feedback_total: 40,
      thinking_sample_count: 100,
      adoption_rate: 0.4,
      user_accuracy_rate: 0.75,
      system_accuracy_rate: 0.8,
      avg_thinking_ms: 2500,
      hit_rate: 0.8,
      failure_rate: 0.05,
      daily: [
        {
          stat_date: '2026-08-17',
          answer_total: 20,
          adoption_rate: 0.5,
          user_accuracy_rate: null,
          system_accuracy_rate: 0.9,
          avg_thinking_ms: 2000,
          hit_rate: 0.85,
          failure_rate: 0,
        },
      ],
    })

    expect(overview.answerTotal).toBe(100)
    expect(overview.metrics.systemAccuracyRate).toBe(0.8)
    expect(overview.daily[0].statDate).toBe('2026-08-17')
    expect(overview.daily[0].metrics.userAccuracyRate).toBeNull()
    expect(overview.daily[0].metrics.failureRate).toBe(0)
  })

  it('分类下钻保留后端给的顺序和中文名', () => {
    const rows = toChatBiCategories({
      start_date: '2026-08-17',
      end_date: '2026-08-23',
      items: [
        {
          category: 'REFUND',
          category_display_name: '电商退货/退款',
          answer_total: 9,
          adoption_rate: 0.33,
          user_accuracy_rate: null,
          system_accuracy_rate: 1,
          avg_thinking_ms: 1000,
          hit_rate: 1,
          failure_rate: 0,
        },
      ],
    })

    expect(rows[0].category).toBe('REFUND')
    expect(rows[0].displayName).toBe('电商退货/退款')
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd frontend; npx vitest run src/api/adapters/analytics.spec.ts`
Expected: FAIL，找不到模块 `./analytics`

- [ ] **Step 3: 写领域模型**

创建 `frontend/src/types/analytics.ts`：

```typescript
/**
 * Chat BI 看板的前端领域模型。
 *
 * 六项比率一律 `number | null`。`null` 是「样本不足」，和 `0` 语义完全不同，
 * 渲染层必须分别处理（AGENTS.md R7）。
 */
export interface NorthStarMetrics {
  adoptionRate: number | null
  userAccuracyRate: number | null
  systemAccuracyRate: number | null
  avgThinkingMs: number | null
  hitRate: number | null
  failureRate: number | null
}

export interface ChatBiDailyPoint {
  statDate: string
  answerTotal: number
  metrics: NorthStarMetrics
}

export interface ChatBiOverview {
  startDate: string
  endDate: string
  answerTotal: number
  businessQuestionTotal: number
  feedbackTotal: number
  thinkingSampleCount: number
  metrics: NorthStarMetrics
  daily: ChatBiDailyPoint[]
}

export interface ChatBiCategoryRow {
  category: string
  displayName: string
  answerTotal: number
  metrics: NorthStarMetrics
}
```

- [ ] **Step 4: 写 Adapter**

创建 `frontend/src/api/adapters/analytics.ts`：

```typescript
import type { components } from '@/api/generated'
import type {
  ChatBiCategoryRow,
  ChatBiOverview,
  NorthStarMetrics,
} from '@/types/analytics'

type OverviewPayload = components['schemas']['ChatBiOverviewResponse']
type CategoriesPayload = components['schemas']['ChatBiCategoriesResponse']

/** 六项比率的取字段是唯一的一处，overview / daily / category 三处复用。 */
function toMetrics(source: {
  adoption_rate: number | null
  user_accuracy_rate: number | null
  system_accuracy_rate: number | null
  avg_thinking_ms: number | null
  hit_rate: number | null
  failure_rate: number | null
}): NorthStarMetrics {
  return {
    adoptionRate: source.adoption_rate,
    userAccuracyRate: source.user_accuracy_rate,
    systemAccuracyRate: source.system_accuracy_rate,
    avgThinkingMs: source.avg_thinking_ms,
    hitRate: source.hit_rate,
    failureRate: source.failure_rate,
  }
}

export function toChatBiOverview(payload: OverviewPayload): ChatBiOverview {
  return {
    startDate: payload.start_date,
    endDate: payload.end_date,
    answerTotal: payload.answer_total,
    businessQuestionTotal: payload.business_question_total,
    feedbackTotal: payload.feedback_total,
    thinkingSampleCount: payload.thinking_sample_count,
    metrics: toMetrics(payload),
    daily: (payload.daily ?? []).map((point) => ({
      statDate: point.stat_date,
      answerTotal: point.answer_total,
      metrics: toMetrics(point),
    })),
  }
}

export function toChatBiCategories(payload: CategoriesPayload): ChatBiCategoryRow[] {
  return (payload.items ?? []).map((item) => ({
    category: item.category,
    displayName: item.category_display_name,
    answerTotal: item.answer_total,
    metrics: toMetrics(item),
  }))
}
```

- [ ] **Step 5: 写 API 调用**

创建 `frontend/src/api/analytics.ts`，照抄 `frontend/src/api/knowledge.ts` 的 `resolveTransport` + `auth: 'admin'` 写法：

```typescript
import type { components } from '@/api/generated'
import type { ChatBiCategoryRow, ChatBiOverview } from '@/types/analytics'

import { toChatBiCategories, toChatBiOverview } from './adapters/analytics'
import { resolveTransport } from './transport'

export interface ChatBiWindow {
  startDate: string
  endDate: string
}

function toQuery(window: ChatBiWindow): string {
  return new URLSearchParams({
    start_date: window.startDate,
    end_date: window.endDate,
  }).toString()
}

export async function getChatBiOverview(
  window: ChatBiWindow,
  signal: AbortSignal,
): Promise<ChatBiOverview> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/analytics/chatbi/overview?${toQuery(window)}`,
      method: 'GET',
      auth: 'admin',
    },
    signal,
  )
  return toChatBiOverview(
    (await response.json()) as components['schemas']['ChatBiOverviewResponse'],
  )
}

export async function getChatBiCategories(
  window: ChatBiWindow,
  signal: AbortSignal,
): Promise<ChatBiCategoryRow[]> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/analytics/chatbi/categories?${toQuery(window)}`,
      method: 'GET',
      auth: 'admin',
    },
    signal,
  )
  return toChatBiCategories(
    (await response.json()) as components['schemas']['ChatBiCategoriesResponse'],
  )
}

export async function triggerChatBiRollup(
  window: ChatBiWindow,
  signal: AbortSignal,
): Promise<number> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: '/api/admin/analytics/chatbi/rollup',
      method: 'POST',
      auth: 'admin',
      body: { start_date: window.startDate, end_date: window.endDate },
    },
    signal,
  )
  const payload = (await response.json()) as components['schemas']['ChatBiRollupResponse']
  return payload.rows_written
}
```

`transport` 的 body 传参形状以 `frontend/src/api/transport.ts` 的实际签名为准，照抄 `knowledge.ts` 里 PUT 请求的写法。

- [ ] **Step 6: 写 Store 测试与实现**

创建 `frontend/src/stores/analytics.spec.ts`，至少覆盖三条：

```typescript
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/analytics', () => ({
  getChatBiOverview: vi.fn(),
  getChatBiCategories: vi.fn(),
  triggerChatBiRollup: vi.fn(),
}))

import { getChatBiCategories, getChatBiOverview } from '@/api/analytics'
import { useAnalyticsStore } from './analytics'

describe('analytics store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('没有管理员令牌时不发请求', async () => {
    const store = useAnalyticsStore()
    await expect(store.load()).rejects.toThrow()
    expect(getChatBiOverview).not.toHaveBeenCalled()
  })

  it('加载成功后同时填充总览与分类', async () => {
    vi.mocked(getChatBiOverview).mockResolvedValue({
      startDate: '2026-08-17',
      endDate: '2026-08-23',
      answerTotal: 10,
      businessQuestionTotal: 9,
      feedbackTotal: 3,
      thinkingSampleCount: 10,
      metrics: {
        adoptionRate: 0.4,
        userAccuracyRate: null,
        systemAccuracyRate: 0.8,
        avgThinkingMs: 2500,
        hitRate: 0.9,
        failureRate: 0,
      },
      daily: [],
    })
    vi.mocked(getChatBiCategories).mockResolvedValue([])

    const store = useAnalyticsStore()
    store.setAdminToken('demo-admin-token')
    await store.load()

    expect(store.overview?.answerTotal).toBe(10)
    expect(store.categories).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('请求失败时写入可读错误并复位 loading', async () => {
    vi.mocked(getChatBiOverview).mockRejectedValue(new Error('后端不可用'))

    const store = useAnalyticsStore()
    store.setAdminToken('demo-admin-token')
    await expect(store.load()).rejects.toThrow()

    expect(store.errorMessage).not.toBe('')
    expect(store.loading).toBe(false)
  })
})
```

实现 `frontend/src/stores/analytics.ts`，结构照抄 `frontend/src/stores/knowledge.ts`（同样的 `adminToken` / `loading` / `errorMessage` / `AUTH_REQUIRED` 前置检查三段式），默认窗口为「含今天在内的最近 7 天」。

- [ ] **Step 7: 跑前端测试确认通过**

```powershell
cd frontend
npm run test
npm run lint
npm run typecheck
```

Expected: 全绿，新增用例全部 PASS

- [ ] **Step 8: 提交（需用户授权）**

```bash
git add frontend/src/types/analytics.ts frontend/src/api/adapters/analytics.ts frontend/src/api/analytics.ts frontend/src/stores/analytics.ts frontend/src/api/adapters/analytics.spec.ts frontend/src/stores/analytics.spec.ts
git commit -m "feat: 接入 Chat BI 看板的前端数据层"
```

---

## Task 9: 看板页面与组件

**Files:**
- Create: `frontend/src/views/OpsDashboardView.vue`
- Create: `frontend/src/components/analytics/NorthStarCards.vue`
- Create: `frontend/src/components/analytics/TrendChart.vue`
- Create: `frontend/src/components/analytics/CategoryTable.vue`
- Modify: `frontend/src/router/index.ts`
- Test: `frontend/src/components/analytics/NorthStarCards.spec.ts`
- Test: `frontend/src/views/OpsDashboardView.spec.ts`
- Test: `frontend/src/router/index.spec.ts`（追加）

**Interfaces:**
- Consumes: `useAnalyticsStore`、`NorthStarMetrics` / `ChatBiOverview` / `ChatBiCategoryRow`（Task 8）
- Produces: 路由 `name: 'ops-dashboard'`，路径 `/ops-dashboard`

- [ ] **Step 1: 写失败的组件测试**

创建 `frontend/src/components/analytics/NorthStarCards.spec.ts`：

```typescript
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NorthStarCards from './NorthStarCards.vue'

const FULL = {
  adoptionRate: 0.4,
  userAccuracyRate: 0.75,
  systemAccuracyRate: 0.8,
  avgThinkingMs: 2500,
  hitRate: 0.9,
  failureRate: 0.05,
}

const EMPTY = {
  adoptionRate: null,
  userAccuracyRate: null,
  systemAccuracyRate: null,
  avgThinkingMs: null,
  hitRate: null,
  failureRate: null,
}

describe('NorthStarCards', () => {
  it('六项指标各渲染一张卡', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: FULL } })
    expect(wrapper.findAll('[data-testid="north-star-card"]')).toHaveLength(6)
  })

  it('比率按百分比渲染，时长按秒渲染', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: FULL } })
    const text = wrapper.text()
    expect(text).toContain('40.0%')
    expect(text).toContain('2.5 秒')
  })

  it('样本不足时显示「样本不足」而不是 0%', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: EMPTY } })
    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).not.toContain('0.0%')
  })

  it('两个准确率分别标注口径，不合并成一个数', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: FULL } })
    const text = wrapper.text()
    expect(text).toContain('用户侧准确率')
    expect(text).toContain('系统侧准确率')
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd frontend; npx vitest run src/components/analytics/NorthStarCards.spec.ts`
Expected: FAIL，找不到 `NorthStarCards.vue`

- [ ] **Step 3: 写 NorthStarCards.vue**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { NorthStarMetrics } from '@/types/analytics'

const props = defineProps<{ metrics: NorthStarMetrics }>()

const INSUFFICIENT = '样本不足'

function percent(value: number | null): string {
  return value === null ? INSUFFICIENT : `${(value * 100).toFixed(1)}%`
}

function seconds(value: number | null): string {
  return value === null ? INSUFFICIENT : `${(value / 1000).toFixed(1)} 秒`
}

/**
 * 两个准确率刻意分开成两张卡。
 * 我们没有人工标注的正确答案，任何单一数字都不足以叫「准确率」：
 * 用户侧是满意度，系统侧是 Reviewer 一次放行率。合并会让这个数失去含义。
 */
const cards = computed(() => [
  { key: 'adoption', label: '回复采纳率', value: percent(props.metrics.adoptionRate), hint: '商家点击采纳的回答占比' },
  { key: 'user-accuracy', label: '用户侧准确率', value: percent(props.metrics.userAccuracyRate), hint: '点赞 /（点赞 + 点踩）' },
  { key: 'system-accuracy', label: '系统侧准确率', value: percent(props.metrics.systemAccuracyRate), hint: 'Reviewer 一次通过率' },
  { key: 'thinking', label: '平均思考时长', value: seconds(props.metrics.avgThinkingMs), hint: '一轮问答从提问到成稿' },
  { key: 'hit', label: '问题命中率', value: percent(props.metrics.hitRate), hint: '业务提问中命中数据或知识的占比' },
  { key: 'failure', label: '回答失效率', value: percent(props.metrics.failureRate), hint: '降级或质量未通过的占比' },
])
</script>

<template>
  <ul class="north-star">
    <li v-for="card in cards" :key="card.key" class="north-star__card" data-testid="north-star-card">
      <p class="north-star__label">{{ card.label }}</p>
      <p class="north-star__value" :class="{ 'north-star__value--empty': card.value === INSUFFICIENT }">
        {{ card.value }}
      </p>
      <p class="north-star__hint">{{ card.hint }}</p>
    </li>
  </ul>
</template>

<style scoped>
.north-star {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.north-star__card {
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 16px;
  background: var(--color-surface);
}

.north-star__label {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.north-star__value {
  margin: 8px 0 4px;
  font-size: 28px;
  font-weight: 600;
}

.north-star__value--empty {
  font-size: 18px;
  color: var(--color-text-muted);
}

.north-star__hint {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
```

CSS 变量名以 `frontend/src/assets/styles.css` 里实际存在的为准，不要新造变量。

- [ ] **Step 4: 写 TrendChart.vue 与 CategoryTable.vue**

`TrendChart.vue` 复用既有 `frontend/src/composables/useEChart.ts`，渲染日趋势折线：X 轴为 `statDate`，两条线分别是采纳率与命中率（百分比），另一条柱是 `answerTotal`。`null` 的点必须传 `null` 给 ECharts 让它断线，**不得填 0**。

`CategoryTable.vue` 渲染 `ChatBiCategoryRow[]`：分类中文名、问答量、六项指标；`null` 一律显示「样本不足」。表格外层套 `overflow-x: auto`。

- [ ] **Step 5: 写 OpsDashboardView.vue**

结构照抄 `frontend/src/views/KnowledgeBaseView.vue`：未授权时渲染 `AdminTokenDialog`，授权后加载数据。ECharts 走异步组件，与 `AssistantView.vue:56` 同款写法：

```typescript
const TrendChart = defineAsyncComponent(
  () => import('@/components/analytics/TrendChart.vue'),
)
```

页面需要有：窗口选择（最近 7 / 30 / 90 天）、「重刷汇总」按钮（调 `triggerChatBiRollup` 后重新 `load()`）、加载态、错误态。

- [ ] **Step 6: 注册路由**

`frontend/src/router/index.ts` 的 `routes` 数组里，在 `knowledge-base` 之后、`not-found` 之前插入：

```typescript
  {
    path: '/ops-dashboard',
    name: 'ops-dashboard',
    component: () => import('@/views/OpsDashboardView.vue'),
  },
```

同时把该文件顶部的注释「F0 只注册两条路由」改成三条，并说明第三条是管理员看板。**注释与代码不一致会误导下一位读者**。

在 `frontend/src/router/index.spec.ts` 追加一条断言：`/ops-dashboard` 能解析到 `name: 'ops-dashboard'`，且 `/login` 仍然落到 `not-found`。

- [ ] **Step 7: 写视图测试**

`frontend/src/views/OpsDashboardView.spec.ts` 至少覆盖：未输入令牌时只渲染令牌对话框、不发请求；输入令牌后渲染六张卡；加载失败时显示错误文案且不渲染卡片。

- [ ] **Step 8: 跑前端全量门禁**

```powershell
cd frontend
npm run test
npm run lint
npm run typecheck
npm run build
npm run firstpaint:check
npm run secrets:check
```

Expected: 全绿。`firstpaint:check` 必须通过——ECharts 不得因为新页面被拉进首屏关键路径。

- [ ] **Step 9: 提交（需用户授权）**

```bash
git add frontend/src/views/OpsDashboardView.vue frontend/src/components/analytics/ frontend/src/router/index.ts frontend/src/router/index.spec.ts frontend/src/views/OpsDashboardView.spec.ts
git commit -m "feat: 交付 Chat BI 管理员看板页面"
```

---

## Task 10: Mock E2E 与文档收口

**Files:**
- Modify: `frontend/src/api/mock/transport.ts`
- Create: `frontend/e2e/ops-dashboard.spec.ts`
- Modify: `docs/project-progress.md`
- Modify: `docs/yshopping-parity-audit.md`

**Interfaces:**
- Consumes: Task 9 的页面与路由
- Produces: 无代码接口；本 Task 只补端到端证据与文档

- [ ] **Step 1: 给 mock transport 加三个端点**

在 `frontend/src/api/mock/transport.ts` 里按既有写法追加三条路径的 mock 响应。**至少要有一条 `null` 比率的样本**，让 E2E 能验证「样本不足」态。

- [ ] **Step 2: 写 E2E**

创建 `frontend/e2e/ops-dashboard.spec.ts`，照抄 `frontend/e2e/` 下知识库后台那份的装配：

```typescript
import { expect, test } from '@playwright/test'

test.describe('Chat BI 看板', () => {
  test('未授权时只显示令牌对话框', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByTestId('north-star-card')).toHaveCount(0)
  })

  test('授权后显示六项指标与分类下钻', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('demo-admin-token')
    await page.getByRole('button', { name: '进入' }).click()

    await expect(page.getByTestId('north-star-card')).toHaveCount(6)
    await expect(page.getByText('用户侧准确率')).toBeVisible()
    await expect(page.getByText('系统侧准确率')).toBeVisible()
  })

  test('样本不足的指标显示文案而不是 0%', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('demo-admin-token')
    await page.getByRole('button', { name: '进入' }).click()

    await expect(page.getByText('样本不足').first()).toBeVisible()
  })
})
```

对话框的 label 与按钮名以 `AdminTokenDialog.vue` 实际文案为准。

- [ ] **Step 3: 跑 E2E**

```powershell
cd frontend
npm run test:e2e
```

Expected: 新增三条通过，既有 E2E 不回归

- [ ] **Step 4: 更新进度快照**

在 `docs/project-progress.md` 更新日期、当前阶段、已完成、最近验证、下一步。写清楚：

- 新增两个迁移（`20260823_0013`、`20260823_0014`），head 为 `20260823_0014`
- 五项北极星指标的口径与「双口径准确率」的裁定
- 汇总只存计数、比率在应用层算的理由
- 本轮**未调用真实 LLM**（R3）
- 本次实际跑过的验证命令与结果（照实写，包括跳过项）

- [ ] **Step 5: 在还原度审计里登记为我方增强**

在 `docs/yshopping-parity-audit.md` §5「有意偏离」新增一节，写明：参考项目**没有** Chat BI 衡量层——`yshopping-merchant-ai 4/` 全仓库搜不到采纳率、准确率、命中率、失效率、思考时长、看板的任何实现，它只有 `merchant_ai_answer` 表存下了原始字段。本项目的看板是我方增强，不是还原缺口。

- [ ] **Step 6: 最终全量门禁**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB = "1"
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run alembic heads
```

```powershell
cd frontend
npm run test
npm run lint
npm run typecheck
npm run build
npm run codegen:check
npm run fixtures:check
npm run firstpaint:check
npm run secrets:check
npm run mock:check
```

Expected: 全部通过，`alembic heads` 只有一个 head。**把真实输出记进 `docs/project-progress.md`，不要写「应该通过」。**

- [ ] **Step 7: 提交（需用户授权）**

```bash
git add frontend/src/api/mock/transport.ts frontend/e2e/ops-dashboard.spec.ts docs/project-progress.md docs/yshopping-parity-audit.md
git commit -m "test: 补充 Chat BI 看板的端到端覆盖并同步文档"
```

---

## 交付后简历可写的表述

本计划全部完成后，以下表述有代码支撑，可以写进简历：

> 设计并落地 Chat BI 量化评估体系：建设日粒度问答汇总表（日期 × 商家 × 问题分类），
> 定义采纳率、双口径准确率、平均思考时长、问题命中率、回答失效率五类北极星指标，
> 并搭建管理员看板支持窗口切换与业务分类下钻。汇总层只存可加计数、比率在应用层计算，
> 物化 Job 幂等可重跑，支持口径变更后重刷历史。

**不能**写的：DWD 分层建模（我们只有一层 ADS 汇总，没有 ODS/DWD/DWS 完整分层）、数据集成任务、数据质量监控与 SLA。这些仍然不在本项目范围内。

---

## 自检记录

**Spec 覆盖**：§0.1 的六项指标口径 → Task 3 纯函数 + Task 4 SQL；§0.2 只存计数 → Task 2 表结构（无比率列）+ Task 3 `merge` 测试；§0.3 幂等物化 → Task 4 的幂等与清幽灵行测试；§0.4 看板位置与鉴权 → Task 6 鉴权测试 + Task 9 路由。无遗漏。

**占位符扫描**：无 TBD / TODO / 「类似 Task N」/「添加适当的错误处理」。写计划时已现场核实并写死的既有事实：集成测试 session fixture 是 `db_session`（`tests/integration/repositories/test_answer_history.py`）、`CATEGORY_DISPLAY_NAMES` 在 `app/schemas/chat.py:96`、`Settings.business_timezone` 在 `app/core/config.py:40`、`error_responses(*status_codes: int)` 在 `app/core/errors.py:86`、迁移 head 为 `20260821_0012`、API 测试自建 app 的写法见 `tests/api/test_admin_ops.py`。仍需执行者现场核对的只剩两处：`Database` 实例的 fixture 名（Task 4 已给出「找不到就本文件内构造，不改全局 conftest」的处置）、`assets/styles.css` 的 CSS 变量名（Task 9 已注明不得新造变量）。

**类型一致性**：`QaCounters` 的十个字段名在 Task 2（列）、Task 3（dataclass）、Task 4（SELECT label 与 DailyRow）之间逐一对齐；`NorthStarMetrics` 的六个字段在 Task 3（后端 dataclass）、Task 6（`NorthStarPayload`）、Task 8（`toMetrics` 与前端 interface）之间以 snake_case ↔ camelCase 一一对应，无孤儿字段。
