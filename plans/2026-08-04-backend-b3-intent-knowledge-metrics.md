# 后端 B3「指标、知识与结构化意图」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让助手把商家问题理解成受严格约束的结构化 `QueryIntent`——判定业务域、指标、维度、筛选与日期范围——并在此过程中完成两层知识检索与三级指标口径检索。B3 只「理解」，不「查数」。

**Architecture:** 关键词匹配的两层知识检索（索引层给模型词汇、正文层给模型事实），中间夹一个两阶段 LLM 意图识别（分类 → 理解），出口是被三套白名单校验过的 `QueryIntent`。LLM 通过 Protocol 注入，测试一律用 `FakeLlmClient`。全部串在 LangGraph 的 13 节点骨架上，其中 5 个属于 B4/B5 的节点先做 passthrough。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.0（async）、Alembic、Pydantic v2、LangGraph、httpx、pytest、Ruff、mypy。

**设计说明：** `docs/specs/2026-08-04-backend-b3-design.md`。本计划的每个决策都以该 spec 为准，冲突时以 spec 为准并回写本文件。

## Global Constraints

- 用户可见文案与知识内容使用中文，代码标识符使用英文。
- **单元测试必须 mock LLM**（AGENTS.md R3）。任何测试都不得发起真实 DeepSeek 调用。首次真实调用前必须取得用户对模型、调用次数和费用的明确同意。
- **`yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 整体只读**（R8）。可以 Read/Grep，不得写入、重命名、格式化。
- 新代码的品牌文案、prompt 话术与演示数据一律使用 **Borough**，不得残留 `yshopping`。
- **商家身份只能由 Bearer Token 解析**，不接受请求体或查询参数传入的 `merchant_id`。
- **LLM 不得直接生成或执行任意 SQL**（R4）。意图对象里不得出现 SQL 字符串或表名。
- **降级必须对用户可见**（R7）：`analysis_sources`、`quality_status`、`quality_notes`、`degraded`、`degraded_reason` 要如实填写。
- 日期范围上限 **180 天**，`limit` 上限由后端覆盖，二者都是「后端截断」而非「报错」。
- 三套白名单是**代码内的不可变常量**，不入库、不接受运行时修改。
- 有意偏离参考实现的地方必须在代码注释里注明「参考实现如何做、本项目为何不同」（清单见 spec §3.2）。
- 项目规则禁止未经明确授权的 Git commit/push/tag/PR。**本计划各 Task 的「Commit」步骤需在获得授权后执行**；未获授权时以「全部门禁通过」替代 commit。

**后端门禁（每个 Task 结束都要跑）：**

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

---

### Task 1: 业务域常量

**Files:**
- Create: `backend/app/knowledge/__init__.py`
- Create: `backend/app/knowledge/domains.py`
- Test: `backend/tests/unit/knowledge/test_domains.py`

**Interfaces:**
- Consumes: `app.schemas.chat.QuestionCategory`（B2 已定义，11 个取值）。
- Produces: `DOMAIN_KEYWORDS: Mapping[QuestionCategory, tuple[str, ...]]`、`DOMAIN_TABLES: Mapping[QuestionCategory, tuple[str, ...]]`、`merchant_filter_key(category: QuestionCategory) -> str`、`INDEX_PATH_MARKERS: tuple[str, ...]`、`MAX_KNOWLEDGE_CHARS: int`、`MAX_PROMPT_KNOWLEDGE_CHARS: int`。

- [ ] **Step 1: 写失败的测试。**

  `backend/tests/unit/knowledge/test_domains.py`：

  ```python
  """业务域常量。别名表直接决定检索召回，改动必须有测试兜住。"""

  from __future__ import annotations

  import pytest

  from app.knowledge.domains import (
      DOMAIN_KEYWORDS,
      DOMAIN_TABLES,
      INDEX_PATH_MARKERS,
      MAX_KNOWLEDGE_CHARS,
      MAX_PROMPT_KNOWLEDGE_CHARS,
      merchant_filter_key,
  )
  from app.schemas.chat import QuestionCategory


  def test_每个业务域都有别名且不含空串() -> None:
      business_categories = [
          category for category in QuestionCategory if category is not QuestionCategory.UNKNOWN
      ]

      for category in business_categories:
          keywords = DOMAIN_KEYWORDS[category]
          assert keywords, category
          assert all(keyword.strip() for keyword in keywords), category


  def test_身份与商家其他用_merchant_id_其余用_seller_id() -> None:
      # 参考实现的 wiki index 里这两个域的过滤键与其余八个不同。
      # 丢掉这个差异会让 B4 写出跨商家泄漏的查询。
      assert merchant_filter_key(QuestionCategory.IDENTITY) == "merchant_id"
      assert merchant_filter_key(QuestionCategory.MERCHANT_OTHER) == "merchant_id"
      assert merchant_filter_key(QuestionCategory.TRADE) == "seller_id"
      assert merchant_filter_key(QuestionCategory.REFUND) == "seller_id"


  def test_平台规则不查数据表() -> None:
      assert DOMAIN_TABLES[QuestionCategory.PLATFORM_RULE] == ()


  def test_别名不含旧品牌词() -> None:
      for keywords in DOMAIN_KEYWORDS.values():
          for keyword in keywords:
              assert "yshopping" not in keyword.lower()


  @pytest.mark.parametrize("marker", ["index", "rule", "目录"])
  def test_索引层标记覆盖参考实现的三种(marker: str) -> None:
      assert marker in INDEX_PATH_MARKERS


  def test_进_prompt_前的上限小于检索层上限() -> None:
      # 参考实现两处取值不同：检索层 24000，进 prompt 前再截到 10000。
      assert MAX_PROMPT_KNOWLEDGE_CHARS < MAX_KNOWLEDGE_CHARS
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/knowledge/test_domains.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.knowledge'`。

- [ ] **Step 3: 实现常量。**

  `backend/app/knowledge/__init__.py` 内容为空。

  `backend/app/knowledge/domains.py`：

  ```python
  """业务域常量。

  别名、主数据表与商家过滤键都是**代码常量**，不入库。

  参考实现把这份映射放在 WikiMemoryService.categoryKeywords() 的 switch 里；
  本项目保持同样的归属——白名单和域映射一旦能被运行时改写就不再是约束。
  内容取自参考项目 runtime/llm-wiki/index/README.md 的业务索引表。
  """

  from __future__ import annotations

  from collections.abc import Mapping
  from typing import Final

  from app.schemas.chat import QuestionCategory

  #: 检索层拼接知识的字符上限。
  MAX_KNOWLEDGE_CHARS: Final[int] = 24_000
  #: 进 prompt 之前的二次截断上限。参考实现同样是两级不同取值。
  MAX_PROMPT_KNOWLEDGE_CHARS: Final[int] = 10_000

  #: 索引层只取路径命中这些标记的文档。业务域未知时靠它们提供拆词词汇。
  INDEX_PATH_MARKERS: Final[tuple[str, ...]] = ("index", "rule", "目录")

  DOMAIN_KEYWORDS: Final[Mapping[QuestionCategory, tuple[str, ...]]] = {
      QuestionCategory.TRADE: ("交易", "订单", "成交", "履约", "支付", "trade", "order", "gmv"),
      QuestionCategory.REFUND: ("退货", "退款", "售后", "refund", "return"),
      QuestionCategory.CS_TICKET: ("客服", "工单", "咨询", "ticket"),
      QuestionCategory.COMPENSATION: ("理赔", "赔付", "补偿", "repay"),
      QuestionCategory.COUPON: ("优惠券", "优惠", "券", "coupon"),
      QuestionCategory.GOODS: ("商品", "货品", "上架", "goods", "spu"),
      QuestionCategory.MERCHANT_OTHER: ("保证金", "申诉", "处罚", "merchant"),
      QuestionCategory.IDENTITY: ("身份", "资料", "商家信息", "merchant"),
      QuestionCategory.SCM: ("供应链", "入库", "分拣", "质检", "鉴定", "出库", "仓库", "scm"),
      QuestionCategory.PLATFORM_RULE: ("规则", "政策", "平台要求"),
      QuestionCategory.UNKNOWN: ("通用",),
  }

  #: 各域的主数据表。平台规则不查库，因此为空元组。
  #: B4 建实际表时以此为白名单源，表名沿用参考实现的语义但归属本项目。
  DOMAIN_TABLES: Final[Mapping[QuestionCategory, tuple[str, ...]]] = {
      QuestionCategory.TRADE: ("trade_order_detail",),
      QuestionCategory.REFUND: ("trade_refund_detail",),
      QuestionCategory.CS_TICKET: ("cs_ticket_detail",),
      QuestionCategory.COMPENSATION: ("cs_repay_detail",),
      QuestionCategory.COUPON: ("coupon_detail",),
      QuestionCategory.GOODS: ("goods_detail",),
      QuestionCategory.MERCHANT_OTHER: ("merchant_appeal_detail", "merchant_deposit_detail"),
      QuestionCategory.IDENTITY: ("merchant_profile_dim",),
      QuestionCategory.SCM: ("scm_detail",),
      QuestionCategory.PLATFORM_RULE: (),
      QuestionCategory.UNKNOWN: (),
  }

  #: 这两个域按 merchant_id 过滤，其余八个按 seller_id。
  #: 参考实现的业务索引表明确区分了这一点，混用会造成跨商家泄漏。
  _MERCHANT_ID_DOMAINS: Final[frozenset[QuestionCategory]] = frozenset(
      {QuestionCategory.IDENTITY, QuestionCategory.MERCHANT_OTHER}
  )


  def merchant_filter_key(category: QuestionCategory) -> str:
      """返回该业务域用于隔离商家的列名。"""

      return "merchant_id" if category in _MERCHANT_ID_DOMAINS else "seller_id"
  ```

- [ ] **Step 4: 运行测试。**

  Run: `cd backend && uv run pytest tests/unit/knowledge/ -v`

  Expected: PASS，8 个测试（含 3 个参数化）。

- [ ] **Step 5: 跑门禁。**

  Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

  Expected: 全部退出码 0。

---

### Task 2: `knowledge_documents` 加两列与仓储

**Files:**
- Modify: `backend/app/models/knowledge.py`
- Create: `backend/migrations/versions/20260804_0002_knowledge_source_path.py`
- Create: `backend/app/repositories/knowledge.py`
- Test: `backend/tests/integration/repositories/test_knowledge_repository.py`

**Interfaces:**
- Produces: `KnowledgeDocument.source_path: str`、`KnowledgeDocument.is_complete: bool`。
- Produces: `KnowledgeRepository(session).list_active() -> list[KnowledgeDocument]`、`.upsert_by_source_path(...) -> KnowledgeDocument`。

- [ ] **Step 1: 写失败的仓储测试。**

  `backend/tests/integration/repositories/test_knowledge_repository.py`：

  ```python
  """知识文档仓储。导入脚本要能重复执行，所以 upsert 是核心行为。"""

  from __future__ import annotations

  import pytest
  from sqlalchemy.ext.asyncio import AsyncSession

  from app.repositories.knowledge import KnowledgeRepository


  @pytest.mark.asyncio
  async def test_按_source_path_幂等_upsert(db_session: AsyncSession) -> None:
      repository = KnowledgeRepository(db_session)

      await repository.upsert_by_source_path(
          source_path="业务/交易/业务流程/交易业务流程图.md",
          category="TRADE",
          title="交易业务流程图",
          content="下单到履约的流程。",
          source="Borough 团队维护",
          is_complete=True,
      )
      await repository.upsert_by_source_path(
          source_path="业务/交易/业务流程/交易业务流程图.md",
          category="TRADE",
          title="交易业务流程图",
          content="下单到履约的流程（已更新）。",
          source="Borough 团队维护",
          is_complete=True,
      )
      await db_session.flush()

      documents = await repository.list_active()

      assert len(documents) == 1
      assert documents[0].content.endswith("（已更新）。")
      assert documents[0].version == 2


  @pytest.mark.asyncio
  async def test_骨架文档标记为不完整(db_session: AsyncSession) -> None:
      repository = KnowledgeRepository(db_session)

      await repository.upsert_by_source_path(
          source_path="业务/优惠券/业务名词解释/优惠券名词.md",
          category="COUPON",
          title="优惠券名词",
          content="⚠️ 待团队补充",
          source="Borough 团队维护",
          is_complete=False,
      )
      await db_session.flush()

      documents = await repository.list_active()

      assert documents[0].is_complete is False
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/integration/repositories/test_knowledge_repository.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.repositories.knowledge'`。

  若本地未起 PostgreSQL，先 `docker compose up -d db`（compose 文件见 `backend/`），再 `uv run alembic upgrade head`。

- [ ] **Step 3: 给模型加两列。**

  在 `backend/app/models/knowledge.py` 的 `KnowledgeDocument` 中，`source` 字段之后追加：

  ```python
      #: 导入时的原始相对路径。检索按「路径 + 正文」匹配，路径本身携带业务域与
      #: 文档类型信息（业务/交易/业务流程/...），丢掉它等于丢掉一半匹配依据。
      source_path: Mapped[str] = mapped_column(Text, nullable=False)
      #: 旧 Wiki 里带「⚠️ 待团队补充」标记的骨架文档为 False。
      #: 命中骨架时回答必须如实说明资料不完整（AGENTS.md R7）。
      is_complete: Mapped[bool] = mapped_column(
          Boolean,
          nullable=False,
          server_default=text("true"),
      )
  ```

  同时把 `Boolean` 加进该文件顶部的 `from sqlalchemy import ...`，并在 `__table_args__` 里追加唯一索引：

  ```python
          Index("uq_knowledge_documents_source_path", "source_path", unique=True),
  ```

- [ ] **Step 4: 生成并编辑迁移。**

  Run: `cd backend && uv run alembic revision -m "knowledge source path"`

  把生成文件重命名为 `20260804_0002_knowledge_source_path.py`，`upgrade()` 写：

  ```python
  def upgrade() -> None:
      op.add_column(
          "knowledge_documents",
          sa.Column("source_path", sa.Text(), nullable=False, server_default=""),
      )
      op.add_column(
          "knowledge_documents",
          sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.text("true")),
      )
      # 既有行的 source_path 为空串，唯一索引会冲突，因此先用 id 回填再建索引。
      op.execute("UPDATE knowledge_documents SET source_path = 'legacy/' || id::text")
      op.alter_column("knowledge_documents", "source_path", server_default=None)
      op.create_index(
          "uq_knowledge_documents_source_path",
          "knowledge_documents",
          ["source_path"],
          unique=True,
      )


  def downgrade() -> None:
      op.drop_index("uq_knowledge_documents_source_path", table_name="knowledge_documents")
      op.drop_column("knowledge_documents", "is_complete")
      op.drop_column("knowledge_documents", "source_path")
  ```

- [ ] **Step 5: 实现仓储。**

  `backend/app/repositories/knowledge.py`：

  ```python
  """知识文档仓储。

  团队知识对所有商家一致，不含商家数据，因此这里不做 merchant_id 过滤——
  这与 ConversationRepository 的隔离要求不同，是有意的。商家级记忆（P1）是
  另一张表，届时必须按 merchant_id 隔离。
  """

  from __future__ import annotations

  from sqlalchemy import select

  from sqlalchemy.ext.asyncio import AsyncSession

  from app.models.knowledge import KnowledgeDocument


  class KnowledgeRepository:
      def __init__(self, session: AsyncSession) -> None:
          self._session = session

      async def list_active(self) -> list[KnowledgeDocument]:
          statement = (
              select(KnowledgeDocument)
              .where(KnowledgeDocument.status == "ACTIVE")
              .order_by(KnowledgeDocument.source_path)
          )
          result = await self._session.execute(statement)
          return list(result.scalars())

      async def upsert_by_source_path(
          self,
          *,
          source_path: str,
          category: str,
          title: str,
          content: str,
          source: str,
          is_complete: bool,
      ) -> KnowledgeDocument:
          """按 source_path 幂等写入。导入脚本会被反复执行，不能产生重复行。"""

          statement = select(KnowledgeDocument).where(
              KnowledgeDocument.source_path == source_path
          )
          existing = (await self._session.execute(statement)).scalar_one_or_none()

          if existing is None:
              document = KnowledgeDocument(
                  source_path=source_path,
                  category=category,
                  title=title,
                  content=content,
                  source=source,
                  is_complete=is_complete,
                  status="ACTIVE",
              )
              self._session.add(document)
              return document

          existing.category = category
          existing.title = title
          existing.content = content
          existing.source = source
          existing.is_complete = is_complete
          existing.version += 1
          return existing
  ```

- [ ] **Step 6: 运行测试与门禁。**

  Run: `cd backend && uv run alembic upgrade head && uv run pytest tests/integration/repositories/test_knowledge_repository.py -v`

  Expected: PASS，2 个测试。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 3: 两层知识检索

**Files:**
- Create: `backend/app/knowledge/retrieval.py`
- Test: `backend/tests/unit/knowledge/test_retrieval.py`

**Interfaces:**
- Consumes: Task 1 的常量、Task 2 的 `KnowledgeRepository`。
- Produces: `@dataclass(frozen=True) KnowledgeHit(source_path: str, title: str, content: str, is_complete: bool)`。
- Produces: `@dataclass(frozen=True) KnowledgeResult(text: str, hits: tuple[KnowledgeHit, ...], matched: bool, has_incomplete: bool)`。
- Produces: `KnowledgeRetrieval(repository).load_index() -> KnowledgeResult`。
- Produces: `KnowledgeRetrieval(repository).load_domain(category, keywords) -> KnowledgeResult`。
- Produces: `strip_metric_suffix(keyword: str) -> str`。

- [ ] **Step 1: 写失败的检索测试。**

  `backend/tests/unit/knowledge/test_retrieval.py`：

  ```python
  """两层知识检索。

  索引层与正文层的分工是本阶段的核心：索引层给模型词汇，正文层给模型事实。
  测试用假仓储，不碰数据库。
  """

  from __future__ import annotations

  import pytest

  from app.knowledge.retrieval import (
      KnowledgeRetrieval,
      strip_metric_suffix,
  )
  from app.schemas.chat import QuestionCategory


  class _FakeDocument:
      def __init__(
          self,
          source_path: str,
          title: str,
          content: str,
          category: str = "TRADE",
          is_complete: bool = True,
      ) -> None:
          self.source_path = source_path
          self.title = title
          self.content = content
          self.category = category
          self.is_complete = is_complete
          self.status = "ACTIVE"


  class _FakeRepository:
      def __init__(self, documents: list[_FakeDocument]) -> None:
          self._documents = documents
          self.list_calls = 0

      async def list_active(self) -> list[_FakeDocument]:
          self.list_calls += 1
          return self._documents


  def _documents() -> list[_FakeDocument]:
      return [
          _FakeDocument("index/README.md", "业务索引", "交易 退货 优惠券 各域目录"),
          _FakeDocument("平台规则/rule.md", "平台规则", "上架规则与政策要求"),
          _FakeDocument("业务/交易/业务流程/交易流程.md", "交易流程", "下单 支付 履约 订单"),
          _FakeDocument("业务/退货/业务流程/退货流程.md", "退货流程", "退货 退款 售后"),
          _FakeDocument(
              "业务/优惠券/业务名词解释/优惠券名词.md",
              "优惠券名词",
              "优惠券 ⚠️ 待团队补充",
              category="COUPON",
              is_complete=False,
          ),
      ]


  @pytest.mark.asyncio
  async def test_索引层只取_index_rule_目录_文档() -> None:
      retrieval = KnowledgeRetrieval(_FakeRepository(_documents()))

      result = await retrieval.load_index()

      paths = [hit.source_path for hit in result.hits]
      assert paths == ["index/README.md", "平台规则/rule.md"]
      assert result.matched is True


  @pytest.mark.asyncio
  async def test_正文层按业务域别名命中() -> None:
      retrieval = KnowledgeRetrieval(_FakeRepository(_documents()))

      result = await retrieval.load_domain(QuestionCategory.REFUND, ())

      paths = [hit.source_path for hit in result.hits]
      assert paths == ["业务/退货/业务流程/退货流程.md"]


  @pytest.mark.asyncio
  async def test_正文层再按意图关键词过滤() -> None:
      retrieval = KnowledgeRetrieval(_FakeRepository(_documents()))

      hit = await retrieval.load_domain(QuestionCategory.TRADE, ("履约",))
      miss = await retrieval.load_domain(QuestionCategory.TRADE, ("赔付",))

      assert [item.source_path for item in hit.hits] == ["业务/交易/业务流程/交易流程.md"]
      assert miss.matched is False


  @pytest.mark.asyncio
  async def test_退货量能命中只写了退货的文档() -> None:
      # 词尾剥离：「退货量」剥成「退货」才命中。这条启发式来自参考实现，
      # 没有它，用户问「最近7天退货量趋势」会检索不到任何退货知识。
      retrieval = KnowledgeRetrieval(_FakeRepository(_documents()))

      result = await retrieval.load_domain(QuestionCategory.REFUND, ("退货量",))

      assert [item.source_path for item in result.hits] == ["业务/退货/业务流程/退货流程.md"]


  @pytest.mark.asyncio
  async def test_两层都未命中时显式返回未命中() -> None:
      retrieval = KnowledgeRetrieval(_FakeRepository([]))

      result = await retrieval.load_domain(QuestionCategory.SCM, ())

      assert result.matched is False
      assert result.hits == ()
      assert result.text == ""


  @pytest.mark.asyncio
  async def test_命中骨架文档时标记资料不完整() -> None:
      retrieval = KnowledgeRetrieval(_FakeRepository(_documents()))

      result = await retrieval.load_domain(QuestionCategory.COUPON, ())

      assert result.matched is True
      assert result.has_incomplete is True


  @pytest.mark.asyncio
  async def test_拼接超过上限时截断() -> None:
      long_document = _FakeDocument(
          "业务/交易/业务流程/长文.md", "长文", "订单" + "凑" * 30_000
      )
      retrieval = KnowledgeRetrieval(_FakeRepository([long_document]))

      result = await retrieval.load_domain(QuestionCategory.TRADE, ())

      from app.knowledge.domains import MAX_KNOWLEDGE_CHARS

      assert len(result.text) <= MAX_KNOWLEDGE_CHARS


  @pytest.mark.parametrize(
      ("raw", "expected"),
      [
          ("退货量", "退货"),
          ("成交金额", "成交"),
          ("订单数", "订单"),
          ("退货", "退货"),
          ("量", "量"),
      ],
  )
  def test_词尾剥离(raw: str, expected: str) -> None:
      assert strip_metric_suffix(raw) == expected
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/knowledge/test_retrieval.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.knowledge.retrieval'`。

- [ ] **Step 3: 实现检索。**

  `backend/app/knowledge/retrieval.py`：

  ```python
  """两层知识检索。

  索引层（业务域未知）只加载目录与规则文档，作用是给模型提供拆词和领域识别
  所需的词汇，不是给模型答案。正文层（业务域已知）按域取正文，再按意图关键词
  收窄。

  匹配方式与参考实现一致：关键词命中「路径 + 正文」。参考实现读文件系统，
  本项目读 PostgreSQL（前端/后端方案 §6.5：Railway 容器重启不保留写入的文件），
  因此路径以 source_path 列的形式保留下来。
  """

  from __future__ import annotations

  import re
  from collections.abc import Sequence
  from dataclasses import dataclass
  from typing import Protocol

  from app.knowledge.domains import (
      DOMAIN_KEYWORDS,
      INDEX_PATH_MARKERS,
      MAX_KNOWLEDGE_CHARS,
  )
  from app.schemas.chat import QuestionCategory

  #: 中文指标问法的常见词尾。「退货量」要能命中只写了「退货」的文档。
  _METRIC_SUFFIX = re.compile(r"(指标|明细|数据|情况|趋势|数量|金额|次数|量|数)$")
  _MIN_STEM_LENGTH = 2


  def strip_metric_suffix(keyword: str) -> str:
      """剥掉指标问法的词尾。剥完短于两个字则保留原词，避免过度泛化。"""

      stem = _METRIC_SUFFIX.sub("", keyword.strip())
      return stem if len(stem) >= _MIN_STEM_LENGTH else keyword.strip()


  @dataclass(frozen=True)
  class KnowledgeHit:
      source_path: str
      title: str
      content: str
      is_complete: bool


  @dataclass(frozen=True)
  class KnowledgeResult:
      text: str
      hits: tuple[KnowledgeHit, ...]
      matched: bool
      has_incomplete: bool


  _EMPTY = KnowledgeResult(text="", hits=(), matched=False, has_incomplete=False)


  class _DocumentLike(Protocol):
      source_path: str
      title: str
      content: str
      is_complete: bool


  class _RepositoryLike(Protocol):
      async def list_active(self) -> list[_DocumentLike]: ...


  class KnowledgeRetrieval:
      def __init__(self, repository: _RepositoryLike) -> None:
          self._repository = repository

      async def load_index(self) -> KnowledgeResult:
          """第一层：业务域未知，只取目录与规则文档。"""

          documents = await self._repository.list_active()
          hits = [
              document
              for document in documents
              if any(marker in document.source_path.lower() for marker in INDEX_PATH_MARKERS)
          ]
          return _render(hits)

      async def load_domain(
          self,
          category: QuestionCategory,
          keywords: Sequence[str],
      ) -> KnowledgeResult:
          """第二层：业务域已知，取该域正文并按意图关键词收窄。"""

          documents = await self._repository.list_active()
          aliases = DOMAIN_KEYWORDS.get(category, ())
          hits = [
              document
              for document in documents
              if _contains_any(_haystack(document), aliases)
          ]

          if keywords:
              hits = [
                  document
                  for document in hits
                  if _matches_keywords(_haystack(document), keywords)
              ]

          # 团队知识为空时，商家级记忆是下一跳（P1/B8）。B3 没有记忆表，
          # 因此这里直接落到显式未命中，而不是返回空串让模型自由发挥。
          return _render(hits)


  def _haystack(document: _DocumentLike) -> str:
      return f"{document.source_path} {document.content}".lower()


  def _contains_any(haystack: str, keywords: Sequence[str]) -> bool:
      return any(keyword.lower() in haystack for keyword in keywords if keyword.strip())


  def _matches_keywords(haystack: str, keywords: Sequence[str]) -> bool:
      for raw in keywords:
          keyword = raw.strip().lower()
          if not keyword:
              continue
          if keyword in haystack:
              return True
          stem = strip_metric_suffix(keyword)
          if stem != keyword and stem in haystack:
              return True
      return False


  def _render(documents: list[_DocumentLike]) -> KnowledgeResult:
      if not documents:
          return _EMPTY

      chunks: list[str] = []
      total = 0
      hits: list[KnowledgeHit] = []
      for document in documents:
          block = f"## {document.title}\n（来源：{document.source_path}）\n{document.content}\n"
          if total + len(block) > MAX_KNOWLEDGE_CHARS:
              break
          chunks.append(block)
          total += len(block)
          hits.append(
              KnowledgeHit(
                  source_path=document.source_path,
                  title=document.title,
                  content=document.content,
                  is_complete=document.is_complete,
              )
          )

      if not hits:
          # 第一篇就超长：截断它而不是整体丢弃，否则长文档等于不存在。
          first = documents[0]
          hits = [
              KnowledgeHit(
                  source_path=first.source_path,
                  title=first.title,
                  content=first.content,
                  is_complete=first.is_complete,
              )
          ]
          chunks = [first.content[:MAX_KNOWLEDGE_CHARS]]

      return KnowledgeResult(
          text="\n".join(chunks)[:MAX_KNOWLEDGE_CHARS],
          hits=tuple(hits),
          matched=True,
          has_incomplete=any(not hit.is_complete for hit in hits),
      )
  ```

- [ ] **Step 4: 运行测试与门禁。**

  Run: `cd backend && uv run pytest tests/unit/knowledge/ -v`

  Expected: PASS，12 个测试（7 个 async + 5 个参数化）。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 4: 旧 Wiki 导入脚本

**Files:**
- Create: `backend/scripts/import_wiki.py`
- Test: `backend/tests/unit/knowledge/test_wiki_import.py`

**Interfaces:**
- Consumes: Task 2 的 `KnowledgeRepository`。
- Produces: `parse_wiki_tree(root: Path) -> list[WikiEntry]`、`@dataclass(frozen=True) WikiEntry(source_path, category, title, content, is_complete)`。
- Produces: CLI `uv run python scripts/import_wiki.py --root <参考项目 llm-wiki 路径>`。

- [ ] **Step 1: 写失败的解析测试。**

  `backend/tests/unit/knowledge/test_wiki_import.py`：

  ```python
  """旧 Wiki 导入。

  参考项目只读（AGENTS.md R8），所以这里用临时目录构造同构的树来测解析，
  不读也不写参考目录。
  """

  from __future__ import annotations

  from pathlib import Path

  from scripts.import_wiki import parse_wiki_tree


  def _build_tree(root: Path) -> None:
      (root / "index").mkdir(parents=True)
      (root / "index" / "README.md").write_text("# 业务索引\n交易 退货", encoding="utf-8")

      trade_flow = root / "业务" / "交易" / "业务流程"
      trade_flow.mkdir(parents=True)
      (trade_flow / "交易业务流程图.md").write_text(
          "适用范围：yshopping 商家订单分析。", encoding="utf-8"
      )

      trade_ddl = root / "业务" / "交易" / "ddl"
      trade_ddl.mkdir(parents=True)
      (trade_ddl / "交易表.md").write_text("## `yshopping.dwm_trade_order_detail_di`", encoding="utf-8")

      coupon_terms = root / "业务" / "优惠券" / "业务名词解释"
      coupon_terms.mkdir(parents=True)
      (coupon_terms / "优惠券名词.md").write_text("⚠️ 待团队补充", encoding="utf-8")


  def test_排除_ddl_目录(tmp_path: Path) -> None:
      _build_tree(tmp_path)

      entries = parse_wiki_tree(tmp_path)

      paths = [entry.source_path for entry in entries]
      # ddl 描述旧库表，本项目的经营表要到 B4 才设计，导进来会让助手描述不存在的表。
      assert not any("ddl" in path for path in paths)


  def test_品牌词洗成_borough(tmp_path: Path) -> None:
      _build_tree(tmp_path)

      entries = parse_wiki_tree(tmp_path)
      trade = next(entry for entry in entries if "交易业务流程图" in entry.source_path)

      assert "yshopping" not in trade.content.lower()
      assert "Borough" in trade.content


  def test_骨架文档标记为不完整(tmp_path: Path) -> None:
      _build_tree(tmp_path)

      entries = parse_wiki_tree(tmp_path)
      coupon = next(entry for entry in entries if "优惠券名词" in entry.source_path)
      trade = next(entry for entry in entries if "交易业务流程图" in entry.source_path)

      assert coupon.is_complete is False
      assert trade.is_complete is True


  def test_从路径推断业务域(tmp_path: Path) -> None:
      _build_tree(tmp_path)

      entries = parse_wiki_tree(tmp_path)

      categories = {entry.source_path: entry.category for entry in entries}
      assert categories["业务/交易/业务流程/交易业务流程图.md"] == "TRADE"
      assert categories["业务/优惠券/业务名词解释/优惠券名词.md"] == "COUPON"
      assert categories["index/README.md"] == "UNKNOWN"


  def test_source_path_使用正斜杠(tmp_path: Path) -> None:
      # Windows 上 Path 会产出反斜杠，入库前必须归一，否则检索的路径匹配会失效。
      _build_tree(tmp_path)

      entries = parse_wiki_tree(tmp_path)

      assert all("\\" not in entry.source_path for entry in entries)
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/knowledge/test_wiki_import.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'scripts.import_wiki'`。

  若 `scripts` 不可导入，在 `backend/scripts/__init__.py` 建空文件。

- [ ] **Step 3: 实现脚本。**

  `backend/scripts/import_wiki.py`：

  ```python
  """把参考项目的旧 Wiki 导入 knowledge_documents。

  参考项目只读（AGENTS.md R8）：本脚本只读取，不写入、不重命名、不格式化。

  排除 ddl/ 与「指标或调用指标平台mcp的skill/」两类目录——它们描述旧库表结构
  （yshopping.dwm_*），而本项目的经营数据表要到 B4 才设计。导进来会让助手
  描述一批不存在的表。
  """

  from __future__ import annotations

  import argparse
  import asyncio
  import re
  from dataclasses import dataclass
  from pathlib import Path

  from app.core.config import Settings
  from app.db.session import Database
  from app.repositories.knowledge import KnowledgeRepository

  _EXCLUDED_DIRS = ("ddl", "指标或调用指标平台mcp的skill")
  _INCOMPLETE_MARKER = "待团队补充"
  _BRAND_PATTERN = re.compile(r"yshopping", re.IGNORECASE)

  _DOMAIN_BY_DIRECTORY = {
      "交易": "TRADE",
      "退货": "REFUND",
      "客服工单": "CS_TICKET",
      "理赔赔付": "COMPENSATION",
      "优惠券": "COUPON",
      "商品": "GOODS",
      "商家其他": "MERCHANT_OTHER",
      "身份信息": "IDENTITY",
      "供应链": "SCM",
      "平台规则": "PLATFORM_RULE",
  }


  @dataclass(frozen=True)
  class WikiEntry:
      source_path: str
      category: str
      title: str
      content: str
      is_complete: bool


  def parse_wiki_tree(root: Path) -> list[WikiEntry]:
      entries: list[WikiEntry] = []
      for path in sorted(root.rglob("*.md")):
          relative = path.relative_to(root)
          parts = relative.parts
          if any(part in _EXCLUDED_DIRS for part in parts):
              continue

          raw = path.read_text(encoding="utf-8")
          entries.append(
              WikiEntry(
                  # 统一正斜杠：Windows 的反斜杠会让检索的路径匹配失效。
                  source_path=relative.as_posix(),
                  category=_category_of(parts),
                  title=path.stem,
                  content=_BRAND_PATTERN.sub("Borough", raw),
                  is_complete=_INCOMPLETE_MARKER not in raw,
              )
          )
      return entries


  def _category_of(parts: tuple[str, ...]) -> str:
      for part in parts:
          domain = _DOMAIN_BY_DIRECTORY.get(part)
          if domain is not None:
              return domain
      return "UNKNOWN"


  async def _import(root: Path) -> int:
      settings = Settings()  # type: ignore[call-arg]
      database = Database(settings)
      entries = parse_wiki_tree(root)
      async with database.session() as session:
          repository = KnowledgeRepository(session)
          for entry in entries:
              await repository.upsert_by_source_path(
                  source_path=entry.source_path,
                  category=entry.category,
                  title=entry.title,
                  content=entry.content,
                  source="Borough 团队维护（自旧 Wiki 导入）",
                  is_complete=entry.is_complete,
              )
          await session.commit()
      return len(entries)


  def main() -> None:
      parser = argparse.ArgumentParser(description="导入旧 Wiki 到 knowledge_documents")
      parser.add_argument("--root", required=True, type=Path, help="llm-wiki 目录")
      args = parser.parse_args()
      count = asyncio.run(_import(args.root))
      print(f"已导入 {count} 篇知识文档")


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 4: 运行测试与门禁。**

  Run: `cd backend && uv run pytest tests/unit/knowledge/test_wiki_import.py -v`

  Expected: PASS，5 个测试。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

- [ ] **Step 5: 实跑一次导入并确认参考目录未被改动。**

  ```bash
  cd backend
  uv run python scripts/import_wiki.py --root "../yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki"
  cd .. && git status --short "yshopping-merchant-ai 4/"
  ```

  Expected: 打印已导入的篇数；`git status` 对参考目录**无任何输出**（R8：只读）。

---

### Task 5: LLM 协议、预算与 FakeLlmClient

**Files:**
- Create: `backend/app/llm/__init__.py`
- Create: `backend/app/llm/client.py`
- Create: `backend/app/llm/fake.py`
- Test: `backend/tests/unit/llm/test_fake_client.py`

**Interfaces:**
- Produces: `class LlmBudgetExceededError(Exception)`、`class LlmUnavailableError(Exception)`。
- Produces: `@dataclass LlmBudget(max_calls: int, max_tokens: int, calls: int = 0, tokens: int = 0)`，方法 `charge(tokens: int) -> None`。
- Produces: `@dataclass(frozen=True) LlmResult(text: str, tokens: int, degraded: bool)`。
- Produces: `class LlmClient(Protocol)`，方法 `is_configured() -> bool` 与 `async complete(*, system, user, fallback, budget) -> LlmResult`。
- Produces: `class FakeLlmClient`，构造参数 `behaviour: Literal["normal", "invalid_json", "timeout", "empty"]` 与 `responses: Sequence[str]`。

- [ ] **Step 1: 写失败的测试。**

  `backend/tests/unit/llm/test_fake_client.py`：

  ```python
  """FakeLlmClient 与预算。

  §B3 验收要求 Fake LLM 覆盖「正常、非法 JSON、超时、空响应」四种，
  逐一在这里钉住。所有单元测试都必须用它，不得联网（AGENTS.md R3）。
  """

  from __future__ import annotations

  import pytest

  from app.llm.client import LlmBudget, LlmBudgetExceededError, LlmUnavailableError
  from app.llm.fake import FakeLlmClient


  def _budget() -> LlmBudget:
      return LlmBudget(max_calls=3, max_tokens=1_000)


  @pytest.mark.asyncio
  async def test_正常返回预置文本() -> None:
      client = FakeLlmClient(responses=['{"answer_mode": "METRIC"}'])

      result = await client.complete(
          system="s", user="u", fallback="fb", budget=_budget()
      )

      assert result.text == '{"answer_mode": "METRIC"}'
      assert result.degraded is False


  @pytest.mark.asyncio
  async def test_非法_json_原样返回由调用方处理() -> None:
      client = FakeLlmClient(behaviour="invalid_json")

      result = await client.complete(
          system="s", user="u", fallback="fb", budget=_budget()
      )

      assert result.text == "这不是 JSON"
      assert result.degraded is False


  @pytest.mark.asyncio
  async def test_超时落到_fallback_并标记降级() -> None:
      client = FakeLlmClient(behaviour="timeout")

      result = await client.complete(
          system="s", user="u", fallback="兜底回答", budget=_budget()
      )

      assert result.text == "兜底回答"
      assert result.degraded is True


  @pytest.mark.asyncio
  async def test_空响应落到_fallback_并标记降级() -> None:
      client = FakeLlmClient(behaviour="empty")

      result = await client.complete(
          system="s", user="u", fallback="兜底回答", budget=_budget()
      )

      assert result.text == "兜底回答"
      assert result.degraded is True


  @pytest.mark.asyncio
  async def test_未配置时抛_unavailable() -> None:
      client = FakeLlmClient(configured=False)

      assert client.is_configured() is False
      with pytest.raises(LlmUnavailableError):
          await client.complete(system="s", user="u", fallback="fb", budget=_budget())


  @pytest.mark.asyncio
  async def test_超过调用次数上限时抛预算异常() -> None:
      client = FakeLlmClient(responses=["ok"] * 5)
      budget = LlmBudget(max_calls=2, max_tokens=1_000)

      await client.complete(system="s", user="u", fallback="fb", budget=budget)
      await client.complete(system="s", user="u", fallback="fb", budget=budget)

      with pytest.raises(LlmBudgetExceededError):
          await client.complete(system="s", user="u", fallback="fb", budget=budget)


  def test_超过_token_上限时抛预算异常() -> None:
      budget = LlmBudget(max_calls=10, max_tokens=100)

      budget.charge(60)

      with pytest.raises(LlmBudgetExceededError):
          budget.charge(60)
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/llm/ -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.llm'`。

- [ ] **Step 3: 实现协议与预算。**

  `backend/app/llm/__init__.py` 内容为空。

  `backend/app/llm/client.py`：

  ```python
  """LLM 协议与单请求预算。

  两个设计点沿用参考实现（LlmClient.java）：

  - `is_configured()`：没配密钥时整条链路仍要能跑通，只是回答降级；
  - `fallback` 是**入参**而不是异常：写调用的人在写下这一行时，就必须想清楚
    「模型不可用时这一步返回什么」。

  在此之上加了本项目方案 §B3 要求、参考实现没有的东西：单请求调用次数与
  token 上限。超限不是错误页，而是显式降级（AGENTS.md R7）。
  """

  from __future__ import annotations

  from dataclasses import dataclass
  from typing import Protocol


  class LlmUnavailableError(RuntimeError):
      """未配置密钥或适配器不可用。调用方应回落到 fallback。"""


  class LlmBudgetExceededError(RuntimeError):
      """单请求的调用次数或 token 超限。调用方应转成显式降级。"""


  @dataclass
  class LlmBudget:
      max_calls: int
      max_tokens: int
      calls: int = 0
      tokens: int = 0

      def charge_call(self) -> None:
          if self.calls >= self.max_calls:
              raise LlmBudgetExceededError(
                  f"单请求 LLM 调用次数已达上限 {self.max_calls}"
              )
          self.calls += 1

      def charge(self, tokens: int) -> None:
          if self.tokens + tokens > self.max_tokens:
              raise LlmBudgetExceededError(
                  f"单请求 LLM token 已达上限 {self.max_tokens}"
              )
          self.tokens += tokens


  @dataclass(frozen=True)
  class LlmResult:
      text: str
      tokens: int
      degraded: bool


  class LlmClient(Protocol):
      def is_configured(self) -> bool: ...

      async def complete(
          self,
          *,
          system: str,
          user: str,
          fallback: str,
          budget: LlmBudget,
      ) -> LlmResult: ...
  ```

- [ ] **Step 4: 实现 FakeLlmClient。**

  `backend/app/llm/fake.py`：

  ```python
  """测试替身。所有单元测试都用它，绝不联网（AGENTS.md R3）。"""

  from __future__ import annotations

  from collections.abc import Sequence
  from typing import Literal

  from app.llm.client import (
      LlmBudget,
      LlmResult,
      LlmUnavailableError,
  )

  Behaviour = Literal["normal", "invalid_json", "timeout", "empty"]


  class FakeLlmClient:
      """四种行为对应 §B3 验收要求的四类：正常、非法 JSON、超时、空响应。"""

      def __init__(
          self,
          *,
          behaviour: Behaviour = "normal",
          responses: Sequence[str] = (),
          configured: bool = True,
          tokens_per_call: int = 10,
      ) -> None:
          self._behaviour = behaviour
          self._responses = list(responses)
          self._configured = configured
          self._tokens_per_call = tokens_per_call
          self.calls: list[tuple[str, str]] = []

      def is_configured(self) -> bool:
          return self._configured

      async def complete(
          self,
          *,
          system: str,
          user: str,
          fallback: str,
          budget: LlmBudget,
      ) -> LlmResult:
          if not self._configured:
              raise LlmUnavailableError("FakeLlmClient 被构造为未配置")

          budget.charge_call()
          budget.charge(self._tokens_per_call)
          self.calls.append((system, user))

          if self._behaviour == "invalid_json":
              return LlmResult(text="这不是 JSON", tokens=self._tokens_per_call, degraded=False)
          if self._behaviour in {"timeout", "empty"}:
              # 两者对调用方是同一件事：拿不到可用输出，落 fallback 并标记降级。
              return LlmResult(text=fallback, tokens=self._tokens_per_call, degraded=True)

          text = self._responses.pop(0) if self._responses else fallback
          return LlmResult(text=text, tokens=self._tokens_per_call, degraded=not self._responses and not text)
  ```

- [ ] **Step 5: 运行测试与门禁。**

  Run: `cd backend && uv run pytest tests/unit/llm/ -v`

  Expected: PASS，7 个测试。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 6: `QueryIntent` 与三套白名单

**Files:**
- Create: `backend/app/intent/__init__.py`
- Create: `backend/app/intent/models.py`
- Create: `backend/app/intent/whitelist.py`
- Test: `backend/tests/unit/intent/test_whitelist.py`

**Interfaces:**
- Produces: `class DateRange(BaseModel)` 字段 `start: date`、`end: date`。
- Produces: `class QueryIntent(BaseModel)` 字段 `answer_mode`、`category`、`metric: str | None`、`dimensions: list[str]`、`filters: dict[str, str]`、`date_range: DateRange | None`、`sort: str | None`、`limit: int | None`、`followup_reference: bool`、`needs_attachment: bool`。
- Produces: `METRIC_WHITELIST: frozenset[str]`、`DIMENSION_WHITELIST: frozenset[str]`、`FILTER_WHITELIST: frozenset[str]`、`MAX_QUERY_DAYS: int = 180`、`MAX_DETAIL_LIMIT: int = 200`。
- Produces: `@dataclass(frozen=True) IntentValidation(intent: QueryIntent, rejected: tuple[str, ...], adjusted: tuple[str, ...])`。
- Produces: `validate_intent(intent: QueryIntent, *, today: date) -> IntentValidation`。

- [ ] **Step 1: 写失败的白名单测试。**

  `backend/tests/unit/intent/test_whitelist.py`：

  ```python
  """意图白名单校验。

  五条红线各一个反例。前三条是拒绝，后两条是**后端覆盖**——用户不该因为问了
  「最近两年」就拿到一个错误页，参考实现同样是截断而不是报错。
  """

  from __future__ import annotations

  from datetime import date

  from app.intent.models import DateRange, QueryIntent
  from app.intent.whitelist import (
      MAX_DETAIL_LIMIT,
      MAX_QUERY_DAYS,
      METRIC_WHITELIST,
      validate_intent,
  )
  from app.schemas.chat import AnswerMode, QuestionCategory

  TODAY = date(2026, 8, 4)


  def _intent(**overrides: object) -> QueryIntent:
      base: dict[str, object] = {
          "answer_mode": AnswerMode.METRIC,
          "category": QuestionCategory.TRADE,
          "metric": "order_gmv_amt_1d",
          "dimensions": [],
          "filters": {},
          "date_range": DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
          "sort": None,
          "limit": None,
          "followup_reference": False,
          "needs_attachment": False,
      }
      base.update(overrides)
      return QueryIntent(**base)  # type: ignore[arg-type]


  def test_合法意图原样通过() -> None:
      result = validate_intent(_intent(), today=TODAY)

      assert result.rejected == ()
      assert result.intent.metric == "order_gmv_amt_1d"


  def test_拒绝_sql_字符串() -> None:
      result = validate_intent(_intent(metric="SELECT * FROM orders"), today=TODAY)

      assert any("SQL" in reason for reason in result.rejected)
      assert result.intent.answer_mode is AnswerMode.INVALID


  def test_拒绝中文指标名() -> None:
      # 模型输出中文变体（空格、简繁、同义词）会造成漏命中，只接受 metric_code。
      result = validate_intent(_intent(metric="成交金额"), today=TODAY)

      assert any("metric_code" in reason for reason in result.rejected)
      assert result.intent.answer_mode is AnswerMode.INVALID


  def test_拒绝非白名单维度() -> None:
      result = validate_intent(_intent(dimensions=["seller_secret"]), today=TODAY)

      assert any("维度" in reason for reason in result.rejected)


  def test_拒绝非白名单筛选字段() -> None:
      result = validate_intent(_intent(filters={"seller_secret": "x"}), today=TODAY)

      assert any("筛选" in reason for reason in result.rejected)


  def test_超过_180_天被截断而不是报错() -> None:
      result = validate_intent(
          _intent(date_range=DateRange(start=date(2024, 1, 1), end=TODAY)),
          today=TODAY,
      )

      assert result.rejected == ()
      assert result.intent.date_range is not None
      span = (result.intent.date_range.end - result.intent.date_range.start).days + 1
      assert span == MAX_QUERY_DAYS
      assert any("日期" in note for note in result.adjusted)


  def test_超过_limit_上限被覆盖而不是报错() -> None:
      result = validate_intent(
          _intent(answer_mode=AnswerMode.DETAIL, limit=100_000), today=TODAY
      )

      assert result.rejected == ()
      assert result.intent.limit == MAX_DETAIL_LIMIT
      assert any("limit" in note for note in result.adjusted)


  def test_指标白名单与指标表_seed_同源() -> None:
      # 白名单漂移是隐蔽故障：表里有而白名单没有，指标查询会静默失败。
      from app.metrics.seed import METRIC_SEED

      assert {item.metric_code for item in METRIC_SEED} == set(METRIC_WHITELIST)
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/intent/ -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.intent'`。最后一个测试还会因 `app.metrics.seed` 不存在而失败——那是 Task 8 的产出，本 Task 结束时它仍应失败。

  **本 Task 只要求前 7 个测试通过。** 在最后一个测试上加 `@pytest.mark.xfail(reason="METRIC_SEED 属 Task 8", strict=True)`，Task 8 再移除该标记。

- [ ] **Step 3: 实现意图模型。**

  `backend/app/intent/__init__.py` 内容为空。

  `backend/app/intent/models.py`：

  ```python
  """结构化意图。

  这是 LLM 输出的唯一落点：模型不产生 SQL、不产生表名，只填这些字段
  （AGENTS.md R4）。字段集合来自后端方案 §6.2。
  """

  from __future__ import annotations

  from datetime import date

  from pydantic import BaseModel, ConfigDict, Field

  from app.schemas.chat import AnswerMode, QuestionCategory


  class DateRange(BaseModel):
      model_config = ConfigDict(extra="forbid")

      start: date
      end: date


  class QueryIntent(BaseModel):
      # extra="forbid"：模型多吐一个字段就是契约漂移，要在解析阶段炸掉，
      # 而不是被静默丢弃。
      model_config = ConfigDict(extra="forbid")

      answer_mode: AnswerMode
      category: QuestionCategory
      metric: str | None = None
      dimensions: list[str] = Field(default_factory=list)
      filters: dict[str, str] = Field(default_factory=dict)
      date_range: DateRange | None = None
      sort: str | None = None
      limit: int | None = None
      followup_reference: bool = False
      needs_attachment: bool = False
  ```

- [ ] **Step 4: 实现白名单与校验。**

  `backend/app/intent/whitelist.py`：

  ```python
  """三套白名单与意图校验。

  白名单是**代码常量**，不入库、不接受运行时修改——与参考实现
  （DorisQueryService.PROFILE_METRIC_COLUMNS 等）的归属一致。

  **B4 必须在查询层再校验一次。** 参考实现在 queryMetric 里留了原因：指标列会
  被拼进 SQL 的标识符位置，那里无法参数化绑定。意图层校验过不等于查询层可以
  省——两处都要有。
  """

  from __future__ import annotations

  import re
  from dataclasses import dataclass
  from datetime import date, timedelta
  from typing import Final

  from app.intent.models import DateRange, QueryIntent
  from app.schemas.chat import AnswerMode

  #: 日期跨度上限。参考实现是 365 天；本项目取 180 天与演示数据天数对齐，
  #: 避免出现「允许查询但没有数据」的区间（后端方案 §6.3）。
  MAX_QUERY_DAYS: Final[int] = 180
  MAX_DETAIL_LIMIT: Final[int] = 200

  METRIC_WHITELIST: Final[frozenset[str]] = frozenset(
      {
          "order_gmv_amt_1d",
          "order_cnt_1d",
          "order_user_cnt_1d",
          "avg_pay_order_amt_1d",
          "trade_success_gmv_amt_1d",
          "trade_success_order_cnt_1d",
          "refund_amt_1d",
          "refund_rate_1d",
          "return_success_cnt_1d",
          "return_cnt_1d",
          "cs_ticket_cnt_1d",
          "avg_ticket_score_1d",
          "seller_repay_amt_1d",
          "coupon_discount_amt_1d",
          "goods_online_cnt_1d",
          "goods_audit_reject_cnt_1d",
          "appeal_cnt_1d",
          "scm_performance_cnt_1d",
      }
  )

  DIMENSION_WHITELIST: Final[frozenset[str]] = frozenset({"pt", "spu_id", "address_city_name"})
  FILTER_WHITELIST: Final[frozenset[str]] = frozenset({"spu_id", "address_city_name", "pt"})

  _SQL_PATTERN = re.compile(
      r"\b(select|insert|update|delete|drop|union|from|where|join)\b", re.IGNORECASE
  )
  _METRIC_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


  @dataclass(frozen=True)
  class IntentValidation:
      intent: QueryIntent
      #: 触碰红线，本轮转为 INVALID。
      rejected: tuple[str, ...]
      #: 被后端覆盖但仍继续，需要在 quality_notes 里告知用户。
      adjusted: tuple[str, ...]


  def validate_intent(intent: QueryIntent, *, today: date) -> IntentValidation:
      rejected: list[str] = []
      adjusted: list[str] = []
      data = intent.model_dump()

      metric = intent.metric
      if metric is not None:
          if _SQL_PATTERN.search(metric):
              rejected.append("指标字段含 SQL 关键字，拒绝执行")
          elif not _METRIC_CODE_PATTERN.match(metric):
              rejected.append("指标必须是英文 metric_code，不接受中文指标名")
          elif metric not in METRIC_WHITELIST:
              rejected.append(f"指标 {metric} 不在白名单内")

      for dimension in intent.dimensions:
          if dimension not in DIMENSION_WHITELIST:
              rejected.append(f"维度 {dimension} 不在白名单内")

      for field in intent.filters:
          if field not in FILTER_WHITELIST:
              rejected.append(f"筛选字段 {field} 不在白名单内")

      if intent.date_range is not None:
          span = (intent.date_range.end - intent.date_range.start).days + 1
          if span > MAX_QUERY_DAYS:
              # 截断而不是报错：用户问「最近两年」不该拿到一个错误页。
              data["date_range"] = DateRange(
                  start=intent.date_range.end - timedelta(days=MAX_QUERY_DAYS - 1),
                  end=intent.date_range.end,
              ).model_dump()
              adjusted.append(f"日期范围超过 {MAX_QUERY_DAYS} 天，已截断为最近 {MAX_QUERY_DAYS} 天")

      if intent.limit is not None and intent.limit > MAX_DETAIL_LIMIT:
          data["limit"] = MAX_DETAIL_LIMIT
          adjusted.append(f"limit 超过上限，已覆盖为 {MAX_DETAIL_LIMIT}")

      if rejected:
          data["answer_mode"] = AnswerMode.INVALID

      return IntentValidation(
          intent=QueryIntent.model_validate(data),
          rejected=tuple(rejected),
          adjusted=tuple(adjusted),
      )
  ```

- [ ] **Step 5: 运行测试与门禁。**

  Run: `cd backend && uv run pytest tests/unit/intent/ -v`

  Expected: 7 passed, 1 xfailed。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 7: 指标目录与 Seed

**Files:**
- Create: `backend/app/metrics/__init__.py`
- Create: `backend/app/metrics/seed.py`
- Create: `backend/app/metrics/catalog.py`
- Create: `backend/app/repositories/metric.py`
- Create: `backend/migrations/versions/20260804_0003_metric_seed.py`
- Test: `backend/tests/unit/metrics/test_catalog.py`
- Modify: `backend/tests/unit/intent/test_whitelist.py`（移除 xfail 标记）

**Interfaces:**
- Consumes: Task 5 的 `LlmClient`/`LlmBudget`、Task 6 的 `QueryIntent`。
- Produces: `@dataclass(frozen=True) MetricSeedItem(metric_code, display_name, unit, business_definition, sql_definition, source, owner)`、`METRIC_SEED: tuple[MetricSeedItem, ...]`。
- Produces: `@dataclass(frozen=True) MetricPayload(metric_code, display_name, unit, definition, source, owner, status, generated, notice)`。
- Produces: `GENERATED_NOTICE: str`。
- Produces: `MetricRepository(session).get_by_code(metric_code: str) -> MetricDefinition | None`。
- Produces: `MetricCatalog(repository, llm).resolve(intent, knowledge_text, budget) -> MetricPayload | None`。

- [ ] **Step 1: 写失败的指标目录测试。**

  `backend/tests/unit/metrics/test_catalog.py`：

  ```python
  """指标口径三级检索。

  三级顺序沿用参考实现 MetricDefinitionService.resolve()：
  正式指标 → 字段注释 → LLM 生成。第三级的产物必须显式标注待核验。
  """

  from __future__ import annotations

  import json

  import pytest

  from app.intent.models import QueryIntent
  from app.llm.client import LlmBudget
  from app.llm.fake import FakeLlmClient
  from app.metrics.catalog import GENERATED_NOTICE, MetricCatalog
  from app.schemas.chat import AnswerMode, QuestionCategory


  class _FakeMetricRow:
      def __init__(self, metric_code: str) -> None:
          self.metric_code = metric_code
          self.display_name = "支付成交额"
          self.unit = "元"
          self.business_definition = "统计口径说明"
          self.sql_definition = "SUM(order_gmv_amt_1d)"
          self.source = "Borough 指标目录"
          self.owner = "经营分析组"
          self.status = "ACTIVE"


  class _FakeMetricRepository:
      def __init__(self, rows: dict[str, _FakeMetricRow]) -> None:
          self._rows = rows

      async def get_by_code(self, metric_code: str) -> _FakeMetricRow | None:
          return self._rows.get(metric_code)


  def _intent(metric: str | None) -> QueryIntent:
      return QueryIntent(
          answer_mode=AnswerMode.METRIC,
          category=QuestionCategory.TRADE,
          metric=metric,
      )


  def _budget() -> LlmBudget:
      return LlmBudget(max_calls=3, max_tokens=1_000)


  @pytest.mark.asyncio
  async def test_一级命中正式指标表不调用_llm() -> None:
      llm = FakeLlmClient(responses=["不该被用到"])
      catalog = MetricCatalog(
          _FakeMetricRepository({"order_gmv_amt_1d": _FakeMetricRow("order_gmv_amt_1d")}),
          llm,
      )

      payload = await catalog.resolve(_intent("order_gmv_amt_1d"), "", _budget())

      assert payload is not None
      assert payload.generated is False
      assert payload.status == "ACTIVE"
      assert llm.calls == []


  @pytest.mark.asyncio
  async def test_三级由_llm_生成且标注待核验() -> None:
      generated = json.dumps(
          {"display_name": "临时口径", "unit": "单", "definition": "由模型生成"},
          ensure_ascii=False,
      )
      catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient(responses=[generated]))

      payload = await catalog.resolve(_intent("unknown_metric_1d"), "知识正文", _budget())

      assert payload is not None
      assert payload.generated is True
      assert payload.status == "UNVERIFIED"
      assert payload.notice == GENERATED_NOTICE
      assert "yshopping" not in payload.notice.lower()


  @pytest.mark.asyncio
  async def test_非指标模式不解析口径() -> None:
      catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient())

      payload = await catalog.resolve(
          QueryIntent(answer_mode=AnswerMode.CHAT, category=QuestionCategory.UNKNOWN),
          "",
          _budget(),
      )

      assert payload is None


  @pytest.mark.asyncio
  async def test_llm_返回非法_json_时不产出口径而不是崩溃() -> None:
      catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient(behaviour="invalid_json"))

      payload = await catalog.resolve(_intent("unknown_metric_1d"), "", _budget())

      assert payload is None
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/metrics/ -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.metrics'`。

- [ ] **Step 3: 实现 Seed。**

  `backend/app/metrics/__init__.py` 内容为空。

  `backend/app/metrics/seed.py`：

  ```python
  """指标 Seed。

  metric_code 是白名单、接口路径和内部引用的唯一键；中文名只用于展示，
  不参与匹配（后端方案 §6.4）。本文件与 app/intent/whitelist.py 的
  METRIC_WHITELIST 必须逐字一致，测试会校验。
  """

  from __future__ import annotations

  from dataclasses import dataclass
  from typing import Final


  @dataclass(frozen=True)
  class MetricSeedItem:
      metric_code: str
      display_name: str
      unit: str
      business_definition: str
      sql_definition: str
      source: str
      owner: str


  def _item(
      metric_code: str, display_name: str, unit: str, definition: str, sql: str
  ) -> MetricSeedItem:
      return MetricSeedItem(
          metric_code=metric_code,
          display_name=display_name,
          unit=unit,
          business_definition=definition,
          sql_definition=sql,
          source="Borough 指标目录",
          owner="经营分析组",
      )


  METRIC_SEED: Final[tuple[MetricSeedItem, ...]] = (
      _item("order_gmv_amt_1d", "下单 GMV", "元", "当日下单口径成交额。", "SUM(order_gmv_amt_1d)"),
      _item("order_cnt_1d", "下单量", "单", "当日下单订单数。", "SUM(order_cnt_1d)"),
      _item("order_user_cnt_1d", "下单人数", "人", "当日下单去重用户数。", "SUM(order_user_cnt_1d)"),
      _item("avg_pay_order_amt_1d", "客单价", "元", "当日支付订单平均金额。", "SUM(avg_pay_order_amt_1d)"),
      _item("trade_success_gmv_amt_1d", "成交 GMV", "元", "当日交易成功口径成交额。", "SUM(trade_success_gmv_amt_1d)"),
      _item("trade_success_order_cnt_1d", "成交订单量", "单", "当日交易成功订单数。", "SUM(trade_success_order_cnt_1d)"),
      _item("refund_amt_1d", "退款金额", "元", "当日退款总金额。", "SUM(refund_amt_1d)"),
      _item("refund_rate_1d", "退款率", "%", "当日退款金额占成交额比例。", "SUM(refund_rate_1d)"),
      _item("return_success_cnt_1d", "退货成功量", "单", "当日退货成功单量。", "SUM(return_success_cnt_1d)"),
      _item("return_cnt_1d", "退货量", "单", "当日发起退货单量。", "SUM(return_cnt_1d)"),
      _item("cs_ticket_cnt_1d", "客服工单量", "单", "当日新建客服工单数。", "SUM(cs_ticket_cnt_1d)"),
      _item("avg_ticket_score_1d", "工单满意度", "分", "当日客服工单平均评分。", "SUM(avg_ticket_score_1d)"),
      _item("seller_repay_amt_1d", "商家赔付金额", "元", "当日商家赔付总额。", "SUM(seller_repay_amt_1d)"),
      _item("coupon_discount_amt_1d", "优惠券优惠金额", "元", "当日优惠券抵扣总额。", "SUM(coupon_discount_amt_1d)"),
      _item("goods_online_cnt_1d", "在架商品数", "个", "当日在架商品数量。", "SUM(goods_online_cnt_1d)"),
      _item("goods_audit_reject_cnt_1d", "商品审核驳回量", "个", "当日商品审核驳回数。", "SUM(goods_audit_reject_cnt_1d)"),
      _item("appeal_cnt_1d", "申诉量", "次", "当日商家申诉发起次数。", "SUM(appeal_cnt_1d)"),
      _item("scm_performance_cnt_1d", "供应链履约量", "单", "当日供应链履约单量。", "SUM(scm_performance_cnt_1d)"),
  )
  ```

- [ ] **Step 4: 实现指标目录。**

  `backend/app/metrics/catalog.py`：

  ```python
  """指标口径三级检索。

  顺序与参考实现 MetricDefinitionService.resolve() 一致：
  正式指标表 → 内置字段映射 → LLM 生成候选。

  第三级的产物必须 generated=True、status='UNVERIFIED'、带待核验文案，
  且**不写入正式指标表**（后端方案 §6.4）。前端 F2 已实现的降级提示条会直接
  展示这条信息。
  """

  from __future__ import annotations

  import json
  from dataclasses import dataclass
  from typing import Final, Protocol

  from app.intent.models import QueryIntent
  from app.llm.client import LlmBudget, LlmBudgetExceededError, LlmClient, LlmUnavailableError
  from app.schemas.chat import AnswerMode

  GENERATED_NOTICE: Final[str] = (
      "该指标口径未命中正式指标目录或字段注释，"
      "以下内容由大模型根据当前问题生成，仅供参考，请以正式指标口径为准。"
  )

  _SYSTEM_PROMPT = "你是 Borough 商家 AI 助手的指标口径助理，只输出 JSON。"


  @dataclass(frozen=True)
  class MetricPayload:
      metric_code: str
      display_name: str
      unit: str
      definition: str
      source: str
      owner: str
      status: str
      generated: bool
      notice: str | None


  class _MetricRowLike(Protocol):
      metric_code: str
      display_name: str
      unit: str
      business_definition: str
      source: str
      owner: str
      status: str


  class _MetricRepositoryLike(Protocol):
      async def get_by_code(self, metric_code: str) -> _MetricRowLike | None: ...


  class MetricCatalog:
      def __init__(self, repository: _MetricRepositoryLike, llm: LlmClient) -> None:
          self._repository = repository
          self._llm = llm

      async def resolve(
          self,
          intent: QueryIntent,
          knowledge_text: str,
          budget: LlmBudget,
      ) -> MetricPayload | None:
          if intent.answer_mode is not AnswerMode.METRIC or intent.metric is None:
              return None

          row = await self._repository.get_by_code(intent.metric)
          if row is not None:
              return MetricPayload(
                  metric_code=row.metric_code,
                  display_name=row.display_name,
                  unit=row.unit,
                  definition=row.business_definition,
                  source=row.source,
                  owner=row.owner,
                  status=row.status,
                  generated=False,
                  notice=None,
              )

          return await self._generate(intent.metric, knowledge_text, budget)

      async def _generate(
          self,
          metric_code: str,
          knowledge_text: str,
          budget: LlmBudget,
      ) -> MetricPayload | None:
          user_prompt = (
              f"指标标识：{metric_code}\n"
              f"可用知识：\n{knowledge_text}\n\n"
              '只输出 JSON，字段为 display_name、unit、definition。'
          )
          try:
              result = await self._llm.complete(
                  system=_SYSTEM_PROMPT,
                  user=user_prompt,
                  fallback="",
                  budget=budget,
              )
          except (LlmUnavailableError, LlmBudgetExceededError):
              # 模型不可用或预算耗尽不是崩溃点：没有口径就不展示口径面板。
              return None

          try:
              payload = json.loads(result.text)
          except json.JSONDecodeError:
              return None
          if not isinstance(payload, dict):
              return None

          return MetricPayload(
              metric_code=metric_code,
              display_name=str(payload.get("display_name", metric_code)),
              unit=str(payload.get("unit", "")),
              definition=str(payload.get("definition", "")),
              source="大模型生成",
              owner="待认领",
              status="UNVERIFIED",
              generated=True,
              notice=GENERATED_NOTICE,
          )
  ```

- [ ] **Step 5: 实现指标仓储。**

  `backend/app/repositories/metric.py`：

  ```python
  """指标定义仓储。

  指标目录对所有商家一致，不含商家数据，因此不做 merchant_id 过滤——
  与 KnowledgeRepository 同理，与 ConversationRepository 的隔离要求不同。
  """

  from __future__ import annotations

  from sqlalchemy import select
  from sqlalchemy.ext.asyncio import AsyncSession

  from app.models.knowledge import MetricDefinition


  class MetricRepository:
      def __init__(self, session: AsyncSession) -> None:
          self._session = session

      async def get_by_code(self, metric_code: str) -> MetricDefinition | None:
          statement = select(MetricDefinition).where(
              MetricDefinition.metric_code == metric_code,
              MetricDefinition.status != "DEPRECATED",
          )
          return (await self._session.execute(statement)).scalar_one_or_none()
  ```

- [ ] **Step 6: 写 Seed 迁移。**

  Run: `cd backend && uv run alembic revision -m "metric seed"`，重命名为 `20260804_0003_metric_seed.py`，`upgrade()` 用 `op.bulk_insert` 写入 `METRIC_SEED` 的 18 条（`status='ACTIVE'`），`downgrade()` 按 `metric_code` 删除同样 18 条。迁移内 `from app.metrics.seed import METRIC_SEED` 以避免手抄。

- [ ] **Step 7: 移除 Task 6 的 xfail 标记。**

  删除 `tests/unit/intent/test_whitelist.py` 中 `test_指标白名单与指标表_seed_同源` 上的 `@pytest.mark.xfail(...)`。

- [ ] **Step 8: 运行测试与门禁。**

  Run: `cd backend && uv run alembic upgrade head && uv run pytest tests/unit/metrics/ tests/unit/intent/ -v`

  Expected: PASS，4 + 8 个测试，无 xfail。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 8: 两阶段意图服务

**Files:**
- Create: `backend/app/intent/prompts.py`
- Create: `backend/app/intent/service.py`
- Test: `backend/tests/unit/intent/test_service.py`

**Interfaces:**
- Consumes: Task 3 的 `KnowledgeRetrieval`、Task 5 的 `LlmClient`/`LlmBudget`、Task 6 的 `QueryIntent`/`validate_intent`。
- Produces: `@dataclass(frozen=True) InitialIntent(answer_mode, category, intent_keywords: tuple[str, ...], llm_analyzed: bool)`。
- Produces: `@dataclass(frozen=True) IntentOutcome(intent: QueryIntent, validation: IntentValidation, notes: tuple[str, ...], degraded: bool)`。
- Produces: `IntentService(llm).recognize(question, index_text, budget) -> InitialIntent`。
- Produces: `IntentService(llm).understand(question, initial, knowledge_text, budget, today) -> IntentOutcome`。
- Produces: `MAX_INTENT_RETRIES: int = 2`。

- [ ] **Step 1: 写失败的意图服务测试。**

  `backend/tests/unit/intent/test_service.py`：

  ```python
  """两阶段意图。

  阶段一（分类）拿索引层知识，阶段二（理解）拿正文层知识——顺序颠倒会让分类
  失去业务词汇上下文（后端方案 §6.5）。
  """

  from __future__ import annotations

  import json
  from datetime import date

  import pytest

  from app.intent.service import MAX_INTENT_RETRIES, IntentService
  from app.llm.client import LlmBudget
  from app.llm.fake import FakeLlmClient
  from app.schemas.chat import AnswerMode, QuestionCategory

  TODAY = date(2026, 8, 4)


  def _budget() -> LlmBudget:
      return LlmBudget(max_calls=10, max_tokens=10_000)


  def _classify(mode: str, category: str, keywords: list[str]) -> str:
      return json.dumps(
          {"answer_mode": mode, "category": category, "intent_keywords": keywords},
          ensure_ascii=False,
      )


  def _understand(**fields: object) -> str:
      payload: dict[str, object] = {
          "answer_mode": "METRIC",
          "category": "TRADE",
          "metric": "order_gmv_amt_1d",
          "dimensions": [],
          "filters": {},
          "date_range": {"start": "2026-08-01", "end": "2026-08-03"},
          "sort": None,
          "limit": None,
          "followup_reference": False,
          "needs_attachment": False,
      }
      payload.update(fields)
      return json.dumps(payload, ensure_ascii=False)


  @pytest.mark.asyncio
  async def test_分类阶段解析出模式分类与关键词() -> None:
      llm = FakeLlmClient(responses=[_classify("METRIC", "TRADE", ["GMV", "成交额"])])
      service = IntentService(llm)

      initial = await service.recognize("昨天总 GMV 是多少？", "索引知识", _budget())

      assert initial.answer_mode is AnswerMode.METRIC
      assert initial.category is QuestionCategory.TRADE
      assert initial.intent_keywords == ("GMV", "成交额")
      assert initial.llm_analyzed is True


  @pytest.mark.asyncio
  async def test_分类阶段拿到的是索引层知识() -> None:
      llm = FakeLlmClient(responses=[_classify("CHAT", "UNKNOWN", [])])
      service = IntentService(llm)

      await service.recognize("你好", "这是索引层文本", _budget())

      assert "这是索引层文本" in llm.calls[0][1]


  @pytest.mark.asyncio
  async def test_理解阶段产出通过校验的意图() -> None:
      llm = FakeLlmClient(responses=[_classify("METRIC", "TRADE", ["GMV"]), _understand()])
      service = IntentService(llm)
      initial = await service.recognize("昨天总 GMV", "索引", _budget())

      outcome = await service.understand("昨天总 GMV", initial, "正文知识", _budget(), TODAY)

      assert outcome.intent.metric == "order_gmv_amt_1d"
      assert outcome.validation.rejected == ()
      assert outcome.degraded is False


  @pytest.mark.asyncio
  async def test_非法_json_重试后仍失败则降级为_chat() -> None:
      llm = FakeLlmClient(behaviour="invalid_json")
      service = IntentService(llm)
      initial = await service.recognize("你好", "索引", _budget())

      outcome = await service.understand("你好", initial, "正文", _budget(), TODAY)

      assert outcome.degraded is True
      assert outcome.intent.answer_mode is AnswerMode.CHAT
      assert any("解析" in note for note in outcome.notes)


  @pytest.mark.asyncio
  async def test_重试次数不超过上限() -> None:
      llm = FakeLlmClient(behaviour="invalid_json")
      service = IntentService(llm)
      budget = _budget()
      initial = await service.recognize("你好", "索引", budget)
      calls_after_classify = len(llm.calls)

      await service.understand("你好", initial, "正文", budget, TODAY)

      assert len(llm.calls) - calls_after_classify == MAX_INTENT_RETRIES + 1


  @pytest.mark.asyncio
  async def test_输出_sql_字符串被拒并转为_invalid() -> None:
      llm = FakeLlmClient(responses=[_understand(metric="SELECT 1 FROM orders")])
      service = IntentService(llm)
      initial = await service.recognize("随便问问", "索引", _budget())

      outcome = await service.understand("随便问问", initial, "正文", _budget(), TODAY)

      assert outcome.intent.answer_mode is AnswerMode.INVALID
      assert outcome.validation.rejected != ()


  @pytest.mark.asyncio
  async def test_超期日期被截断并记入_notes() -> None:
      llm = FakeLlmClient(
          responses=[_understand(date_range={"start": "2024-01-01", "end": "2026-08-04"})]
      )
      service = IntentService(llm)
      initial = await service.recognize("两年 GMV", "索引", _budget())

      outcome = await service.understand("两年 GMV", initial, "正文", _budget(), TODAY)

      assert outcome.intent.answer_mode is AnswerMode.METRIC
      assert any("日期" in note for note in outcome.notes)
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/intent/test_service.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.intent.service'`。

- [ ] **Step 3: 实现 prompts。**

  `backend/app/intent/prompts.py`：

  ```python
  """意图识别的两个 prompt。

  话术使用 Borough，不得残留旧品牌（AGENTS.md「命名与品牌」）。
  两个 prompt 都要求「只输出 JSON」——解析失败会触发有限重试。
  """

  from __future__ import annotations

  from typing import Final

  from app.intent.whitelist import (
      DIMENSION_WHITELIST,
      FILTER_WHITELIST,
      MAX_DETAIL_LIMIT,
      MAX_QUERY_DAYS,
      METRIC_WHITELIST,
  )

  CLASSIFY_SYSTEM: Final[str] = (
      "你是 Borough 商家 AI 助手的意图分类器。只输出 JSON，不要解释。"
  )

  UNDERSTAND_SYSTEM: Final[str] = (
      "你是 Borough 商家 AI 助手的结构化理解器。只输出 JSON，不要解释。"
      "禁止输出 SQL、表名或任何查询语句。"
  )


  def classify_user_prompt(question: str, index_text: str) -> str:
      return (
          f"业务索引：\n{index_text}\n\n"
          f"商家问题：{question}\n\n"
          "输出 JSON，字段：\n"
          "- answer_mode：METRIC / DETAIL / RULE / IDENTITY / CHAT / INVALID 之一\n"
          "- category：PLATFORM_RULE / TRADE / REFUND / CS_TICKET / COMPENSATION / "
          "COUPON / GOODS / MERCHANT_OTHER / IDENTITY / SCM / UNKNOWN 之一\n"
          "- intent_keywords：字符串数组，问题里的业务词"
      )


  def understand_user_prompt(question: str, category: str, knowledge_text: str) -> str:
      return (
          f"业务域：{category}\n"
          f"业务知识：\n{knowledge_text}\n\n"
          f"商家问题：{question}\n\n"
          "输出 JSON，字段：answer_mode、category、metric、dimensions、filters、"
          "date_range（含 start 与 end，格式 YYYY-MM-DD）、sort、limit、"
          "followup_reference、needs_attachment。\n"
          f"metric 只能取：{sorted(METRIC_WHITELIST)}\n"
          f"dimensions 只能取：{sorted(DIMENSION_WHITELIST)}\n"
          f"filters 的键只能取：{sorted(FILTER_WHITELIST)}\n"
          f"日期跨度不超过 {MAX_QUERY_DAYS} 天，limit 不超过 {MAX_DETAIL_LIMIT}。\n"
          "禁止输出中文指标名，禁止输出 SQL。"
      )
  ```

- [ ] **Step 4: 实现意图服务。**

  `backend/app/intent/service.py`：

  ```python
  """两阶段意图：分类 → 理解 → 校验。

  参考实现的 recognizeIntent 同样是两阶段（analyze → refine），中间夹一次按
  category + intentKeywords 的正文检索。本项目在此之上加了 Pydantic 严格校验
  与有限重试（后端方案 §B3），参考实现只有 fallback 兜底。
  """

  from __future__ import annotations

  import json
  from dataclasses import dataclass
  from datetime import date
  from typing import Final

  from pydantic import ValidationError

  from app.intent.models import QueryIntent
  from app.intent.prompts import (
      CLASSIFY_SYSTEM,
      UNDERSTAND_SYSTEM,
      classify_user_prompt,
      understand_user_prompt,
  )
  from app.intent.whitelist import IntentValidation, validate_intent
  from app.llm.client import (
      LlmBudget,
      LlmBudgetExceededError,
      LlmClient,
      LlmUnavailableError,
  )
  from app.schemas.chat import AnswerMode, QuestionCategory

  #: 解析失败的额外重试次数。总调用次数 = 1 + MAX_INTENT_RETRIES。
  MAX_INTENT_RETRIES: Final[int] = 2


  @dataclass(frozen=True)
  class InitialIntent:
      answer_mode: AnswerMode
      category: QuestionCategory
      intent_keywords: tuple[str, ...]
      llm_analyzed: bool


  @dataclass(frozen=True)
  class IntentOutcome:
      intent: QueryIntent
      validation: IntentValidation
      notes: tuple[str, ...]
      degraded: bool


  _CHAT_FALLBACK = InitialIntent(
      answer_mode=AnswerMode.CHAT,
      category=QuestionCategory.UNKNOWN,
      intent_keywords=(),
      llm_analyzed=False,
  )


  class IntentService:
      def __init__(self, llm: LlmClient) -> None:
          self._llm = llm

      async def recognize(
          self,
          question: str,
          index_text: str,
          budget: LlmBudget,
      ) -> InitialIntent:
          """阶段一：拿索引层知识做分类与拆词。"""

          try:
              result = await self._llm.complete(
                  system=CLASSIFY_SYSTEM,
                  user=classify_user_prompt(question, index_text),
                  fallback="",
                  budget=budget,
              )
          except (LlmUnavailableError, LlmBudgetExceededError):
              return _CHAT_FALLBACK

          payload = _load_object(result.text)
          if payload is None:
              return _CHAT_FALLBACK

          return InitialIntent(
              answer_mode=_enum(AnswerMode, payload.get("answer_mode"), AnswerMode.CHAT),
              category=_enum(
                  QuestionCategory, payload.get("category"), QuestionCategory.UNKNOWN
              ),
              intent_keywords=tuple(
                  str(item) for item in payload.get("intent_keywords", []) if str(item).strip()
              ),
              llm_analyzed=True,
          )

      async def understand(
          self,
          question: str,
          initial: InitialIntent,
          knowledge_text: str,
          budget: LlmBudget,
          today: date,
      ) -> IntentOutcome:
          """阶段二：拿正文层知识产出完整意图，解析失败有限重试。"""

          user_prompt = understand_user_prompt(question, initial.category.value, knowledge_text)
          notes: list[str] = []

          for attempt in range(MAX_INTENT_RETRIES + 1):
              try:
                  result = await self._llm.complete(
                      system=UNDERSTAND_SYSTEM,
                      user=user_prompt,
                      fallback="",
                      budget=budget,
                  )
              except (LlmUnavailableError, LlmBudgetExceededError) as error:
                  notes.append(f"结构化理解不可用，已降级：{error}")
                  return _degraded(initial, notes)

              payload = _load_object(result.text)
              if payload is not None:
                  try:
                      intent = QueryIntent.model_validate(payload)
                  except ValidationError as error:
                      notes.append(f"第 {attempt + 1} 次结构化理解校验未通过：{error.error_count()} 处")
                  else:
                      validation = validate_intent(intent, today=today)
                      notes.extend(validation.adjusted)
                      notes.extend(validation.rejected)
                      return IntentOutcome(
                          intent=validation.intent,
                          validation=validation,
                          notes=tuple(notes),
                          degraded=False,
                      )
              else:
                  notes.append(f"第 {attempt + 1} 次结构化理解解析失败，输出不是 JSON 对象")

          notes.append("结构化理解重试耗尽，已降级为普通对话")
          return _degraded(initial, notes)


  def _degraded(initial: InitialIntent, notes: list[str]) -> IntentOutcome:
      intent = QueryIntent(answer_mode=AnswerMode.CHAT, category=initial.category)
      return IntentOutcome(
          intent=intent,
          validation=IntentValidation(intent=intent, rejected=(), adjusted=()),
          notes=tuple(notes),
          degraded=True,
      )


  def _load_object(text: str) -> dict[str, object] | None:
      try:
          payload = json.loads(text)
      except (json.JSONDecodeError, TypeError):
          return None
      return payload if isinstance(payload, dict) else None


  def _enum[EnumT](enum_type: type[EnumT], raw: object, default: EnumT) -> EnumT:
      try:
          return enum_type(raw)  # type: ignore[call-arg]
      except ValueError:
          return default
  ```

- [ ] **Step 5: 运行测试与门禁。**

  Run: `cd backend && uv run pytest tests/unit/intent/ -v`

  Expected: PASS，15 个测试。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 9: DeepSeek Adapter（测试不启用）

**Files:**
- Create: `backend/app/llm/deepseek.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/unit/llm/test_deepseek_client.py`

**Interfaces:**
- Produces: `DeepSeekLlmClient(settings, transport=None)`，实现 `LlmClient`。
- Produces: `Settings.llm_api_key: str | None`、`Settings.llm_base_url: str`、`Settings.llm_model: str`、`Settings.llm_max_calls_per_request: int`、`Settings.llm_max_tokens_per_request: int`。

- [ ] **Step 1: 加依赖。**

  在 `backend/pyproject.toml` 的 `dependencies` 追加 `"httpx>=0.28,<1",`，并从 `[dependency-groups].dev` 移除同名条目（它要变成生产依赖）。

  Run: `cd backend && uv sync`

- [ ] **Step 2: 写失败的测试。**

  `backend/tests/unit/llm/test_deepseek_client.py`：

  ```python
  """DeepSeek 适配器。

  **本文件不发起任何真实网络请求**（AGENTS.md R3）：用 httpx.MockTransport 拦截。
  真实调用必须先取得用户对模型、调用次数和费用的明确同意。
  """

  from __future__ import annotations

  import httpx
  import pytest

  from app.core.config import Settings
  from app.llm.client import LlmBudget, LlmUnavailableError
  from app.llm.deepseek import DeepSeekLlmClient


  def _settings(api_key: str | None) -> Settings:
      return Settings(
          database_url="postgresql+psycopg://u:p@localhost:5432/db",
          llm_api_key=api_key,
      )  # type: ignore[call-arg]


  def _budget() -> LlmBudget:
      return LlmBudget(max_calls=3, max_tokens=1_000)


  def test_未配置密钥时_is_configured_为假() -> None:
      client = DeepSeekLlmClient(_settings(None))

      assert client.is_configured() is False


  @pytest.mark.asyncio
  async def test_未配置密钥时调用抛_unavailable() -> None:
      client = DeepSeekLlmClient(_settings(None))

      with pytest.raises(LlmUnavailableError):
          await client.complete(system="s", user="u", fallback="fb", budget=_budget())


  @pytest.mark.asyncio
  async def test_请求打到_openai_兼容路径且带鉴权头() -> None:
      seen: dict[str, object] = {}

      def handler(request: httpx.Request) -> httpx.Response:
          seen["url"] = str(request.url)
          seen["auth"] = request.headers.get("authorization")
          return httpx.Response(
              200,
              json={
                  "choices": [{"message": {"content": "回答"}}],
                  "usage": {"total_tokens": 42},
              },
          )

      client = DeepSeekLlmClient(
          _settings("demo-key"), transport=httpx.MockTransport(handler)
      )

      result = await client.complete(system="s", user="u", fallback="fb", budget=_budget())

      assert result.text == "回答"
      assert result.tokens == 42
      assert result.degraded is False
      assert str(seen["url"]).endswith("/chat/completions")
      assert seen["auth"] == "Bearer demo-key"


  @pytest.mark.asyncio
  async def test_上游报错时落_fallback_并标记降级() -> None:
      def handler(request: httpx.Request) -> httpx.Response:
          return httpx.Response(500, json={"error": "upstream"})

      client = DeepSeekLlmClient(
          _settings("demo-key"), transport=httpx.MockTransport(handler)
      )

      result = await client.complete(
          system="s", user="u", fallback="兜底", budget=_budget()
      )

      assert result.text == "兜底"
      assert result.degraded is True


  def test_默认模型与基础地址符合契约() -> None:
      settings = _settings("demo-key")

      assert settings.llm_base_url == "https://api.deepseek.com"
      assert settings.llm_model == "deepseek-v4-flash"
  ```

- [ ] **Step 3: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/llm/test_deepseek_client.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.llm.deepseek'`。

- [ ] **Step 4: 加配置项。**

  在 `backend/app/core/config.py` 的 `Settings` 中追加：

  ```python
      #: 未配置时整条链路仍可运行，只是回答降级（参考实现的 isConfigured 语义）。
      llm_api_key: str | None = None
      #: 固定为 DeepSeek 的 OpenAI 兼容入口（AGENTS.md）。
      llm_base_url: str = "https://api.deepseek.com"
      llm_model: str = "deepseek-v4-flash"
      llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
      #: 单请求预算。超限转显式降级，不是错误页。
      llm_max_calls_per_request: int = Field(default=4, ge=1, le=20)
      llm_max_tokens_per_request: int = Field(default=8_000, ge=100, le=200_000)
  ```

- [ ] **Step 5: 实现适配器。**

  `backend/app/llm/deepseek.py`：

  ```python
  """DeepSeek 适配器（OpenAI 兼容 Chat Completions）。

  **所有测试使用 FakeLlmClient 或 MockTransport，不发真实请求。**
  首次真实调用前必须取得用户对模型、调用次数和费用的明确同意（AGENTS.md R3）。
  """

  from __future__ import annotations

  import httpx

  from app.core.config import Settings
  from app.llm.client import LlmBudget, LlmResult, LlmUnavailableError


  class DeepSeekLlmClient:
      def __init__(
          self,
          settings: Settings,
          *,
          transport: httpx.AsyncBaseTransport | None = None,
      ) -> None:
          self._settings = settings
          self._transport = transport

      def is_configured(self) -> bool:
          return bool(self._settings.llm_api_key)

      async def complete(
          self,
          *,
          system: str,
          user: str,
          fallback: str,
          budget: LlmBudget,
      ) -> LlmResult:
          if not self.is_configured():
              raise LlmUnavailableError("未配置 LLM_API_KEY")

          budget.charge_call()

          payload = {
              "model": self._settings.llm_model,
              "messages": [
                  {"role": "system", "content": system},
                  {"role": "user", "content": user},
              ],
              "stream": False,
          }
          headers = {"authorization": f"Bearer {self._settings.llm_api_key}"}

          try:
              async with httpx.AsyncClient(
                  base_url=self._settings.llm_base_url,
                  timeout=self._settings.llm_timeout_seconds,
                  transport=self._transport,
              ) as client:
                  response = await client.post(
                      "/chat/completions", json=payload, headers=headers
                  )
                  response.raise_for_status()
                  body = response.json()
          except (httpx.HTTPError, ValueError):
              # 上游不可用不是崩溃点：落 fallback 并标记降级（AGENTS.md R7）。
              return LlmResult(text=fallback, tokens=0, degraded=True)

          tokens = int(body.get("usage", {}).get("total_tokens", 0))
          budget.charge(tokens)
          choices = body.get("choices") or []
          text = choices[0].get("message", {}).get("content", "") if choices else ""
          if not text:
              return LlmResult(text=fallback, tokens=tokens, degraded=True)
          return LlmResult(text=text, tokens=tokens, degraded=False)
  ```

- [ ] **Step 6: 运行测试与门禁。**

  Run: `cd backend && uv run pytest tests/unit/llm/ -v`

  Expected: PASS，12 个测试。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

  **同时确认没有真实网络调用**：`uv run pytest tests/unit/llm/ -v` 在断网环境下也必须通过。

---

### Task 10: LangGraph 骨架与 FakeAgent 退役

**Files:**
- Create: `backend/app/agent/state.py`
- Create: `backend/app/agent/graph.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/pyproject.toml`
- Delete: `backend/app/agent/fake_agent.py`
- Delete: `backend/tests/unit/agent/test_fake_agent.py`
- Test: `backend/tests/unit/agent/test_graph.py`

**Interfaces:**
- Consumes: Task 3 的 `KnowledgeRetrieval`、Task 5 的 `LlmClient`、Task 7 的 `MetricCatalog`、Task 8 的 `IntentService`。
- Produces: `class AgentState(TypedDict)`，字段见后端方案 §10。
- Produces: `@dataclass(frozen=True) AgentRunResult(response: ChatResponse, steps: list[ThinkingStep])`——与被删除的 `FakeAgentResult` 同构，使 `ChatAgentProtocol` 只需改类型名。
- Produces: `MerchantQaGraph(*, retrieval: KnowledgeRetrieval, intent_service_llm: LlmClient, catalog: MetricCatalog, max_llm_calls: int = 4, max_llm_tokens: int = 8_000)`，方法 `async run(message: str, session_id: UUID) -> AgentRunResult`。预算上限带默认值，测试可省略，`dependencies.py` 传 `Settings` 里的配置值。
- Produces: `MAX_REVIEW_ATTEMPTS: int = 2`、`GRAPH_NODES: tuple[str, ...]`（13 个节点名，供测试断言顺序）。

- [ ] **Step 1: 加依赖。**

  在 `backend/pyproject.toml` 的 `dependencies` 追加 `"langgraph>=0.2,<1",`，然后 `uv sync`。

- [ ] **Step 2: 写失败的图测试。**

  `backend/tests/unit/agent/test_graph.py`：

  ```python
  """Agent 图骨架。

  B3 只实现到 validate_intent + retrieve_knowledge_detail；query_data、
  compose_answer、local_validate、review_answer、decide_retry 是 passthrough
  占位（B4/B5 填肉）。SSE 的 step 序列从本阶段起就是完整的一串。
  """

  from __future__ import annotations

  import json
  from uuid import uuid4

  import pytest

  from app.agent.graph import MAX_REVIEW_ATTEMPTS, MerchantQaGraph
  from app.knowledge.retrieval import KnowledgeRetrieval
  from app.llm.fake import FakeLlmClient
  from app.metrics.catalog import MetricCatalog
  from app.schemas.chat import AnswerMode


  class _FakeDocument:
      def __init__(self, source_path: str, title: str, content: str) -> None:
          self.source_path = source_path
          self.title = title
          self.content = content
          self.is_complete = True


  class _FakeKnowledgeRepository:
      async def list_active(self) -> list[_FakeDocument]:
          return [
              _FakeDocument("index/README.md", "业务索引", "交易 退货 优惠券"),
              _FakeDocument("业务/交易/业务流程/交易流程.md", "交易流程", "订单 成交 GMV"),
          ]


  class _FakeMetricRepository:
      async def get_by_code(self, metric_code: str) -> None:
          return None


  def _graph(responses: list[str]) -> MerchantQaGraph:
      llm = FakeLlmClient(responses=responses)
      return MerchantQaGraph(
          retrieval=KnowledgeRetrieval(_FakeKnowledgeRepository()),
          intent_service_llm=llm,
          catalog=MetricCatalog(_FakeMetricRepository(), llm),
      )


  def _classify(mode: str, category: str) -> str:
      return json.dumps(
          {"answer_mode": mode, "category": category, "intent_keywords": ["订单"]},
          ensure_ascii=False,
      )


  def _understand(mode: str, category: str, metric: str | None) -> str:
      return json.dumps(
          {
              "answer_mode": mode,
              "category": category,
              "metric": metric,
              "dimensions": [],
              "filters": {},
              "date_range": {"start": "2026-08-01", "end": "2026-08-03"},
              "sort": None,
              "limit": None,
              "followup_reference": False,
              "needs_attachment": False,
          },
          ensure_ascii=False,
      )


  @pytest.mark.asyncio
  async def test_指标问题路由到_metric() -> None:
      graph = _graph(
          [_classify("METRIC", "TRADE"), _understand("METRIC", "TRADE", "order_gmv_amt_1d")]
      )

      result = await graph.run("昨天总 GMV 是多少？", uuid4())

      assert result.response.answer_mode is AnswerMode.METRIC


  @pytest.mark.asyncio
  async def test_闲聊路由到_chat() -> None:
      graph = _graph([_classify("CHAT", "UNKNOWN"), _understand("CHAT", "UNKNOWN", None)])

      result = await graph.run("你好", uuid4())

      assert result.response.answer_mode is AnswerMode.CHAT


  @pytest.mark.asyncio
  async def test_输出_sql_被拒后路由到_invalid() -> None:
      graph = _graph(
          [_classify("METRIC", "TRADE"), _understand("METRIC", "TRADE", "DROP TABLE orders")]
      )

      result = await graph.run("帮我删表", uuid4())

      assert result.response.answer_mode is AnswerMode.INVALID


  @pytest.mark.asyncio
  async def test_step_序列覆盖全部十三个节点() -> None:
      graph = _graph(
          [_classify("METRIC", "TRADE"), _understand("METRIC", "TRADE", "order_gmv_amt_1d")]
      )

      result = await graph.run("昨天总 GMV 是多少？", uuid4())

      nodes = [step.node for step in result.steps]
      assert nodes == [
          "load_context",
          "retrieve_knowledge_index",
          "classify_intent",
          "understand_intent",
          "validate_intent",
          "retrieve_knowledge_detail",
          "query_data",
          "compose_answer",
          "local_validate",
          "review_answer",
          "decide_retry",
          "suggest_questions",
          "persist_answer",
      ]


  @pytest.mark.asyncio
  async def test_llm_不可用时整条链路仍产出回答并标记降级() -> None:
      graph = MerchantQaGraph(
          retrieval=KnowledgeRetrieval(_FakeKnowledgeRepository()),
          intent_service_llm=FakeLlmClient(configured=False),
          catalog=MetricCatalog(_FakeMetricRepository(), FakeLlmClient(configured=False)),
      )

      result = await graph.run("昨天总 GMV 是多少？", uuid4())

      assert result.response.answer_mode is AnswerMode.CHAT
      assert result.response.degraded is True
      assert "FALLBACK" in [source.value for source in result.response.analysis_sources]


  def test_重试上限是常量而不是注释() -> None:
      assert MAX_REVIEW_ATTEMPTS == 2
  ```

- [ ] **Step 3: 运行测试确认失败。**

  Run: `cd backend && uv run pytest tests/unit/agent/test_graph.py -v`

  Expected: FAIL，`ModuleNotFoundError: No module named 'app.agent.graph'`。

- [ ] **Step 4: 定义 AgentState。**

  `backend/app/agent/state.py`：

  ```python
  """图状态。

  后端方案 §10 要求使用明确类型而不是随意扩展的匿名字典——TypedDict 让漏填
  字段在 mypy 阶段就暴露，而不是运行时 KeyError。
  """

  from __future__ import annotations

  from typing import TypedDict
  from uuid import UUID

  from app.intent.models import QueryIntent
  from app.intent.service import InitialIntent
  from app.knowledge.retrieval import KnowledgeResult
  from app.llm.client import LlmBudget
  from app.metrics.catalog import MetricPayload
  from app.schemas.chat import (
      AnalysisSource,
      QualityStatus,
      Recommendation,
      ThinkingStep,
      Visualization,
  )


  class AgentState(TypedDict):
      request_id: str
      session_id: UUID
      question: str
      knowledge_index: KnowledgeResult | None
      knowledge_detail: KnowledgeResult | None
      initial_intent: InitialIntent | None
      intent: QueryIntent | None
      metric_definition: MetricPayload | None
      candidate_answer: str
      visualization: Visualization | None
      recommendations: list[Recommendation]
      suggestions: list[str]
      suggestion_alternates: list[list[str]]
      analysis_sources: list[AnalysisSource]
      quality_status: QualityStatus
      quality_notes: list[str]
      attempt: int
      degraded: bool
      degraded_reason: str | None
      budget: LlmBudget
      steps: list[ThinkingStep]
  ```

- [ ] **Step 5: 实现图。**

  `backend/app/agent/graph.py` 的骨架如下。B3 真正实现 8 个节点，其余 5 个只推 step 并原样返回 state。

  ```python
  """商家问答图。

  节点顺序与后端方案 §10 一致。参考实现是手写的 GraphNode 顺序链
  （MerchantQaLangGraph 的注释：「这里没有依赖外部图框架」）；本项目用
  LangGraph，因为 §10 已经定下 13 节点与条件分支，手写分支容易漏掉上限判断。

  query_data / compose_answer / local_validate / review_answer / decide_retry
  在 B3 是 passthrough：SSE 的 step 序列从本阶段起就是完整的一串，B4/B5 填肉
  时前端不用改第二次。
  """

  from __future__ import annotations

  from dataclasses import dataclass
  from typing import Final
  from uuid import UUID

  from app.agent.state import AgentState
  from app.schemas.chat import ChatResponse, QualityStatus, ThinkingStep

  MAX_REVIEW_ATTEMPTS: Final[int] = 2

  GRAPH_NODES: Final[tuple[str, ...]] = (
      "load_context",
      "retrieve_knowledge_index",
      "classify_intent",
      "understand_intent",
      "validate_intent",
      "retrieve_knowledge_detail",
      "query_data",
      "compose_answer",
      "local_validate",
      "review_answer",
      "decide_retry",
      "suggest_questions",
      "persist_answer",
  )

  _STEP_LABELS: Final[dict[str, str]] = {
      "load_context": "识别商家与会话上下文",
      "retrieve_knowledge_index": "读取业务索引",
      "classify_intent": "识别问题类型与业务域",
      "understand_intent": "结构化理解问题",
      "validate_intent": "校验查询意图",
      "retrieve_knowledge_detail": "读取业务知识正文",
      "query_data": "查询经营数据",
      "compose_answer": "整理回答",
      "local_validate": "本地校验回答",
      "review_answer": "复核回答质量",
      "decide_retry": "判断是否需要重写",
      "suggest_questions": "生成推荐问题",
      "persist_answer": "保存本轮回答",
  }


  @dataclass(frozen=True)
  class AgentRunResult:
      response: ChatResponse
      steps: list[ThinkingStep]


  def _with_step(state: AgentState, node: str) -> AgentState:
      state["steps"].append(ThinkingStep(label=_STEP_LABELS[node], node=node))
      return state


  def _should_retry(state: AgentState) -> str:
      # 上限写进分支条件本身，不写在注释里——写在注释里的上限会在实现时被漏掉，
      # 然后形成无限循环（后端方案 §10）。
      if state["quality_status"] is QualityStatus.FAILED and state["attempt"] < MAX_REVIEW_ATTEMPTS:
          return "compose_answer"
      return "suggest_questions"
  ```

  五个占位节点一律是这个形状，各自替换 `node` 名并保留注释：

  ```python
  async def _query_data(state: AgentState) -> AgentState:
      # 占位：安全经营数据查询属 B4，经营数据表也还不存在。
      return _with_step(state, "query_data")
  ```

  八个实现节点里，`classify_intent` 与 `understand_intent` 分别调用 Task 8 的 `IntentService.recognize` / `understand`；`retrieve_knowledge_index` 与 `retrieve_knowledge_detail` 调用 Task 3 的 `load_index` / `load_domain`；`understand_intent` 之后立即用 Task 7 的 `MetricCatalog.resolve` 填 `metric_definition`。

  `suggest_questions` **不调用 LLM**（后端方案 §6.8），从预置配置取当前组与备选组。

  `run()` 用构造时传入的 `max_llm_calls` / `max_llm_tokens` 初始化 `state["budget"]`（两者带默认值，测试可省略；`dependencies.py` 传 `Settings` 里的配置值）。末尾把 `state` 组装成 `ChatResponse`：`degraded`、`degraded_reason`、`quality_notes`、`analysis_sources` 全部如实填写（AGENTS.md R7）。

- [ ] **Step 6: 接线并退役 FakeAgent。**

  `backend/app/api/dependencies.py` 的 `get_chat_service` 改为：

  ```python
  def get_chat_service(
      session: Annotated[AsyncSession, Depends(get_db_session)],
      database: Annotated[Database, Depends(get_database)],
      settings: Annotated[Settings, Depends(get_app_settings)],
  ) -> ChatService:
      """构造请求级 ChatService。B3 起使用 MerchantQaGraph 替代 B2 的 FakeAgent。"""

      # 没配 LLM_API_KEY 时整条链路仍然可跑，只是回答降级——这是参考实现
      # isConfigured() 的语义，也是演示环境不配密钥也能跑通的前提。
      llm: LlmClient = (
          DeepSeekLlmClient(settings) if settings.llm_api_key else FakeLlmClient()
      )
      conversations = ConversationRepository(session)
      graph = MerchantQaGraph(
          retrieval=KnowledgeRetrieval(KnowledgeRepository(session)),
          intent_service_llm=llm,
          catalog=MetricCatalog(MetricRepository(session), llm),
          max_llm_calls=settings.llm_max_calls_per_request,
          max_llm_tokens=settings.llm_max_tokens_per_request,
      )
      return ChatService(
          session,
          conversations,
          graph,
          MerchantScopeService(conversations, AuditRepository(database)),
      )
  ```

  删除 `backend/app/agent/fake_agent.py` 与 `backend/tests/unit/agent/test_fake_agent.py`。

  `backend/app/services/chat_service.py` 里把 `from app.agent.fake_agent import FakeAgentResult` 改为 `from app.agent.graph import AgentRunResult`，并把 `ChatAgentProtocol.run` 的返回类型同步改名：

  ```python
  class ChatAgentProtocol(Protocol):
      async def run(self, message: str, session_id: UUID) -> AgentRunResult: ...
  ```

- [ ] **Step 7: 运行测试与门禁。**

  Run: `cd backend && uv run pytest -v`

  Expected: 全部 PASS。`tests/api/test_chat.py` 与 `tests/api/test_chat_fixtures.py` 会因 FakeAgent 退役而需要调整——把它们的断言从「FakeAgent 的固定文案」改为「图在 FakeLlmClient 下的输出」，不要削弱断言强度。

  再跑：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`

---

### Task 11: 契约补齐与文档同步

**Files:**
- Modify: `backend/app/schemas/chat.py`
- Modify: `backend/scripts/export_chat_fixtures.py`
- Modify: `docs/api.json`（由脚本重新导出）
- Modify: `frontend/src/api/generated.ts`（由 `npm run codegen` 重新生成）
- Modify: `docs/backend-development-plan.md`
- Modify: `docs/project-progress.md`

- [ ] **Step 1: 给 `Visualization` 加枚举。**

  在 `backend/app/schemas/chat.py` 新增：

  ```python
  class ChartType(StrEnum):
      LINE = "LINE"
      BAR = "BAR"
      PIE = "PIE"
  ```

  把 `Visualization.type` 改为 `ChartType | None`，`allowed_types` 改为 `list[ChartType]`。

  **理由记进注释**：前端不能自行窄化（前端方案 §5.0 禁止 Adapter 编造后端不保证的约束），只能在契约侧加枚举；加完 `codegen` 自动传导，前端零改动。

- [ ] **Step 2: 补导 `DETAIL` 与 `IDENTITY` 两种模式的 fixture。**

  在 `backend/scripts/export_chat_fixtures.py` 增加两个场景：一个 `answer_mode=DETAIL`（订单明细，`data` 有 `rows`/`total_rows`/`truncated`），一个 `answer_mode=IDENTITY`（商家资料）。

  Run: `cd backend && uv run python scripts/export_chat_fixtures.py`

  Expected: `docs/fixtures/chat/` 新增两个 JSON；六种 P0 模式齐全。

- [ ] **Step 3: 重新导出契约并同步前端。**

  ```bash
  cd backend && uv run python scripts/export_openapi.py
  cd ../frontend && npm run codegen && npm run fixtures && npm run codegen:check && npm run fixtures:check
  ```

  Expected: 四条命令退出码为 0。

- [ ] **Step 4: 跑前端全量门禁，确认契约变更没有打破前端。**

  ```bash
  cd frontend
  npm run lint && npm run format:check && npm run typecheck && npm run test && npm run build && npm run mock:check
  ```

  Expected: 全部退出码 0。若 `typecheck` 因 `ChartType` 报错，说明前端某处把 `type` 当自由字符串用了——按契约收窄该处，不要把枚举改回 `string`。

- [ ] **Step 5: 文档同步。**

  `docs/backend-development-plan.md` §B3 的任务清单全部勾选，并在末尾追加一段「实现说明」，写明：三套白名单的位置、**B4 必须在查询层二次校验**、日期上限 180 天与参考实现 365 天的差异及理由。

  `docs/project-progress.md` 更新当前阶段、已完成、最近验证与下一步；写明 FakeAgent 已退役、FakeLlmClient 接替，以及「首次真实 DeepSeek 调用仍未发生，需要用户对模型、调用次数和费用的明确同意」。

- [ ] **Step 6: 全量门禁复验。**

  ```bash
  cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
  cd ../frontend && npm run lint && npm run format:check && npm run fixtures:check && npm run codegen:check && npm run typecheck && npm run test && npm run build && npm run mock:check
  ```

  Expected: 全部退出码 0。
