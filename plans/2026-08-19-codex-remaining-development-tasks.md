# Codex 后续开发任务清单

**日期：2026-08-19　状态：待执行　前置分支：`feature/answer-loop-demo-refresh`（已推送 `origin`，尖端 `bef7568`）**

本文件是「回答闭环整改与演示数据保鲜」那一轮工作的交接单，只回答一件事：**下一位 coding agent 接手后按什么顺序做什么**。

上一轮的设计依据与逐步 TDD 步骤在 [2026-08-18-answer-loop-parity-and-demo-data-freshness.md](2026-08-18-answer-loop-parity-and-demo-data-freshness.md)（第 5 稿）和 [2026-08-18-answer-loop-and-demo-data-change-summary.md](2026-08-18-answer-loop-and-demo-data-change-summary.md)，本文件不重复它们。

---

## 一、接手时的基线

### 已落库并推送的成果

分支 `feature/answer-loop-demo-refresh` 相对 `main`（`37755f0`）为 **70 files changed, +4359 / -545**，四个提交：

```text
bef7568  docs: 登记质量循环与演示数据滚动的契约、偏离与运维事实（计划 C4）
fa343c8  feat: 演示数据改为按日确定生成与每日增量滚动（计划 C1-C3 代码侧）
2477ba9  feat: 合并生成与复核为统一质量循环并把数字守卫升级为事实校验（计划 B1-B6）
f82951b  feat: LLM 调用可观测化并对结构化步骤关闭推理（计划 A1-A3）
```

**提交时实测的门禁（2026-08-19，全绿）**：

| 门禁 | 结果 |
| --- | --- |
| 后端 pytest（真实 PostgreSQL 在线） | **859 passed / 0 failed / 0 skipped**（60.84s） |
| `ruff check` / `ruff format --check` / `mypy app` | 全绿（95 源文件） |
| 前端 Vitest | 26 文件 / **254 passed** |
| typecheck / lint / format:check / codegen:check / fixtures:check | 全绿 |

> 只有分支尖端 `bef7568` 验证过是绿的。中间三个提交未逐个跑测试——`core/config.py`、`.env.example` 等文件跨 A/B/C 三段，无法按段拆分。**不要假设 `f82951b` 或 `2477ba9` 单独可用。**

### 计划完成度

原计划 15 个任务（A1–A4、B1–B7、C1–C4）中 **13.5 个已完成，约 90%**。未完成的是 **B7**（真实模型九题验收）与 **C3 的控制台部分**。

### 尚未发生的事

- **`main` 没动**，本地与远端都仍是 `37755f0`；分支未合并、未开 PR；
- 计划文件里 **68 个 checkbox 一个没勾**，账本与代码状态完全脱节；
- 知识库仍是 **0 行**。

---

## 二、剩余任务

### 第 1 类 · 零费用，接手后立即可做

#### T1　导入知识库（**最高优先级**）

**为什么排第一**：`knowledge_documents` 至今 0 行，导致三件事同时坏着——RULE 类问题无依据可答、指标口径三级检索的第三级无料、每轮回答都挂着「未命中与当前问题相关的知识资料」。**更关键的是 T1 不做，T7 的 RULE 那道题必挂**，四五万 token 的验收费用会白花一部分。

```powershell
cd backend
uv run python scripts/import_wiki.py --root "../yshopping-merchant-ai 4/yshopping-merchant-ai/runtime/llm-wiki"
```

- 参考目录下有 54 个 `.md`；`parse_wiki_tree` 会排除旧 DDL 与指标调用说明（它们描述的表结构在 Borough 不存在），**实际导入数以脚本输出为准，不要预设数字**；
- 参考目录只读（R8）：脚本仅读取，不得改写、重命名或格式化其中任何文件；
- 验收：`knowledge_documents` 行数 > 0；随便问一个规则类问题，`quality_notes` 不再出现「未命中知识资料」。

#### T2　复核 classify 提示词里的硬编码兜底

`backend/app/intent/prompts.py` 里有一段「即使业务索引为空，也按以下固定规则分类」（成交额/GMV/订单/交易 → TRADE、退款/退货 → REFUND、工单/咨询 → SUPPORT、规则 → PLATFORM）。

这是 2026-08-19 22:22 加的**空知识库过渡措施**，不在原计划 15 个任务内。**T1 完成后必须重新判断它的去留**：知识索引有料之后，这段固定规则可能与检索结果冲突，也可能仍作为兜底有价值。做出判断并在 `docs/yshopping-parity-audit.md` 登记结论。

> 附带事实：这段改动是上一轮工作被中断时的最后一笔，当时**没跑完门禁**（`ruff format` 未过，已在提交前补跑）。它的测试 `tests/unit/intent/test_prompts.py` 是绿的，但它本身没有经过完整的计划审阅流程。

#### T3　补指标口径调用点的 usage 上报

A2 的记账改造漏了一个调用点。`backend/app/metrics/catalog.py` 的 `_generate` 里：

```python
result = await self._llm.complete(..., options=STRUCTURED_CALL_OPTIONS)
data = json.loads(result.text)
...
return replace(generated, source=MetricDefinitionSource.AI_GENERATED.value)
```

`result` 里的 usage 被丢掉了，方法只返回 `MetricPayload`。后果已经在 A4 验收里显形——记录写的是「指标口径生成成功且字段完整，但现有组件未向验收调用方暴露该次 LLM usage，按未知用量记录」。

改法：让该路径把 usage 一并透出（返回值扩展或回调），使 `llm_usage` 能记到真实 token 而不是落进未知。验收：新增一条单元测试断言该调用点的 usage 可被观测到。

#### T4　按 A4 实测重算 B4 的预算

当前 `backend/app/core/config.py` 里的 `MAX_LLM_CALLS_PER_REQUEST=10`、`MAX_LLM_TOKENS_PER_REQUEST=25000`、`QUALITY_MAX_ATTEMPTS=3` 是**计划预填值，不是按 A4 实测重算出来的**。

计划 Task B4 明确要求：用 A4 的实测值按调用图逐段核算，逐段列出「期望次数 / 最坏次数」，确认最坏 ≤ `MAX_LLM_CALLS_PER_REQUEST`，且**禁止再按「understand = 1 次」估算**。

已知 A4 实测（2026-08-19，`deepseek-v4-flash`）：classify 298 token / 1.94s，understand 865 token / 1.05s，Reviewer 0.90s 返回合法 verdict，指标口径用量未知（见 T3）。

**T3 应先于 T4**——指标口径那一段的真实用量拿不到，核算就还是有一个洞。

#### T5　回填账本

这是本项目已记录 **4 次**的系统性问题（「计划勾选账本与实际代码状态脱节」），不要让它变成第 5 次：

- `plans/2026-08-18-answer-loop-parity-and-demo-data-freshness.md` 的 68 个 checkbox 按实际完成情况勾选；
- `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md` 仍停在 2026-08-12，R9、Vitest、Playwright 数字均已过期；
- `plans/2026-08-12-post-f6-execution-roadmap.md` 阶段 0–2.5 的状态回填。

#### T6　Task 2.4：清理 `tests/` 与 `scripts/` 的 mypy 债务

roadmap 里登记的既有任务，从未开始。`mypy app` 是绿的，债务在 app 之外。

---

### 第 2 类 · 需要用户明确授权（R3，会真实计费）

#### T7　B7 九题真实模型验收

**执行前必须先说明模型、调用次数与预计费用并取得同意。**

- 题目：METRIC×6（趋势、分类、同比/环比、空结果、截断风险、非加和各 1）+ DETAIL×1 + RULE×1 + CHAT×1；
- 逐条记录 `degraded`、`quality_status`、`quality_attempts`、`quality_notes`、`data_rows`、图表与建议条数、端到端耗时；
- **出口判据**：6 条 METRIC 全部 `degraded=false`（对照 2026-08-18 修复前 4 次采样 2 次失败的基线）；任何降级都能从 `quality_notes` 读出被打回的具体原因；`NOT_RUN` 与 `PASSED` 不得混淆；
- 预计 4~5 万 token；单题受 `MAX_LLM_CALLS_PER_REQUEST` 约束，整个验收的理论硬上限为 90 次模型请求，实际应显著低于该值；
- 用户确认的调用次数与 token 上限必须写进验收记录，**任一上限将被触及时立即停止**，不得自动追加样例或重跑；
- 结果写进 `docs/project-progress.md`。

**前置：T1 必须先完成**，否则 RULE 那题无知识依据。

---

### 第 3 类 · 需要用户在控制台操作或另行裁定

#### T8　C3：创建 Railway Cron Service

代码侧已齐：`backend/railway.cron.json`（无 `healthcheckPath`、无 `preDeployCommand`、`restartPolicyType: NEVER`）、`app/jobs/seed_demo_rolling.py`、`app/core/seed_config.py`，`docs/deployment.md` 的「演示数据的每日滚动」章节已写清操作步骤。

剩下的是控制台动作：建 Service、配四个变量（`DATABASE_URL`、`APP_ENV`、`ALLOW_DEMO_DATA_REFRESH`、`BUSINESS_TIMEZONE`）、手工触发一次并验收。

**不得复用 `backend/railway.json`**——它带健康检查与 `preDeployCommand`，一次性任务不监听端口，健康检查必然失败。

#### T9　线上遗留验收项

| 项 | 内容 | 费用 |
| --- | --- | --- |
| 转发头伪造验收 | 同一演示 Token 连续更换 `X-Real-IP` / `X-Forwarded-For`，超限仍须返回 429 | 零 |
| SIGTERM 收尾验收 | 容器收到终止信号后的收尾行为 | 零 |
| 日志脱敏抽查 | 确认敏感字段未落日志 | 零 |

阶段 2.5 遗留，需线上环境。

#### T10　分支合并与 PR

`main` 仍是 `37755f0`。合并或开 PR 前：

> **必须先删掉主目录 `plans/` 下那两份未跟踪的重复文档**（`2026-08-18-answer-loop-and-demo-data-change-summary.md` 与 `2026-08-18-answer-loop-parity-and-demo-data-freshness.md`）。它们与分支上已提交的版本字节一致，但 git 会以「未跟踪文件会被覆盖」拒绝检出。

按 R2，合并、PR、push 均需用户明确许可。

---

## 三、建议执行顺序

```text
T1 导知识库 ──┬─→ T2 复核硬编码兜底
              └─────────────────────────────┐
T3 补 catalog usage ──→ T4 重算预算 ────────┤
                                            ├─→ T7 九题真实验收（需授权）
T5 回填账本（可并行）                       │
T6 mypy 债务（可并行）                      │
                                            └─→ T10 合并回 main（需授权）

T8 Cron Service ─→ T9 线上遗留验收          （需控制台，与上面无依赖）
```

- **T1 必须先于 T2 和 T7**；
- **T3 必须先于 T4**（用量拿不到，核算有洞）；
- **T4 应先于 T7**（预算没标定准，验收可能撞「预算耗尽」降级，把排查方向带偏）；
- T5、T6、T8 与主线无依赖，可随时插入。

---

## 四、硬性约束

- **R2**：未经用户明确许可，不执行 `git commit` / `push` / `tag` / `gh pr create` / `gh pr merge`，不使用 `git reset --hard`、`git clean`；
- **R3**：真实 LLM 调用前必须说明接口、调用次数、模型和费用，取得同意后才能执行。单元测试必须 mock LLM；
- **R8**：`yshopping-merchant-ai 4/` 整体只读，导入 wiki 时只读不写；
- **R10**：技能产出的文档写进 `plans/` 与 `docs/specs/`，不建 `superpowers/` 目录；
- **改任何 LLM 提示词，必须同时加一条从 Pydantic 模型推导期望值的提示词契约测试**（范式见 `backend/tests/unit/intent/test_prompts.py`）。原因见下一节第 1 条。

### 每次改完必跑的门禁

```powershell
# 后端
cd backend
uv run pytest                      # 真实库需 REQUIRE_INTEGRATION_DB=1
uv run ruff check .
uv run ruff format --check .
uv run mypy app

# 前端
cd frontend
npm run typecheck
npm run lint
npm run format:check
npm run codegen:check
npm run fixtures:check
npx vitest run
```

---

## 五、已知陷阱

1. **`FakeLlmClient` 会掩盖整类缺陷**。它返回预写好的合法 JSON，因此「提示词有没有告诉模型该输出什么」在自动化测试里完全不可见。2026-08-17～18 连续暴露的五个缺陷全部属于这一类。这就是上面那条提示词契约测试要求的由来。

2. **两套重试是乘加关系**。`app/intent/service.py` 的 `MAX_INTENT_RETRIES=2`（understand 最坏跑 3 次）与 `QUALITY_MAX_ATTEMPTS` 互相独立，但四个调用点共用同一个 `LlmBudget`。当前最坏路径 9 次。任何一边加码都要重算，否则会以「预算耗尽」的面目暴露成意图识别问题。

3. **真实库全量测试对并发敏感**。历史上多 Agent 并发访问同一测试容器时出现过 `TRUNCATE_ALL_TABLES` 死锁；单 Agent 独占时连续多次干净通过。**跑全量前确认没有其他 agent 在同一容器上写数据。**

4. **旧全量 Seed 会抹掉滚动历史**。`backend/scripts/seed_demo_analytics.py` 会 DELETE 六张表再重写，已加 `--force-full-rebuild` 显式确认，降为一次性重置工具。常态入口是 `python -m app.jobs.seed_demo_rolling`。

5. **有一个 2026-08-10 的陈年 stash**（`stash@{0}`，`b4-branch-stale-docs-backup-20260810`，6 个文档文件 +278/-90），来自 `feature/b4-safe-analytics-query` 时期，与本轮无关。大概率已被后续提交完全覆盖，但**清理前先 diff 确认里面没有未落地内容**。

6. **`docs/project-progress.md` 是跨日工作的外部记忆入口**。每完成一段可验证工作就更新它的日期、状态、验证结果、下一步和风险；它只保留当前快照，不追加流水账。

---

## 六、不在本清单范围

以下属于 MVP 出口的其余部分，已在 `docs/project-progress.md` 登记：

- IDENTITY、生成指标、跨业务查询的真实模型验收（目前只验通 METRIC 一条路径）；
- F1 的 1440×1000 人工视觉比对；
- P1 的 B8–B9 / F7–F9（附件、日报、商家记忆、对象存储、Worker、知识库后台）。
