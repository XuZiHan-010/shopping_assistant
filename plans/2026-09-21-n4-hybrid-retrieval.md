# N4 混合检索与索引版本实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。
> 本地嵌入模型推理**不是 LLM 调用，无费用**；若评估中改用任何付费嵌入 API，须先按 R3 取得授权。
> RAG 忠实度的 LLM 裁判评测需 R3 授权。

**目标：** 实现 PRD A7 混合召回（关键词 + pgvector）、§7.6 索引版本原子切换，
完成 E5 RAG 专项评测，并让 **S7 在混合检索下回归通过**。

**架构：** **演进既有 `app/knowledge/retrieval.py`，不另起一套**（§6.14）。
对外接口保持不变，N3 的规则与口径问答工具不需要改调用方式。
**先测关键词基线，再加向量**——没有基线就无法证明向量带来了收益。

**技术栈：** PostgreSQL + pgvector、本地多语种嵌入模型、pytest。

**规格来源：** PRD A7、A11、M12、§7.6、E5；融合决策 Q11、Q21；
后端计划 §6.5、§6.14；`AGENTS.md` §十一（N4 启用 pgvector）。

---

## 入口条件

> **预写计划不是已验证实现。** 本计划写于上游代码尚不存在时，文中引用的类名、函数签名、
> 工具名、表字段、错误码都是**当时的设计**。开工前逐项对照上游**实际落地**的接口；
> 不一致时先按 PRD → 契约 → 计划的顺序修正，**再动代码**，不得在实现里默默适配或绕过。

- [x] `n3-merchant-skills` Task 6 已完成：S7 在关键词检索下可跑，**作为本计划的回归基准**
      （2026-09-28 核对：S7 已有两层证据——后端 `tests/e2e/test_s7_definitions_loop.py`（真实 PostgreSQL + Fake LLM）
      与浏览器 `frontend/e2e/n3/merchant-skills.spec.ts` 的 S7 用例（`npm run test:e2e:n3`）；
      另有集成测试 `tests/integration/v2/test_merchant_chat_definitions.py`。三者都是本计划 Task 7 的回归基准）；
- [x] 本地开发库与生产库均可启用 `vector` 扩展（2026-10-02 用户确认：生产库是外部 **Neon**，`vector` 0.8.6 可用）——
      2026-09-27 核对：`docker-compose.yml` 使用 `postgres:16-alpine`，**不含 pgvector**，见 Task 2 步骤 0；
- [x] **核对 §6.14 与本计划一致**；
- [x] **核对检索入口的实际形状**：本计划写作时假设的 `retrieve(...)` 函数并不存在，实际入口是
      `KnowledgeRetrieval(repository).load_domain(category, keywords)`（`app/knowledge/retrieval.py:200`），
      调用方为 v1 链路与 N3 `search_rules`（`app/tools/merchant/definitions.py:145`）；Task 4「接口不变」以此为准。

> **2026-09-27 编组修订**（见 `plans/2026-09-27-n4-module-roadmap.md` §二）：新增 Task 2 步骤 0（本地与集成测试库镜像）、
> Task 6 步骤 0（知识后台索引状态字段契约先行）；Task 3 步骤 1 的 Railway 实测数据须由用户提供或另行授权读取。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **不锁死 `bge-m3`**：先建基线，再选较小的多语种模型，实测部署内存与镜像体积后决定（A7）。
- **重排须证明收益才保留**（A7）。
- 知识文档正文是外部文本，进提示词前**必须围栏**（A11）。
- 降级必须对用户可见（R7）。

---

## 一个部署约束决定了模型选型的上限

查询时要把用户问题转成向量，**嵌入模型必须在 backend 进程里**。本版**不建通用 Worker**
（`AGENTS.md` §十一），没有地方可以把模型挪出去。因此：

- 模型体积直接加到 backend 镜像上；
- 模型常驻内存直接加到 backend 实例上；
- Railway 的实例内存与镜像体积上限**就是选型的硬约束**，不是事后优化项。

**Task 3 的选型必须先量出 Railway 的实际可用余量，再在余量内挑模型**，而不是先挑一个
效果好的再看能不能塞进去。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/knowledge/retrieval.py` | 演进：增加向量召回与融合，接口不变 |
| `backend/app/knowledge/embedding.py` | 本地嵌入模型加载与推理 |
| `backend/app/knowledge/index_versions.py` | §7.6 索引版本状态机 |
| `backend/app/knowledge/fusion.py` | 关键词与向量结果融合（RRF） |
| `backend/app/models/knowledge.py` | `knowledge_documents` 补源语言、版本；新增索引版本与分块表 |
| `backend/migrations/versions/*` | `CREATE EXTENSION vector`；分块与索引版本表 |
| `backend/app/jobs/build_index.py` | 构建新索引版本 |
| `backend/app/eval/datasets/rag/` | E5 RAG 评测集 |
| `docs/history/eval/rag-baseline.md` | 关键词基线报告 |

---

### Task 1：关键词基线——先量，再改

**不写任何新检索代码**，先用现有 `retrieval.py` 在评测集上量出基线。

- [x] **步骤 1：建 RAG 评测集** `app/eval/datasets/rag/`，≥ 60 条，每条标注**应命中的文档**：
      口径问答、平台规则、跨语言（中文问英文文档）、口语化改写、多文档组合、
      **以及应当"找不到"的问题**（检索不到时要承认，而不是凑一个）
- [x] **步骤 2：跑基线，记录四项指标**

| 指标 | 含义 |
| --- | --- |
| Recall@k（k=3、5） | 应命中文档出现在前 k 的比例 |
| MRR / nDCG@5 | 排序质量 |
| 引用正确率 | 回答引用的文档确实支持该陈述 |
| 回答忠实度 | 回答未超出检索内容 |

前两项**纯确定性**，Fake LLM 即可；后两项需要 LLM 裁判，属 R3 范围——
**未授权时只报前两项**，并在报告中写明后两项待测。

- [x] **步骤 3：报告落 `docs/history/eval/rag-baseline.md`**

**这份基线是本计划后续所有改动的对照**。没有它，"加了向量效果更好"只是感觉。

**2026-10-01 完成记录（Opus）：** 评测集 `app/eval/datasets/rag/n4_e5_rag.yaml` 64 条（可回答 54、应找不到 10，七类）；评估器 `app/eval/rag_e5.py`，
检索路径与 `search_rules` 一致；校验 `tests/eval/test_n4_rag_baseline.py` 7 例。基线：Recall@3 0.093、Recall@5 0.093、MRR 0.074、nDCG@5 0.066、
拒答率 0.50。主因是 `search_rules` 固定平台规则域，21 篇里只有 3 篇进入候选；诊断上限（假设业务域选对）Recall@5 0.861。
引用正确率与回答忠实度待 LLM 裁判（R3），报告已标待测。报告 `docs/history/eval/rag-baseline.md`。

---

### Task 2：索引版本状态机（§7.6）

```text
构建中 → 验证中 → 已就绪 →（原子切换）→ 生效
构建中 / 验证中 → 失败 → 继续使用上一生效版本并标记陈旧
无可用旧版本 → 降级为关键词检索并显式标注
```

### 实现要点

- 每个版本的分块与向量**写入独立的版本号下**，查询按"当前生效版本号"过滤；
- **原子切换 = 在单个事务里改一行"当前生效版本"指针**，不是逐行更新分块——
  逐行更新必然产生"一半新一半旧"的窗口；
- 同一时刻只允许一个版本处于构建中（数据库锁）；
- 验证阶段跑 Task 1 评测集的确定性部分，**Recall@5 低于上一生效版本的 95% 则判失败**，不切换。

- [x] **步骤 0：本地与集成测试库启用 pgvector**——`docker-compose.yml` 与集成测试库改用带 `vector` 扩展的
      PostgreSQL 16 镜像（主版本不变），迁移里 `CREATE EXTENSION IF NOT EXISTS vector`；
      全量 `REQUIRE_INTEGRATION_DB=1` 回归零失败后才进入步骤 1，避免换镜像与新功能的失败混在一起
      （2026-10-01 部分完成：`docker-compose.yml` 与 `.github/workflows/n1-checks.yml` 已改用 `pgvector/pgvector:pg16`，`vector` 0.8.6 可用；
      compose 改用新数据卷 `borough_postgres_pgvector_data`（Alpine→Debian 排序规则不同，旧卷保留未删）；新镜像下后端全量
      **4262 passed / 12 skipped / 0 failed**。**未做**：迁移里的 `CREATE EXTENSION vector`——Railway 是否支持未确认，提前加入会让部署失败，
      顺延到步骤 1 真正用到向量列且用户确认后再加。**2026-10-02 补完**：迁移 `20261002_0047` 加入扩展与三张表，升/降/升与 `alembic check` 通过）
- [x] **步骤 1：写失败测试**

```python
async def test_switch_is_atomic(db_pool) -> None:
    """并发查询在切换瞬间只能看到完整的旧版本或完整的新版本。"""
    await build_and_activate(version=1)
    await build(version=2)
    seen = await asyncio.gather(
        *[query_versions_seen(db_pool) for _ in range(200)],
        activate(version=2))
    assert all(len(s) == 1 for s in seen[:-1])


async def test_failed_build_keeps_previous_and_marks_stale(svc) -> None:
    await build_and_activate(version=1)
    with failing_embedder():
        await svc.build(version=2)
    assert await svc.active_version() == 1
    assert (await svc.status()).stale is True


async def test_no_previous_version_falls_back_to_keyword_visibly(svc, loop) -> None:
    with failing_embedder():
        await svc.build(version=1)
    out = await loop.run(script=scripted_rule_question())
    src = next(s for s in out.analysis_sources if s.source == "KNOWLEDGE")
    assert src.degraded is True and src.degraded_reason == "INDEX_UNAVAILABLE_KEYWORD_FALLBACK"


async def test_quality_regression_blocks_switch(svc) -> None:
    await build_and_activate(version=1)                 # Recall@5 = 0.80
    await svc.build(version=2, embedder=worse_embedder())   # Recall@5 = 0.70
    assert await svc.active_version() == 1
```

第三条对应 R7：降级必须在 `analysis_sources` 的单来源降级字段里**如实标注**，
整轮可以不降级，但该来源必须标出来。

- [x] **步骤 2：确认失败 → 实现 → 确认通过**（**真实 PostgreSQL**）

**2026-10-02 完成记录（Opus）：** `app/knowledge/index_versions.py`、`app/models/knowledge_index.py`、迁移 `20261002_0047`；
集成测试 `tests/integration/v2/test_knowledge_index_versions.py` 12 例（四条必测 + 单构建互斥、崩溃回收、换模型不可用、
语料变更标陈旧、旧分块回收、空语料、`needs_build`）。**如实说明**：测试与实现同一轮写成，未先单独跑红；
改用变异验证——去掉查询 SQL 的指针过滤、关闭质量闸门后，原子切换与质量回退两例分别变红，恢复后全绿。
第三条必测在 Chat 层由 `tests/integration/v2/test_merchant_chat_definitions.py` 断言 `analysis_sources` 的 KNOWLEDGE 项
`degraded_reason="INDEX_UNAVAILABLE_KEYWORD_FALLBACK"`（真实 ASGI + PostgreSQL + Fake LLM）。

---

### Task 3：嵌入模型选型

- [x] **步骤 1：量出 Railway backend 实例的可用余量**（读取 Railway 控制台指标须用户提供截图/数值或单独授权；
      未取得时本步保持未完成，Task 3 不得用本地机器数值替代）

记录当前 backend 镜像体积、空载常驻内存、峰值内存，以及 Railway 方案的上限。
**余量 = 上限 − 当前峰值 − 安全边际（建议 25%）**。

- [x] **步骤 2：在余量内列出候选**

只列**多语种**且**体积与内存在余量内**的本地模型，至少 3 个候选。`bge-m3` 可以列入，
但**若超出余量则直接排除**，不因为它是常见选择就放宽约束。

- [x] **步骤 3：每个候选跑 Task 1 评测集**，记录 Recall@k、MRR/nDCG、
      冷启动加载时间、单次查询延迟、镜像增量、内存增量
- [x] **步骤 4：选定并写入 §6.14**，附完整对比表

**2026-10-02 完成记录（Opus）：** 用户提供 Railway 现状（Hobby，backend 空载约 100 MB，只看了 15 分钟曲线）；本机实测 6 个
不依赖 PyTorch 的候选（详见 §6.14 与 `docs/history/eval/rag-hybrid.md`）。推荐 `google/embeddinggemma-300m`（τ=0.40）：
拒答率 0.90 不变时 R@5 0.759→0.935、MRR 0.639→0.812；Linux 常驻 +795 MB、镜像 +1.26 GB。低成本备选 `BAAI/bge-small-zh-v1.5`（中文模型，
R@5 0.870，Linux 常驻 +170 MB、镜像 +95 MB）。**2026-10-02 用户裁定选 `bge-small-zh-v1.5`**（中文为主、英文锦上添花；中文 46 条 R@5 0.891 对 gemma 0.946，成本约 1/5）；
偏离本 Task「只列多语种」的规则，理由记入 §6.14。代码默认 `EMBEDDING_MODEL` 为空，compose 与 Railway 设为该模型。
步骤 1 的余量数据只有空载值，没有 7 天峰值与 Railway 单服务上限，这一点在报告中注明。

**若所有候选都超出余量**：停下来报告，不自行决定"换个大一点的 Railway 方案"——
那是成本决策，属于用户。

---

### Task 4：混合召回与融合

- 关键词与向量**各召回 top-N**，用 **RRF（倒数排名融合）** 合并——它不需要两路分数可比，
  是两种异质检索融合的稳妥默认；
- 跨语言：沿用既有的查询规范化译文机制（`AgentState.retrieval_queries` 的同类思路），
  向量召回天然跨语言，可减少对译文的依赖；
- 接口保持不变：`KnowledgeRetrieval.load_domain(...)` 的签名与返回的 `KnowledgeResult` 结构不改（入口条件已核对实际形状）。

> **2026-10-01 前置改进（用户同意，不依赖向量）：** `search_rules` 由固定平台规则域改为全文档检索
> （`KnowledgeRetrieval.search_documents`，至少命中 2 个不同查询词，最多 5 篇），`load_domain` 签名与 v1 路径不变。
> E5 RAG：Recall@5 0.093→0.759、MRR 0.074→0.639、拒答率 0.50→0.90。本 Task 的混合检索须相对**这个新路径**证明收益，
> 而不只是相对原基线。三条工具单测先红后绿；评估器 `search_rules_retriever` 随产品代码变化。

- [x] **步骤 1：写失败测试**

```python
def test_rrf_needs_no_score_normalization() -> None:
    kw = [("d1", 12.7), ("d2", 3.1)]            # BM25 分数
    vec = [("d2", 0.91), ("d3", 0.88)]           # 余弦相似度
    assert [d for d, _ in rrf_fuse(kw, vec)][:2] == ["d2", "d1"]


async def test_retrieve_signature_unchanged() -> None:
    """N3 的工具不应需要修改。"""
    import inspect
    assert inspect.signature(KnowledgeRetrieval.load_domain) == BASELINE_SIGNATURE
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**（单测 `tests/unit/knowledge/test_hybrid_retrieval.py` 9 例、`tests/unit/services/v2/test_merchant_chat_sources.py` 5 例；
      同样是与实现同轮写成，未先单独跑红）
- [x] **步骤 3：在评测集上对比基线**——混合检索的 Recall@5 与 MRR **须优于基线**，
      否则不上线，报告原因

---

### Task 5：重排——须证明收益才保留

- [x] **步骤 1：实现一个重排候选**（在余量内的本地交叉编码器）
- [x] **步骤 2：在评测集上对比"混合"与"混合 + 重排"**
- [x] **步骤 3：判定**

**2026-10-02 完成记录（Opus）：** `BAAI/bge-reranker-base` 只在评测脚本中实现：nDCG@5 0.819→0.884（+6.4 个百分点）、
MRR 0.794→0.875，但每次查询 p50 4.0 s / p95 9.4 s、内存 +1.3 GB（测量时全量回归并行，偏高）。延迟不可接受，**不保留**；
未进入产品代码，无需删除。详见 `docs/history/eval/rag-hybrid.md` 末节。

| 结果 | 处置 |
| --- | --- |
| nDCG@5 提升 ≥ 3 个百分点，且 p95 延迟增量可接受 | 保留 |
| 否则 | **删除重排代码**，不以"以后可能有用"为由保留 |

---

### Task 6：知识库后台接入（M12）

- 既有知识库后台是**唯一内容维护入口**（Q11），团队维护区优先；
- 文档保存或删除后**触发新索引版本构建**，而不是原地改分块；
- 文档补齐源语言与版本字段（PRD §8.1）；
- 后台显示当前生效索引版本、构建状态、是否陈旧。

- [x] **步骤 0：契约先行**——索引状态字段先写入后端计划 §8.6.5（知识后台契约），**优先加在既有
      `GET /api/admin/knowledge/tree` 响应里**；若确需新端点，须先改 PRD §11 与 `AGENTS.md` §8.1 路径表。
      随后 Schema → OpenAPI → `generated.ts` → Adapter → `KnowledgeBaseView.vue`（Sonnet）。
      **（2026-09-28，PRD §15「W」）** 页面部分在 W Task 7 完成后做：
      - 知识库已迁入商家工作台侧栏的「管理」分组，经 `AdminGate` 输入管理员令牌后进入；
      - 索引状态展示用新 token；
      - 契约与后端部分不受 W 影响，可以先做。
- [x] **步骤 1：写失败测试**——保存文档后新版本进入构建中；构建期间旧版本继续服务。
- [x] **步骤 2：确认失败 → 实现 → 确认通过**

**2026-10-02 完成记录（Opus）：** 契约 §8.6.7（`KnowledgeTreeResponse.index_status`，不新增端点）→ Schema → OpenAPI →
两端 `generated.ts` → Adapter（`toKnowledgeTreeSnapshot`）→ Store → `KnowledgeBaseView` 状态行（中英文案）。
写入在同一事务标 `CORPUS_CHANGED`，提交后 FastAPI 后台任务 `rebuild_until_fresh()`；人工译文不触发；切换时先锁指针行
再核对语料指纹，构建期间又有保存则保持陈旧并再建一轮。API 测试 `tests/api/test_knowledge_index_admin.py` 6 例
（「同一事务标陈旧」一例经变异验证：去掉标记后变红）。前端单测 +4 例，`e2e/knowledge-base.spec.ts` 2/2。
文档表字段「源语言与版本」在 N1 已存在（`source_locale`、`version`），本次未改。

---

### Task 7：S7 回归与 E5 报告

- [x] **步骤 1：S7 回归**——`n3-merchant-skills` Task 6 的 S7 场景在混合检索下重跑，**必须通过**：
      后端 `test_s7_definitions_loop.py` 与浏览器 `npm run test:e2e:n3` 的 S7 用例两层都要重跑
- [x] **步骤 2：E5 RAG 报告**——基线 vs 混合 vs 混合 + 重排的完整对比，
      落 `docs/history/eval/rag-hybrid.md`
- [x] **步骤 3：忠实度与引用正确率**——需 LLM 裁判，按 R3 提交审批，填入实际条数与费用上限；
      **未授权时报告标注"待测"，不得声称检索质量已全面验证**
      （2026-10-01 用户授权执行，针对当前关键词全文档检索：`deepseek-flash` 128 次、184,360 token；引用正确率 0.979、
      如实拒答 1.000、裁判忠实度 1.000 但人工抽查 10 条有 1 条轻度推断；同模型自评偏差已注明。结果在 `docs/history/eval/rag-baseline.md`。
      混合检索上线后须对新检索重跑一次）

---

**2026-10-02 S7 回归记录（Opus）：** 后端 `test_s7_definitions_loop.py` 2 例通过——原有一例（未配置模型，走关键词降级）
与新增 `test_s7_rule_citation_through_hybrid_index`（确定性嵌入器 + 已生效索引，断言 `retrieval=HYBRID`、KNOWLEDGE 不降级）；
浏览器 `npm run test:e2e:n3` 4/4（含 S7）。浏览器层未配置真实嵌入模型，验证的是关键词降级路径下的界面与来源展示。

### Task 8：自检

```powershell
cd backend
rg -n "UPDATE knowledge_chunks" app/
uv run pytest; uv run ruff check .; uv run mypy app
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/ -k "index or retrieval" -v
```

第一条期望零命中：分块只按版本写入，**不原地更新**。

**2026-10-02 自检记录（Opus）：** `UPDATE knowledge_chunks` 在 `app/` 零命中；后端全量 4350 passed / 4 skipped / 0 failed，
`ruff check .`、`mypy app` 通过；`docs/project-progress.md`、`docs/deployment.md`、`docs/database.md`、`docs/project-navigation.md` 已更新。

更新 `docs/project-progress.md` 与 `docs/deployment.md`（pgvector 启用步骤、镜像与内存增量）。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 商家可维护的店铺级知识 | 不在本版（M1：知识库不进普通商家工作台） |
| 索引构建的 Cron 接线 | `n5-budget-ops-and-railway` |
| 付费嵌入 API | 除非 Task 3 证明本地模型不可行且用户按 R3 授权 |
