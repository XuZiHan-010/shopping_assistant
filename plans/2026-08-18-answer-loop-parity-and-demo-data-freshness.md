# 回答质量循环还原与演示数据时效方案 实施计划（第 5 稿）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `superpowers:executing-plans` 或 `superpowers:subagent-driven-development` 逐任务执行。步骤用 `- [ ]` 复选框跟踪。

**状态：第 5 稿，已按三轮审查意见修订；D1–D3 仍待用户明确确认。未开始执行。**

**第 1 稿经审阅被判定「抓对了问题，但方案不够成熟，不建议直接实施」；第 3 稿又发现 Reviewer 判定、预算分类、空正文重试、配置接线、用量迁移与 Railway 授权门等问题；第 4 稿经代码逐条核对，又发现预算次数算漏 understand 重试、空正文契约未落到代码、异常兜底被删出缺口、前端 fixture 门禁未登记、演示数据随机种子与真实写入路径不符等问题。本稿逐条处置（见 §0）。D1～D3 来自审查建议，不是用户已经作出的裁定；本稿先按这些建议写成可审阅的默认方案，只有用户明确确认后才能执行。**

**Goal:** 还原参考项目「生成 → 校验 → Reviewer → 反馈重试 → 确定性兜底」的**产品行为与质量标准**，但不复制它的技术局限；同时让 Railway 演示环境具备可观测、成本可控、历史数据稳定、与真实数据隔离四项性质。

**Architecture:** 三段。**A 段**先降本增效并补可观测（关结构化步骤的 thinking、JSON Output、错误码不再静默、用量记账修正），它是 B 段成本估算的前提。**B 段**重构质量循环并把数字守卫升级为事实校验。**C 段**用「独立 Cron + 增量滚动 Seed」解决演示数据时效，且不破坏历史稳定性。A 段可独立交付，B、C 互不依赖。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、pytest、Ruff、mypy、Docker、Railway Cron。

**Spec:** §1（参考项目实现事实，带行号出处）与 §2（2026-08-18 真实模型实测数据）共同构成规格来源。

## Global Constraints

- 面向用户的文案、错误提示、日志与文档用中文；代码标识符用英文（AGENTS.md R1）。
- 不修改只读目录 `yshopping-merchant-ai 4/`，只作行为对照（R8）。
- 未经用户明确许可不执行 `git commit` / `git push` / `git tag` / PR 操作（R2）。每个任务以检查 diff 收尾。
- 单元测试必须 mock LLM；真实 DeepSeek 调用前先按 R3 说明接口、次数、模型与预计费用并取得同意。
- R3 的“次数”按**模型请求次数**说明，不能只写问题条数；验收说明同时列出期望调用数与最坏调用上限。
- 降级必须对用户可见，字段名不得超出 `docs/backend-development-plan.md` §8.2 的 ChatResponse 契约（R7）。
- 每个生产行为先写失败测试、确认失败原因，再写最小实现（TDD）。
- **演示数据库与未来承载真实商家数据的数据库彻底隔离**，任何演示专用开关都不得在真实数据部署里生效。
- 创建 Railway Service、配置生产变量、手工触发 Cron 或执行任何正式部署前，必须另行取得用户明确许可；确认 D1～D3 只代表认可设计方向，不等于部署授权。
- 验证阶段只运行 `ruff format --check`；需要格式化时仅对本任务改动文件单独执行，不能把会改写整个目录的 `ruff format app tests` 当作只读门禁。

---

## §0 第 1 稿的缺陷与本稿处置

上一轮审查提出四点，全部经代码或真实模型实测核实属实。逐条处置：

| # | 第 1 稿缺陷 | 核实依据 | 本稿处置 |
| --- | --- | --- | --- |
| 1 | **解析失败立即降级** | 第 1 稿 `QualityLoop` 写 `if drafted.draft is None: return _fallback_outcome(...)`；参考实现 `PromptLoopAnalysisService.java:152-155` 是 `validate(null)` → 记「answer 不能为空」→ **继续下一轮** | Task B2：解析失败并入 issues 参与重试，只有轮次用尽才兜底 |
| 2 | **Reviewer 缺失却标记 PASSED** | 第 1 稿 `if not issues and reviewer_llm is not None:` 之后直接落 `PASSED`，并写「通过本地校验和独立复核前后比对」——复核根本没跑，同时违反 R7 | Task B2：`reviewer_llm is None` 时返回确定性摘要并标 `DEGRADED`；`NOT_RUN` 只留给本来不进入质量循环的回答 |
| 3 | **过早把预算翻倍到 12 次 / 40000 token** | 见 §2 实测：关掉结构化步骤的 thinking 后 understand 单次从 1612 降到 908 token（completion 700→75） | 顺序倒过来：A 段先降本，再按实测重新标定；Railway 初期 2 轮、8 次、25000 token，日预算维持 500000 |
| 4 | **每日全量删除重建演示数据** | `app/analytics/demo_data.py:60-70`：`start_date = end_date - (days-1)`，且主键 UUID 由同一 `rng` 顺序生成——跨天重跑是整批平移重建，已落库 `answers` 引用的数字会全部对不上 | C 段改为稳定商品目录 + 按日事实分区；每次补齐全部漏跑日并做外键安全的窗口清理，同一历史分区不改写 |

**另外两处由本稿自行补入：**

- `MAX_QUALITY_ATTEMPTS` 必须**可配置**（审查建议为「代码支持 3 轮，Railway 初期运行 2 轮」），不能写成模块常量。
- Railway Cron **不得复用** `backend/railway.json`：该配置带 `healthcheckPath: /api/health` 与 `preDeployCommand`，一次性任务没有监听端口，健康检查必然失败。

### 第 3 稿审查发现的问题与第 4 稿处置

| # | 第 3 稿问题 | 第 4 稿处置 |
| --- | --- | --- |
| 1 | Reviewer 返回 `passed=false, issues=[]` 时可能被误判为通过 | `ReviewVerdict` 增加双向一致性校验；QualityLoop 必须显式检查 `verdict.passed`，不再以 issues 是否为空代替 verdict |
| 2 | 单请求预算耗尽被归为 `UPSTREAM`，Reviewer 又把预算原因压成布尔值 | 引入共享的类型化 `AttemptFailureKind`；单请求与每日预算统一映射 `BUDGET`，传输/鉴权失败才映射 `UPSTREAM` |
| 3 | 空正文同时被写成“立即降级”和“可重试解析失败” | HTTP 成功但空正文、非法 JSON、字段错误统一作为可回喂的输出校验失败；只有请求未成功到达可用模型结果时立即降级 |
| 4 | `quality_max_attempts` 与 `llm_disable_thinking_for_structured` 只声明未接线 | `app/api/dependencies.py` 纳入变更；前者注入 Graph/QualityLoop，后者由 DeepSeek Adapter 实际决定结构化调用的 thinking 参数 |
| 5 | 计划声称“其余可并行”，但 B2/B5/B6 有未声明依赖 | §7 改为精确依赖图，禁止违反依赖并行 |
| 6 | 旧 FAILED 用量行的悲观预扣无法迁入 `reserved_tokens`，成功响应缺 usage 时又可能释放预扣 | 迁移把旧 FAILED 的 `reserved_tokens` 回填为原 `total_tokens`；Adapter 对缺 usage 明确标记 unknown，默认值改为保守值并配套测试 |
| 7 | 数字守卫未检查建议 title/action | 正文与建议的 title/evidence/action 全部进入同一数字与 UUID 校验 |
| 8 | Railway 生产变更缺独立授权门，新环境变量未登记 | C3 新增部署授权硬门；`.env.example`、`AGENTS.md` 与部署文档同步登记 `ALLOW_DEMO_DATA_REFRESH` |

### 第 4 稿审查发现的问题与第 5 稿处置

第 4 稿被逐条对着代码核对，以下问题都已在代码里找到证据，不是风格意见。

| # | 第 4 稿问题 | 核实依据 | 第 5 稿处置 |
| --- | --- | --- | --- |
| 1 | **B4 的调用次数算漏了 understand 的重试** | `app/intent/service.py:27` `MAX_INTENT_RETRIES = 2`、`:99` `for attempt in range(MAX_INTENT_RETRIES + 1)` —— understand 最坏跑 3 次；且 `app/api/dependencies.py:143-166` 把同一个 guard 同时传给 intent / catalog / answer / reviewer，四者共用一个 `LlmBudget` | Task B4：最坏路径重算为 **9 次**，`MAX_LLM_CALLS_PER_REQUEST` 初期定 **10**；Step 1 改为按调用图逐段列举，禁止再按「understand = 1 次」估算 |
| 2 | **「HTTP 200 + 空正文」的返回值没定义，与 B2 的判据直接冲突** | `app/llm/deepseek.py:64` 现为 `LlmResult(text or fallback, tokens, not bool(text))`：空正文会变成 `text=fallback, degraded=True`，而 B2 的 `compose_once` 见到 `degraded=True` 就立即降级，与 B2 自己的空正文重试用例矛盾 | Task A1 Step 3 增加显式契约小节，写死该路径的四个字段取值，并列出三个下游调用点的行为核对清单 |
| 3 | **A1 去掉 `httpx.HTTPError` 兜底后会漏异常** | httpx 的 `ProtocolError` / `ProxyError` / `UnsupportedProtocol` / `InvalidURL` / `StreamError` 原本被 `HTTPError` 吃掉，改后会逃出 Adapter 变成 500；且 `ConnectError` 本就是 `NetworkError` 的子类 | Task A1 Step 3 补最后一条 `except httpx.HTTPError` 兜底并去掉重复元组，新增「未枚举的 httpx 异常不得逃出 Adapter」的失败测试 |
| 4 | **B2 合并图节点会打断前端 fixture 门禁，计划未登记** | `frontend/src/api/mock/fixtures.generated.ts` 有 7 处写死 `local_validate` / `review_answer` / `decide_retry`；`frontend/package.json` 有 `fixtures:check`，而 B2 Step 9 的门禁命令只有后端 | B2 文件清单补入 fixture 与 `scripts/export_chat_fixtures.py`；Step 9 门禁补 `npm run codegen:check` / `fixtures:check` / `test` |
| 5 | **C2 的随机种子与真正的写入路径不符** | 真正写演示经营数据的是 `backend/scripts/seed_demo_analytics.py:61,84`，用的是每商家 `20260804 + index`；`scripts/seed_demo_data.py` 的 20260730 只 seed 商家表，不生成经营数据 | C2 第 6 条改为沿用 `DEMO_ANALYTICS_SEED_BASE = 20260804` 与 `base + index`；并在 C4 登记旧全量脚本与 Cron 互斥 |
| 6 | 旧全量脚本 `seed_demo_analytics.py` 会 DELETE 六张表再重写，跑一次即抹掉滚动出来的历史，计划未处理 | 该脚本 `_DELETE_ORDER` + `_seed()` 的现有实现 | C2 增加 Step 5：给旧脚本加与 Cron 互斥的护栏；C4 登记它只用于一次性重置 |
| 7 | A2 的 `test_success_payload_without_usage_never_releases_reservation` 造了 `degraded=False` 且 `failure_kind=BAD_PAYLOAD` 的自相矛盾对象 | 该用例本身 | 改为 `failure_kind=None, usage_known=False`，与用例名意图一致 |
| 8 | `ReviewVerdict` 硬性禁止 `passed=true` 带 issues，会把模型很常见的「通过但有小建议」判成不合格，白白吃掉唯一一次重试 | `QUALITY_MAX_ATTEMPTS=2` 下只有一次重试机会 | 改为：`passed=false` 必须非空（保留硬约束）；`passed=true` 时把 issues 归一化为 notes，不再 `ValidationError` |
| 9 | B3 只说 `_validate` 改成返回 issues，但现状有三处 raise，测试只覆盖两类 | `app/services/answer_service.py:141-160` 的 UUID、非加和合计（`_ADDITIVE_CLAIM_PHRASES`）、数字越界三处 | B3 Step 1 补非加和用例，Step 4 明确三处 raise 全部改成 issues |
| 10 | C2 第 9 条写 `await dispose_database()`，该函数不存在 | 实际是 `Database.dispose()`（`app/db/session.py:69`） | 改为 `Database.dispose()`；业务日改为复用既有 `app.analytics.dates.business_today()` |
| 11 | `railway.cron.json` 的 `$schema` 用 `railway.com`，与现有 `backend/railway.json` 的 `railway.app` 不一致 | 两个文件对比 | 统一为 `railway.app` |
| 12 | 文档清扫漏了两处旧「最多两轮」语义 | `docs/project-progress.md:46`、`docs/yshopping-parity-audit.md:200` | B2 Step 6 的文档清单补入这两处 |

### 本稿采用的三个默认方向（待用户明确确认）

- **D1（建议）= 保留并升级数字守卫**：不删除，也不再靠补日期正则；后端先算可信摘要，模型只能引用，守卫据此验证。
- **D2（建议）= 代码支持 3 轮、Railway 初期 2 轮，不立即翻倍预算**：先关 thinking、开 JSON Output、修可观测，再谈上调。
- **D3（建议）= 自动刷新，但改为「独立 Cron + 增量滚动 Seed」**，不采用全量删除重建。

---

## §1 参考项目实现事实（规格来源）

全部出自 `yshopping-merchant-ai 4/yshopping-merchant-ai/`，只读核对，未修改。

### 1.1 统一质量循环 —— `service/PromptLoopAnalysisService.java:45-96`

```java
AnalysisResult fallback = fallback(question, intent, queryBundle, attachments, analysisOnly);
if (!llmClient.isConfigured()) {
    fallback.setLoopStatus("FALLBACK");
    fallback.setLoopAttempts(0);
    fallback.setLoopNotes(List.of("LLM 未配置，使用确定性降级分析"));
    return fallback;
}
for (int attempt = 0; attempt <= MAX_RETRIES; attempt++) {   // MAX_RETRIES = 2 → 共 3 轮
    String prompt = basePrompt;
    if (attempt > 0) {
        prompt += "\n\n上一版输出：\n" + previous
                + "\n校验失败原因：" + String.join("；", errors)
                + "\n请修复所有问题，并重新只输出完整 JSON。";
    }
    String response = llmClient.chat(systemPrompt(), prompt, images, "");
    previous = response;
    AnalysisResult parsed = parse(response);          // 解析失败返回 null，不中断循环
    errors = validate(parsed, analysisOnly);          // validate(null) → "answer 不能为空"
    if (errors.isEmpty()) {
        try { errors = answerReviewService.review(question, intent, queryBundle, parsed, analysisOnly); }
        catch (Exception ignored) { errors = List.of("质检子 agent 调用异常"); }
    }
    if (errors.isEmpty()) {
        parsed.setLoopStatus("PASS");
        parsed.setLoopAttempts(attempt + 1);
        loopNotes.add("第 " + (attempt + 1) + " 轮通过本地校验和独立 reviewer 前后比对");
        return parsed;
    }
    loopNotes.add("第 " + (attempt + 1) + " 轮被打回：" + String.join("；", errors));
}
fallback.setLoopStatus("FALLBACK");
fallback.setLoopAttempts(MAX_RETRIES + 1);
loopNotes.add("达到最大重试次数，使用确定性降级结果");
```

三个要点：**本地校验与独立复核在同一循环**；失败原因**回喂模型**；`loopNotes` **逐轮记录被打回的具体原因**。**解析失败也走重试**，不是直接兜底。

### 1.2 本地校验只有 4 条 —— `PromptLoopAnalysisService.java:152-175`

`answer` 非空、`recommendations` ≥ 2 条、每条建议有 title/evidence/action、`analysisOnly` 时正文无 markdown 表格。**没有数字校验**——数字正确性由 `AnswerReviewService` 的提示词承担（「是否只使用给定 Doris 数字」）。

本稿**有意偏离**：保留数字校验并升级为事实校验，理由见 Task B3。

### 1.3 宽松 JSON 解析 —— `PromptLoopAnalysisService.java:177-192`

截取第一个 `{` 到最后一个 `}`，容忍 markdown 围栏与前后解释文字。

### 1.4 确定性兜底 —— `PromptLoopAnalysisService.java:194-260`

指标类分加和 / 非加和两套措辞，均给出**合计 + 最新日期 + 峰值日期**；另有明细类、附件类、无数据类、`analysisOnly` 无上文四种分支；建议固定两条。

### 1.5 演示数据 —— `backend/tools/seed_yshopping_doris_july.py:32-33`

固定 `2026-07-22 ~ 2026-07-24` 共 3 天，其他区间靠 CLI 传参，**无定时刷新**。全项目唯一 `@Scheduled` 是 `scheduler/DailyReportScheduler.java:28`（日报），与造数无关。

本稿**有意偏离**：我方 180 天滚动窗口优于参考项目的固定 3 天，不复刻。

---

## §2 真实模型实测数据（2026-08-18，规格来源）

模型 `deepseek-v4-flash`，`max_tokens=4096`，同一提示词分别测试：

| 变体 | classify total | understand total | understand completion | reasoning_tokens | 输出合法 JSON |
| --- | --- | --- | --- | --- | --- |
| 基线 | 403 | 1612 | 700 | 624 | 是 |
| `response_format={"type":"json_object"}`（thinking 开着） | 593 | — | — | 202 | 是 |
| `reasoning_effort="none"` | 291 | **908** | **75** | **字段消失** | 是 |
| `thinking={"type":"disabled"}` | 286 | — | — | **字段消失** | 是 |
| `reasoning_effort="none"` + `json_object` | — | 928 | 75 | **字段消失** | 是 |

**结论：**

1. 两个关闭推理的参数都真实生效——`reasoning_tokens` 字段整个消失、completion 从 700 掉到 75，不是被静默忽略。
2. 关闭推理后 understand 单次省 **44%**，延迟随 completion 同步下降。
3. **`json_object` 单独使用时曾适得其反**：2026-08-17 实测在 thinking 开着的情况下 `reasoning_tokens` 涨到 4096、`content` 返回空、`finish_reason=length`。必须与关闭推理配对使用。
4. 关闭推理的范围**只限结构化步骤**（classify、understand、指标口径、Reviewer）。**回答生成保留推理**——趋势解读需要它，实测基线正是靠 193~624 reasoning tokens 产出可用的分析文字。

---

## §3 文件结构

| 文件 | 职责 | 变更 |
| --- | --- | --- |
| `backend/app/llm/client.py` | LLM 协议与单请求预算 | 改：新增 `LlmCallOptions`、受控 `LlmFailureKind`，把 JSON 输出、thinking 策略、usage 是否可知分开表达 |
| `backend/app/llm/deepseek.py` | DeepSeek 适配器 | 改：按 `LlmCallOptions` 下发官方 `thinking` 开关与 JSON Output；上游错误不再静默 |
| `backend/app/llm/guard.py`、`backend/app/llm/fake.py` | 费用守卫与测试模型 | 改：完整透传并记录 `LlmCallOptions`；失败预扣按已知/未知用量核销 |
| `backend/app/models/operations.py`、`backend/app/repositories/llm_budget.py` | 用量记账 | 改：写入真实 token、失败类型、预扣量与 usage 是否可知 |
| `backend/app/intent/service.py`、`app/metrics/catalog.py`、`app/services/review_service.py` | 结构化调用点 | 改：传 `options=STRUCTURED_CALL_OPTIONS` |
| `backend/app/schemas/answer.py` | 草稿与 Reviewer 内部契约 | 改：约束 `ReviewVerdict.passed` 与 `issues` 双向一致 |
| `backend/app/services/quality_types.py` | **新建**：质量循环共享类型 | 新建：`AttemptFailureKind`、`DraftAttempt`、`ReviewAttempt`、`DegradeReason`、`QualityOutcome`，避免服务之间用无类型布尔值传递失败原因 |
| `backend/app/services/answer_service.py` | 草稿、校验、兜底、事实摘要 | 大改：宽松解析、`_validate` 返回 issues、事实摘要、兜底文案；正文和建议全部字段统一校验 |
| `backend/app/services/quality_loop.py` | **新建**：统一质量循环 | 新建 |
| `backend/app/agent/graph.py` | 编排 | 改：两节点合并为调用 `QualityLoop`；`degraded_reason` 据实分类 |
| `backend/app/api/dependencies.py` | 请求级依赖装配 | 改：把 `quality_max_attempts` 注入 Graph/QualityLoop，确保 Railway 配置真实生效 |
| `backend/app/core/config.py` | Web 配置 | 改：`quality_max_attempts`、结构化 thinking 策略开关、调用与 token 上限 |
| `backend/app/core/seed_config.py` | **新建**：Seed 专用最小配置 | 部署只需数据库、环境、业务时区与显式刷新开关；数据库超时/重试用安全默认值，不加载 Web/导出/LLM 密钥约束 |
| `backend/app/analytics/demo_data.py` | 演示数据生成 | 改：稳定商品目录与按业务日确定的事实分区，单日结果与窗口无关 |
| `backend/app/jobs/seed_demo_rolling.py` | **新建**：增量滚动 Seed 的可执行模块 | 随现有 `COPY app ./app` 自动进入后端镜像 |
| `backend/railway.cron.json` | **新建**：Cron 专用配置 | 新建（无健康检查、无 preDeploy） |
| `.env.example`、`AGENTS.md`、`docs/deployment.md`、`docs/yshopping-parity-audit.md`、`docs/project-progress.md` | 配置示例与文档 | 改：同步质量循环变量、Seed 独立写权限、目录索引与偏离登记 |

---

## §4 A 段 —— 先降本与补可观测

### Task A1: DeepSeek 客户端不再静默吞掉上游错误

**Files:**
- Modify: `backend/app/llm/deepseek.py`
- Modify: `backend/app/llm/client.py`（新增受控的失败类型）
- Modify: `backend/app/llm/fake.py`，以及构造成功 `LlmResult` 的测试替身（显式 `usage_known=True`）
- Test: `backend/tests/unit/llm/test_deepseek_client.py` 与受影响的 Fake/Graph/Guard 单元测试

**背景：** 当前 `except (httpx.HTTPError, ValueError): return LlmResult(fallback, 0, True)` 把 401、超时、限流、网络不通压成同一个无声降级，一行日志都没有。2026-08-18 的 `LLM_API_KEY` 误填事故因此排查了近一小时——界面显示「模型没理解你的问题」，真实原因是 DeepSeek 一律返回 401。

**Interfaces:**
- 新增 `LlmFailureKind(StrEnum)`：`HTTP_401` / `HTTP_403` / `HTTP_429` / `HTTP_OTHER` / `TIMEOUT` / `NETWORK` / `BAD_PAYLOAD`。非 401/403/429 的状态码统一落 `HTTP_OTHER`，原始状态码只作为单独的非敏感日志字段记录，禁止用 `f"HTTP_{status}"` 绕过受控枚举。
- Extend `LlmResult`: `input_tokens: int = 0`、`output_tokens: int = 0`、`failure_kind: LlmFailureKind | None = None`、`usage_known: bool = False`；保留前三个位置参数兼容既有 fake 与测试，但所有生产 Adapter 与 Fake 成功结果必须显式填写 `usage_known=True`，不得靠不安全默认值推断。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_upstream_401_is_recorded_and_logged_not_silently_swallowed(caplog) -> None:
    """401 被压成「模型没理解问题」会让排查完全跑偏（2026-08-18 实际发生过）。"""

    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad key"}))
    client = DeepSeekLlmClient(_settings(), transport=transport)

    result = await client.complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(max_calls=2, max_tokens=1000)
    )

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.HTTP_401
    assert any(record.message == "llm_upstream_failed" for record in caplog.records)
    assert all("bad key" not in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_unlisted_http_status_uses_controlled_other_kind() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
    result = await DeepSeekLlmClient(_settings(), transport=transport).complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(max_calls=2, max_tokens=1000)
    )

    assert result.failure_kind is LlmFailureKind.HTTP_OTHER


@pytest.mark.asyncio
async def test_malformed_success_payload_is_controlled_bad_payload() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    result = await DeepSeekLlmClient(_settings(), transport=transport).complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(max_calls=2, max_tokens=1000)
    )

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.BAD_PAYLOAD
    assert result.usage_known is False


@pytest.mark.asyncio
async def test_unenumerated_httpx_error_still_degrades_instead_of_escaping() -> None:
    """去掉 `except httpx.HTTPError` 兜底会让 ProtocolError 一类异常逃出适配器变成 500。

    httpx 的 ProtocolError / ProxyError / UnsupportedProtocol / InvalidURL / StreamError
    原本都被那条兜底吃掉；只列 HTTPStatusError / TimeoutException / NetworkError 是漏的。
    """

    def raise_protocol_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("bad chunk", request=request)

    result = await DeepSeekLlmClient(
        _settings(), transport=httpx.MockTransport(raise_protocol_error)
    ).complete(
        system="s", user="u", fallback="{}", budget=LlmBudget(max_calls=2, max_tokens=1000)
    )

    assert result.degraded is True
    assert result.failure_kind is LlmFailureKind.NETWORK


@pytest.mark.asyncio
async def test_successful_response_with_empty_content_is_not_a_transport_failure() -> None:
    """合法 200 + 空正文属于「模型输出不合格」，必须让 B2 能重试，而不是伪装成上游故障。

    现状 deepseek.py:64 `LlmResult(text or fallback, tokens, not bool(text))` 会把它变成
    `text=fallback, degraded=True`，B2 的 compose_once 见到 degraded 就立即降级——
    与 B2 自己的空正文重试用例直接冲突。
    """

    payload = _ok_payload(content="", usage={"prompt_tokens": 120, "completion_tokens": 0,
                                             "total_tokens": 120})
    result = await DeepSeekLlmClient(
        _settings(), transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ).complete(
        system="s", user="u", fallback='{"answer":"兜底"}',
        budget=LlmBudget(max_calls=2, max_tokens=1000),
    )

    assert result.text == ""            # 不得回落成 fallback
    assert result.degraded is False
    assert result.failure_kind is None
    assert result.usage_known is True
    assert result.tokens == 120         # 真实 usage 照记，费用不能丢
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/llm/test_deepseek_client.py -v`
Expected: FAIL —— `LlmResult` 没有 `failure_kind`

- [ ] **Step 3: 最小实现**

```python
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            kind = {
                401: LlmFailureKind.HTTP_401,
                403: LlmFailureKind.HTTP_403,
                429: LlmFailureKind.HTTP_429,
            }.get(status_code, LlmFailureKind.HTTP_OTHER)
        except httpx.TimeoutException:
            status_code = None
            kind = LlmFailureKind.TIMEOUT
        except httpx.NetworkError:
            # ConnectError / ReadError / WriteError / CloseError 都是它的子类，不必重复列。
            status_code = None
            kind = LlmFailureKind.NETWORK
        except ValueError:
            status_code = None
            kind = LlmFailureKind.BAD_PAYLOAD
        except httpx.HTTPError:
            # 兜底必须留：ProtocolError / ProxyError / UnsupportedProtocol / InvalidURL /
            # StreamError 原本被旧的 `except httpx.HTTPError` 吃掉，只枚举上面三类会让它们
            # 逃出适配器变成 500。放在具体分支之后，不影响上面的精确归类。
            status_code = None
            kind = LlmFailureKind.NETWORK
        else:
            status_code = None
            kind = None
        if kind is not None:
            logger.warning(
                "llm_upstream_failed",
                failure_kind=kind.value,
                status_code=status_code,
                model=self._settings.llm_model,
            )
            return LlmResult(
                fallback,
                0,
                True,
                failure_kind=kind,
                usage_known=kind in {LlmFailureKind.HTTP_401, LlmFailureKind.HTTP_403},
            )
```

非 HTTP 分支令 `status_code=None`。日志**只记受控失败类型、状态码与模型名**，不记响应正文、提示词正文或 API Key（R6、日志脱敏）。测试必须用 `caplog` 同时证明事件存在且响应错误正文、system/user 与密钥均未进入日志。由于 `usage_known` 默认改为保守的 false，本任务同一步把 Fake 和所有“成功返回”的测试替身改为显式 true，确保 A1 自己的全量门禁即可通过，不把修复拖到 A3。

`response.json()` 之后必须显式校验顶层为对象、`choices` 为非空列表、首项 message/content 形状合法；任何形状错误统一返回 `BAD_PAYLOAD`，不得让 `.get()` 的 `AttributeError` 或错误索引逃出 Adapter。

**「HTTP 200 + 空正文」的返回值必须写死，不能只写在散文里。** 现状 `deepseek.py:64` 是 `LlmResult(text or fallback, tokens, not bool(text))`，空正文会被写成 `text=fallback, degraded=True`；而 B2 的 `compose_once` 见到 `degraded=True` 就立即降级，与 B2 的空正文重试用例正面冲突。本任务改成：

| 场景 | `text` | `degraded` | `failure_kind` | `usage_known` | `tokens` |
| --- | --- | --- | --- | --- | --- |
| 200 + 正文非空 + usage 完整 | 模型正文 | `False` | `None` | `True` | 真实 total |
| **200 + 正文为空 + usage 完整** | **`""`（不回落 fallback）** | **`False`** | **`None`** | **`True`** | **真实 total** |
| 200 + 正文为空 + 缺 usage | `""` | `False` | `None` | `False` | 0 |
| 200 但结构非法 | fallback | `True` | `BAD_PAYLOAD` | `False` | 0 |
| 传输/状态码失败 | fallback | `True` | 对应 kind | 见上文 | 0 |

即：`fallback` 参数从此只服务于「请求未成功拿到可用模型结果」这一类，成功响应一律返回模型的真实正文（含空串），由服务层判定合格与否。

**这条改动会改变三个既有调用点看到的 `degraded` 语义，本任务必须逐个核对并补测试：**

- `app/intent/service.py:54,101` 与 `app/metrics/catalog.py:99` 用 `_object(result.text)` 判空，空串仍返回 `None`，行为不变——但要有测试钉住这一点；
- `app/services/review_service.py:39` 现在靠 `if result.degraded` 判定「Reviewer 暂不可用」，改动后空正文会从「上游不可用」变成「输出不合格」。这正是 B2 想要的分类，但它是 A1 引入的行为变化，必须在 A1 就有测试覆盖，不能留给 B2 顺手发现；
- `app/services/answer_service.py:83` 的旧 `compose()` 在 B2 被 `compose_once()` 取代前仍在生产路径上，A1 交付后到 B2 交付前的中间态里，空正文会从「降级兜底」变成「解析空串抛 ValueError → 走 `except (ValueError, ...)` → 仍然降级兜底」，最终对用户表现不变。要有一条测试钉住这个中间态不回归。

- [ ] **Step 4: 跑测试确认通过 → Step 5: 全量门禁 → Step 6: 检查 diff**

Run: `uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app && git diff`

### Task A2: 用量记账修正

**Files:**
- Modify: `backend/app/llm/deepseek.py`、`app/llm/guard.py`、`app/models/operations.py`、`app/repositories/llm_budget.py`
- Create: `backend/migrations/versions/20260818_0011_extend_llm_usage_observability.py`
- Test: `backend/tests/unit/llm/test_guard.py`、`backend/tests/integration/repositories/test_llm_budget_repository.py`

**背景：** `llm_usage.input_tokens` / `output_tokens` 恒为 0，只有 `total_tokens` 有值；且 `status="FAILED"` 的行记的是 `LlmCostGuard` 的**悲观估算值**（`len(system)+len(user)+max_output`）而非真实用量。2026-08-18 排查时正是这一点让「4678 tokens」被误读成真实消耗，进而推出错误结论。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_usage_row_records_real_prompt_and_completion_tokens() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[3_000])
    inner = StubInnerClient(
        result=LlmResult(
            text="ok", tokens=2_778, degraded=False,
            input_tokens=508, output_tokens=2_270,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback",
        budget=LlmBudget(max_calls=4, max_tokens=8_000),
    )
    row = repository.record_usage_calls[-1]

    assert row.input_tokens == 508
    assert row.output_tokens == 2270


@pytest.mark.asyncio
async def test_http_401_records_known_zero_tokens_and_releases_reservation() -> None:
    """401 明确未进入模型执行，可释放预扣并记 usage_known=true、实际 0。"""

    repository = FakeLlmBudgetRepository(reserve_returns=[500])
    inner = StubInnerClient(
        result=LlmResult(
            text="fallback", tokens=0, degraded=True,
            failure_kind="HTTP_401", usage_known=True,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback",
        budget=LlmBudget(max_calls=4, max_tokens=8_000),
    )
    row = repository.record_usage_calls[-1]

    assert row.total_tokens == 0
    assert row.status == "FAILED"
    assert row.failure_kind == "HTTP_401"
    assert row.usage_known is True
    assert row.reserved_tokens > 0
    assert repository.reconcile_calls[-1].delta == -repository.reserve_calls[0].tokens


@pytest.mark.asyncio
async def test_timeout_keeps_conservative_reservation_and_marks_usage_unknown() -> None:
    """超时可能发生在上游已经开始生成之后，不能把未知费用伪装成真实 0。"""

    repository = FakeLlmBudgetRepository(reserve_returns=[500])
    inner = StubInnerClient(
        result=LlmResult(
            text="fallback", tokens=0, degraded=True,
            failure_kind="TIMEOUT", usage_known=False,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback",
        budget=LlmBudget(max_calls=4, max_tokens=8_000),
    )
    row = repository.record_usage_calls[-1]

    assert row.total_tokens == 0
    assert row.failure_kind == "TIMEOUT"
    assert row.usage_known is False
    assert row.reserved_tokens > 0
    assert repository.reconcile_calls == [], "未知费用保留悲观预扣，防止日预算超发"


@pytest.mark.asyncio
async def test_success_payload_without_usage_never_releases_reservation() -> None:
    """有正文但缺 usage 不能借 `usage_known` 的默认值冒充零费用。

    注意结果对象本身必须自洽：这是一次**成功**调用（`degraded=False`），只是响应里没给
    usage，所以 `failure_kind` 必须是 `None`。第 4 稿这里写成 `BAD_PAYLOAD` 与 degraded=False
    并存，是自相矛盾的构造——BAD_PAYLOAD 意味着结构非法，那条路径 `degraded` 必为 True。
    """

    repository = FakeLlmBudgetRepository(reserve_returns=[500])
    inner = StubInnerClient(
        result=LlmResult(
            text='{"answer":"ok"}', tokens=0, degraded=False,
            usage_known=False, failure_kind=None,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback",
        budget=LlmBudget(max_calls=4, max_tokens=8_000),
    )

    assert repository.reconcile_calls == []
    assert repository.record_usage_calls[-1].reserved_tokens == 500
    assert repository.record_usage_calls[-1].usage_known is False
```

- [ ] **Step 2: 跑测试确认失败 → Step 3: 从 `usage.prompt_tokens` / `usage.completion_tokens` 透传并落库；失败行同时记录 `reserved_tokens` / `usage_known` / `failure_kind` → Step 4: 按失败类型核销预扣 → Step 5: 确认通过 → Step 6: 全量门禁 → Step 7: 检查 diff**

同步扩展 `LlmBudgetRepository.record_usage()` 与 `FakeLlmBudgetRepository` 的调用记录：`input_tokens`、`output_tokens`、`reserved_tokens`、`usage_known`、`failure_kind` 都必须是显式关键字参数；禁止继续用单个 `tokens` 同时表示“实际用量”和“预扣上限”。

预扣核销规则必须写死并测试：收到完整、可解析的真实 usage 时按实际值 reconcile；明确在鉴权阶段拒绝的 401/403 释放预扣；429、TIMEOUT、NETWORK、响应缺少 usage 或 usage 字段不完整时，保留悲观预扣并记 `usage_known=false`，除非 DeepSeek 响应明确给出可核验的 usage。正文存在不代表 usage 已知，禁止因 `total_tokens=0` 自动释放预扣。每日熔断统计使用“已知实际 token + 未知调用的 reserved token”，运维报表不得把未知调用的 `total_tokens=0` 解释为真实零费用。

**`guard.py` 的分支判据必须从 `result.degraded` 改为 `result.usage_known`。** 现状 `app/llm/guard.py:95` 是 `if result.degraded and result.tokens == 0:` 记 FAILED、否则 reconcile；A1 之后「成功但缺 usage」是 `degraded=False, tokens=0`，会落进 reconcile 分支把预扣按 `0 - estimated` 全额释放，正好是本组测试要拦的行为。改后的判据固定为：`usage_known=True` 才 reconcile，其余一律保留预扣。`status` 仍按调用是否成功记（成功但缺 usage 记 `SUCCEEDED`，`usage_known=false`），不要把「usage 未知」和「调用失败」混成同一个状态。`except BaseException` 那条路径也要同步记 `reserved_tokens=estimated, usage_known=false`。

**迁移：** 给 `llm_usage` 增加可空 `failure_kind`、带 `CHECK (reserved_tokens >= 0)` 的 `reserved_tokens`（默认 0）与 `usage_known` 三列。回填规则固定为：既有 `SUCCEEDED` 行 `usage_known=true, reserved_tokens=0`；既有 `FAILED` 行 `usage_known=false, reserved_tokens=total_tokens`，因为旧 `total_tokens` 正是当时保留的悲观预扣；既有 `BUDGET_REJECTED` 行 `usage_known=true, reserved_tokens=0`。保留所有原 token 列不改写。迁移升级/降级测试必须覆盖三类既有行，并断言负 `reserved_tokens` 被数据库拒绝。

### Task A3: 结构化步骤关闭推理并启用 JSON Output

**Files:**
- Modify: `backend/app/llm/client.py`（新增 `LlmCallOptions`）、`app/llm/deepseek.py`、`app/llm/guard.py`、`app/llm/fake.py`
- Modify: `backend/app/intent/service.py`（2 处）、`app/metrics/catalog.py`、`app/services/review_service.py`
- Modify: `backend/app/core/config.py`（新增 `llm_disable_thinking_for_structured: bool = True`）
- Test: `backend/tests/unit/llm/test_deepseek_client.py`、`backend/tests/unit/llm/test_guard.py`、`backend/tests/unit/intent/test_prompts.py`、指标口径与 Reviewer 提示词测试，以及实现 `LlmClient` 的图测试替身

**依据：** §2 实测。**回答生成（`answer_service.py`）不传 `STRUCTURED_CALL_OPTIONS`**——趋势解读需要推理；它使用独立的回答生成选项。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_structured_call_disables_thinking_and_requests_json_output() -> None:
    """结构化抽取不需要推理。实测 understand 关掉后单次从 1612 降到 908 token
    （completion 700→75），且输出仍是合法 JSON（见计划 §2）。

    json_object 必须与关闭推理配对：2026-08-17 单独启用时 reasoning 涨到 4096、
    content 返回空、finish_reason=length。
    """

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload())

    client = DeepSeekLlmClient(_settings(), transport=httpx.MockTransport(handler))
    await client.complete(
        system="s", user="u", fallback="{}",
        budget=LlmBudget(max_calls=2, max_tokens=1000), options=STRUCTURED_CALL_OPTIONS,
    )

    assert captured["thinking"] == {"type": "disabled"}
    assert captured["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_answer_generation_keeps_thinking() -> None:
    """回答生成保留推理——趋势解读靠它产出可用的分析文字。"""

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload())

    client = DeepSeekLlmClient(_settings(), transport=httpx.MockTransport(handler))
    await client.complete(
        system="s", user="u", fallback="{}",
        budget=LlmBudget(max_calls=2, max_tokens=1000),
    )

    assert captured.get("thinking") != {"type": "disabled"}


@pytest.mark.asyncio
async def test_structured_thinking_kill_switch_is_really_wired() -> None:
    """配置为 false 时必须覆盖结构化调用选项，而不是留下一个无人读取的假开关。

    关掉开关 = 回到基线行为 = **完全不下发 `thinking` 字段**，与回答生成走同一条路径。
    不主动下发 `{"type":"enabled"}`：一是同一个语义没必要有两种线上表达，二是我们只
    实测过 disabled 分支，对未验证的取值主动发值有被上游 400 的风险（§2 只测了 disabled）。
    同理 json_object 也随之关闭——§2 结论 3 要求它必须与关闭推理配对。
    """

    captured: dict[str, object] = {}
    client = DeepSeekLlmClient(
        _settings(llm_disable_thinking_for_structured=False),
        transport=_capturing_transport(captured),
    )
    await client.complete(
        system="只输出 JSON：示例 {\"ok\":true}", user="u", fallback="{}",
        budget=LlmBudget(max_calls=2, max_tokens=1000), options=STRUCTURED_CALL_OPTIONS,
    )

    assert "thinking" not in captured
    assert "response_format" not in captured
```

- [ ] **Step 2: 跑测试确认失败 → Step 3: 新增显式调用选项并实现 → Step 4: 确认通过**

```python
@dataclass(frozen=True)
class LlmCallOptions:
    json_output: bool = False
    thinking: Literal["enabled", "disabled"] = "enabled"


STRUCTURED_CALL_OPTIONS = LlmCallOptions(json_output=True, thinking="disabled")
```

不得使用未写入官方参数枚举的 `reasoning_effort="none"`。JSON 输出与 thinking 是两个独立维度，不能继续用一个含义过载的 `structured: bool` 表达。`LlmCostGuard.complete()` 与 `FakeLlmClient.complete()` 必须接收并原样透传/记录 `options`；所有测试替身同步签名，否则生产包装器会在结构化调用时首先报 `TypeError`。

`llm_disable_thinking_for_structured` 的接线规则固定为：调用点声明“这是结构化调用”；DeepSeek Adapter 在该配置为 true 时下发 `thinking={"type":"disabled"}` 与 `response_format={"type":"json_object"}`，为 false 时**两个字段都不下发**（回到基线请求体）。测试必须证明 true/false 两路请求体不同；若不准备支持运行期关闭该策略，就删除该配置字段而不是留下假开关。

`response_format` 只有在 thinking 实际被关闭时才下发——§2 结论 3 的实测是「json_object 单独启用会让 reasoning 涨到 4096、content 返回空」，所以这两个字段在 Adapter 里必须成对出现，不允许出现只有 json_object 的请求体。这一条也要有测试。

- [ ] **Step 5: 四个结构化调用点传 `options=STRUCTURED_CALL_OPTIONS`**

`intent/service.py:54`（classify）、`intent/service.py:101`（understand）、`metrics/catalog.py:99`（指标口径）、`services/review_service.py:34`（Reviewer）传 `options=STRUCTURED_CALL_OPTIONS`。

**回答生成不传 `options`，即取 `LlmCallOptions()` 默认值 `json_output=False, thinking="enabled"`**，也就是完全不下发这两个字段、保持 2026-08-18 已验证可用的基线请求体。这不是「待定的独立选项」——它必须现在就定死为默认值，否则 B1 的宽松解析（专为「模型在 JSON 外面加围栏和解释文字」而写）与「回答走 json_object」这两条设计会互相矛盾。回答生成开启 JSON Output 属于单独的后续实验，需要先按 §2 的方法实测，不在本计划范围。

- [ ] **Step 6: 补 JSON Output 提示词契约测试**

四个结构化提示词都必须同时包含“只输出 JSON”与可由测试解析的合法 JSON 示例。`classify`/`understand` 复用现有从 Pydantic/枚举推导的契约测试；指标口径提示词补完整 `{display_name, unit, definition}` 示例；Reviewer 示例同时覆盖通过与拒绝形态。测试不得只搜索字段名，必须把示例片段提取出来并交给对应 Pydantic 模型或显式字段集合校验。

- [ ] **Step 7: 全量门禁 + 检查 diff**

### Task A4: A 段真实模型验收（**执行前按 R3 单独取得同意**）

- [ ] **Step 1: 说明费用并取得同意** —— 4 个定向样例；若直接调用单个组件则固定 **4 次模型请求**，若走端到端链路则按调用图列出实际期望与最坏上限（不得只报“4 条问题”）；模型 `deepseek-v4-flash`，预计 1.5~2 万 token，**会真实计费**。用户确认的调用上限写入验收记录，执行时不得超出。
- [ ] **Step 2: 用四个定向样例分别覆盖 classify、understand、生成指标 catalog 与 Reviewer**；优先直接调用目标组件以避免无关模型费用。每次记 input/output/total token、`usage_known`、目标步骤是否实际命中、质量状态与端到端耗时。
- [ ] **Step 3: 出口判据** —— 结构化步骤 token 较基线下降 ≥ 30%；每条 `answer_mode` / `category` / catalog 字段与预先写定的期望值一致，不能以可能本身错误的旧基线当正确答案；Reviewer 必须真实执行且给出合法 verdict。
- [ ] **Step 4: 把实测数字写进 `docs/project-progress.md`，并据此重新标定 §5 Task B4 的预算。**

---

## §5 B 段 —— 质量循环与事实校验

### Task B1: 宽松 JSON 解析

**Files:**
- Modify: `backend/app/services/answer_service.py`、`app/services/review_service.py`
- Test: `backend/tests/unit/services/test_answer_service.py`

**Interfaces:**
- Produces: `extract_json_object(text: str) -> str`

- [ ] **Step 1: 写失败测试**

```python
def test_extract_json_object_strips_markdown_fence_and_prose() -> None:
    """参考实现 PromptLoopAnalysisService.parse() 截取第一个 { 到最后一个 }。"""

    from app.services.answer_service import extract_json_object

    assert extract_json_object('```json\n{"answer":"x"}\n```') == '{"answer":"x"}'
    assert extract_json_object('好的：{"answer":"x"} 以上。') == '{"answer":"x"}'
    assert extract_json_object('{"answer":"x"}') == '{"answer":"x"}'
    assert extract_json_object("没有花括号") == "没有花括号"
```

- [ ] **Step 2: 跑测试确认失败**（`ImportError`）→ **Step 3: 实现**

```python
def extract_json_object(text: str) -> str:
    """截取第一个 `{` 到最后一个 `}`。

    与参考实现同口径：模型偶尔在 JSON 前后加围栏或解释文字，整串直接解析会失败，
    但内部那段 JSON 本身是好的。找不到成对花括号时原样返回，让调用方拿到真实错误。
    """

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return text
    return text[start : end + 1]
```

- [ ] **Step 4: 确认通过 → Step 5: 接进 `AnswerDraft` 与 `ReviewVerdict` 两处解析 → Step 6: 全量门禁 → Step 7: 检查 diff**

### Task B2: 统一质量循环（修正第 1 稿两处缺陷）

> **执行依赖：** 虽然本节为便于先解释循环而排在 B3 前面，实际实施必须先完成 B1 与 B3；B2 直接消费 B1 的 `extract_json_object()` 和 B3 的 `validate_issues() -> list[str]` / `FactSummary`。未满足依赖时不得并行开工。

**Files:**
- Create: `backend/app/services/quality_types.py`、`backend/app/services/quality_loop.py`、`backend/tests/unit/services/test_quality_loop.py`
- Modify: `backend/app/services/answer_service.py`、`app/services/review_service.py`、`app/agent/graph.py`、`app/api/dependencies.py`、`app/core/config.py`、`app/schemas/answer.py`、`app/schemas/chat.py`
- Modify first: `docs/PRD.md`、`docs/backend-development-plan.md`
- Regenerate/modify: `docs/api.md`、`docs/api.json`、`frontend/src/api/generated.ts`、`frontend/src/api/adapters/chat.ts`、**`frontend/src/api/mock/fixtures.generated.ts`**（由 `backend/scripts/export_chat_fixtures.py` + `npm run fixtures` 重新生成）
- Test: `backend/tests/unit/schemas/test_chat.py`、`frontend/src/api/adapters/chat.spec.ts`、OpenAPI/codegen 漂移门禁、**前端 fixture 漂移门禁 `npm run fixtures:check`**

**Interfaces:**

```python
class AttemptFailureKind(StrEnum):
    UPSTREAM = "UPSTREAM"
    BUDGET = "BUDGET"


class DegradeReason(StrEnum):
    UPSTREAM = "UPSTREAM"        # 模型不可用 / HTTP 失败 / 返回空正文
    VALIDATION = "VALIDATION"    # 校验或复核未通过且轮次用尽
    BUDGET = "BUDGET"            # 单请求或每日预算耗尽


@dataclass(frozen=True)
class QualityOutcome:
    draft: AnswerDraft
    status: QualityStatus        # PASSED / DEGRADED / FAILED / NOT_RUN
    attempts: int
    notes: list[str]
    reason: DegradeReason | None


@dataclass(frozen=True)
class DraftAttempt:
    draft: AnswerDraft | None
    raw_text: str
    failure_kind: AttemptFailureKind | None


@dataclass(frozen=True)
class ReviewAttempt:
    verdict: ReviewVerdict | None
    raw_text: str
    issues: tuple[str, ...]
    failure_kind: AttemptFailureKind | None
```

以上共享类型放在 `quality_types.py`，`answer_service.py` 与 `review_service.py` 只依赖它，不反向 import `QualityLoop`，避免循环导入。`QualityLoop` 的公开接口固定为构造器 `QualityLoop(*, max_attempts: int, answer_service: AnswerService | None = None, review_service: ReviewService | None = None)`，以及异步方法 `run(facts: AnswerFacts, answer_llm: LlmClient, reviewer_llm: LlmClient | None, budget: LlmBudget) -> QualityOutcome`。禁止继续用 `upstream_failed: bool` 同时承载服务故障与预算耗尽。

- [ ] **Step 1: 写三条失败测试（分别覆盖第 1 稿的两处缺陷与主路径）**

```python
@pytest.mark.asyncio
async def test_unparsable_draft_is_retried_not_immediately_degraded() -> None:
    """第 1 稿缺陷 1：解析失败直接兜底。

    参考实现是 validate(null) → 记「answer 不能为空」→ 继续下一轮。解析失败恰恰是
    「回喂原因让它重写」最该救的场景。
    """

    good = _valid_draft_json()
    llm = FakeLlmClient(responses=["这不是 JSON", good, '{"passed":true,"issues":[]}'])

    outcome = await QualityLoop(max_attempts=3).run(
        _trend_facts(), llm, llm, LlmBudget(max_calls=12, max_tokens=40_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 2
    assert any("无法解析" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_missing_reviewer_is_visible_degradation_never_passed() -> None:
    """第 1 稿缺陷 2：Reviewer 缺失却标记 PASSED 并写「通过独立复核前后比对」。

    复核没跑就说跑过，既是假话也违反 R7（降级与未执行必须对用户可见）。
    """

    llm = FakeLlmClient(responses=[_valid_draft_json()])

    outcome = await QualityLoop(max_attempts=3).run(
        _trend_facts(), llm, None, LlmBudget(max_calls=12, max_tokens=40_000)
    )

    assert outcome.status is QualityStatus.DEGRADED
    assert outcome.reason is DegradeReason.UPSTREAM
    assert any("未执行独立复核" in note for note in outcome.notes)
    assert not any("通过" in note and "复核" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_validation_issues_are_fed_back_into_the_next_prompt() -> None:
    bad = _draft_json(answer="退货量为 98765 件。")
    llm = FakeLlmClient(responses=[bad, _valid_draft_json(), '{"passed":true,"issues":[]}'])

    outcome = await QualityLoop(max_attempts=3).run(
        _trend_facts(), llm, llm, LlmBudget(max_calls=12, max_tokens=40_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert "98765" in llm.calls[1][1], "第二轮提示词必须带上一轮的失败原因"


@pytest.mark.asyncio
async def test_invalid_reviewer_payload_is_fed_back_and_retried() -> None:
    """Reviewer 的非法 JSON 是一次不合格复核输出，不等同于 HTTP/网络不可用。"""

    llm = FakeLlmClient(
        responses=[_valid_draft_json(), "not-json", _valid_draft_json(), '{"passed":true,"issues":[]}']
    )
    outcome = await QualityLoop(max_attempts=2).run(
        _trend_facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 2
    assert any("Reviewer 输出无法解析" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_successful_http_with_empty_content_is_retried_as_invalid_output() -> None:
    llm = FakeLlmClient(responses=["", _valid_draft_json(), '{"passed":true,"issues":[]}'])

    outcome = await QualityLoop(max_attempts=2).run(
        _trend_facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 2
    assert any("模型返回空正文" in note for note in outcome.notes)


def test_reviewer_rejection_cannot_have_an_empty_issue_list() -> None:
    """打回却不说哪里错，回喂就没有内容可回喂，等于白跑一轮。这条保持硬约束。"""

    with pytest.raises(ValidationError):
        ReviewVerdict.model_validate({"passed": False, "issues": []})


def test_reviewer_pass_with_advisory_issues_is_normalized_not_rejected() -> None:
    """`{"passed":true,"issues":["建议补充同比"]}` 是模型很常见的输出形态。

    第 4 稿把它判成 ValidationError → 按「输出不合格」重试；在 QUALITY_MAX_ATTEMPTS=2 下
    这会吃掉唯一一次重试机会，把一个已经通过复核的回答推向降级。改为归一化：
    passed=true 时 issues 清空并转成 advisory 备注，进 quality_notes 供用户可见。
    """

    verdict = ReviewVerdict.model_validate({"passed": True, "issues": ["建议补充同比"]})

    assert verdict.passed is True
    assert verdict.issues == []
    assert verdict.advisory_notes == ["建议补充同比"]


@pytest.mark.asyncio
async def test_advisory_notes_from_a_passing_reviewer_reach_quality_notes() -> None:
    llm = FakeLlmClient(
        responses=[_valid_draft_json(), '{"passed":true,"issues":["建议补充同比"]}']
    )

    outcome = await QualityLoop(max_attempts=2).run(
        _trend_facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 1
    assert any("建议补充同比" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_per_request_budget_exhaustion_is_reported_as_budget_not_upstream() -> None:
    llm = RaisingLlmClient(LlmBudgetExceededError("request cap"))

    outcome = await QualityLoop(max_attempts=2).run(
        _trend_facts(), llm, llm, LlmBudget(max_calls=1, max_tokens=100)
    )

    assert outcome.status is QualityStatus.DEGRADED
    assert outcome.reason is DegradeReason.BUDGET
```

- [ ] **Step 2: 跑测试确认全部失败**（`ModuleNotFoundError`）

- [ ] **Step 3: 在 `AnswerService` 上开出三个接缝**

```python
    async def compose_once(
        self, facts, llm, budget, *, previous: str = "", issues: Sequence[str] = ()
    ) -> DraftAttempt:
        """一次生成尝试。重试语义归 QualityLoop 掌握，这里不吞预算类异常。"""

        user = _facts_json(facts)
        if previous and issues:
            user += (
                "\n\n上一版输出：\n" + previous
                + "\n校验失败原因：" + "；".join(issues)
                + "\n请修复所有问题，并重新只输出完整 JSON。"
            )
        result = await llm.complete(
            system=ANSWER_SYSTEM_PROMPT, user=user,
            fallback=self.fallback_draft(facts).model_dump_json(), budget=budget,
        )
        if result.degraded and result.failure_kind is not LlmFailureKind.BAD_PAYLOAD:
            return DraftAttempt(
                draft=None, raw_text=result.text,
                failure_kind=AttemptFailureKind.UPSTREAM,
            )
        if not result.text:
            # HTTP 成功但正文为空属于模型输出不合格，可回喂重试，不是假装成服务宕机。
            return DraftAttempt(draft=None, raw_text="", failure_kind=None)
        try:
            return DraftAttempt(
                draft=AnswerDraft.model_validate_json(extract_json_object(result.text)),
                raw_text=result.text, failure_kind=None,
            )
        except ValidationError:
            return DraftAttempt(draft=None, raw_text=result.text, failure_kind=None)

    def validate_issues(self, draft, facts) -> list[str]: return self._validate(draft, facts)
    def fallback_draft(self, facts) -> AnswerDraft: return self._fallback(facts)
```

`failure_kind` 是区分三类 `draft is None` 的关键：上游真失败立即可见降级；预算失败归 `BUDGET`；HTTP 成功后的空正文、解析失败或 Schema 失败归输出校验问题并继续重试。DeepSeek Adapter 不得把成功响应里的空 `content` 伪装成 HTTP 故障；它要保留实际 usage，并让服务层看到空正文。

- [ ] **Step 4: 实现 `QualityLoop`**

```python
class QualityLoop:
    """生成 → 本地校验 → 独立复核 → 回喂失败原因 → 重试，用尽后确定性兜底。

    与参考实现 `PromptLoopAnalysisService.analyze()` 同结构，并修正第 1 稿的两处
    缺陷：解析失败并入 issues 参与重试；缺少 Reviewer 时返回可见的 DEGRADED 摘要。
    """

    def __init__(self, *, max_attempts: int, answer_service=None, review_service=None) -> None:
        self._max_attempts = max_attempts
        self._answers = answer_service or AnswerService()
        self._reviews = review_service or ReviewService()

    async def run(self, facts, answer_llm, reviewer_llm, budget) -> QualityOutcome:
        fallback = self._answers.fallback_draft(facts)
        notes: list[str] = []
        issues: list[str] = []
        previous = ""
        for attempt in range(1, self._max_attempts + 1):
            reviewed = ReviewAttempt(
                verdict=None, raw_text="", issues=(), failure_kind=None
            )
            try:
                drafted = await self._answers.compose_once(
                    facts, answer_llm, budget, previous=previous, issues=issues
                )
            except LlmDailyBudgetExceededError:
                notes.append("今日模型用量已达上限，本次只提供受控数据摘要")
                return _fallback_outcome(fallback, attempt - 1, notes, DegradeReason.BUDGET)
            except LlmBudgetExceededError:
                notes.append("本次请求的模型预算已达上限，本次只提供受控数据摘要")
                return _fallback_outcome(fallback, attempt - 1, notes, DegradeReason.BUDGET)
            except LlmUnavailableError:
                notes.append("模型暂不可用，本次只提供受控数据摘要")
                return _fallback_outcome(fallback, attempt - 1, notes, DegradeReason.UPSTREAM)

            if drafted.failure_kind is AttemptFailureKind.BUDGET:
                notes.append("本次请求的模型预算已达上限，本次只提供受控数据摘要")
                return _fallback_outcome(fallback, attempt, notes, DegradeReason.BUDGET)
            if drafted.failure_kind is AttemptFailureKind.UPSTREAM:
                notes.append("模型未返回内容，本次只提供受控数据摘要")
                return _fallback_outcome(fallback, attempt, notes, DegradeReason.UPSTREAM)

            previous = drafted.raw_text
            if drafted.draft is None:
                # 参考实现的 validate(null) 分支：解析失败也是一条可回喂的校验错误。
                issues = [
                    "模型返回空正文，请重新只输出完整 JSON"
                    if not drafted.raw_text
                    else "上一版输出无法解析为约定的 JSON 对象，请只输出完整 JSON"
                ]
            else:
                issues = self._answers.validate_issues(drafted.draft, facts)
                if not issues and reviewer_llm is None:
                    notes.append("未配置独立 Reviewer，本次只提供受控数据摘要")
                    return _fallback_outcome(fallback, attempt, notes, DegradeReason.UPSTREAM)
                if not issues:
                    reviewed = await self._reviews.review(
                        drafted.draft, self._answers.facts_json(facts), reviewer_llm, budget
                    )
                    if reviewed.failure_kind is AttemptFailureKind.BUDGET:
                        notes.append("复核模型预算已达上限，已显示受控数据摘要。")
                        return _fallback_outcome(
                            fallback, attempt, notes, DegradeReason.BUDGET
                        )
                    if reviewed.failure_kind is AttemptFailureKind.UPSTREAM:
                        notes.append("独立复核暂不可用，已显示受控数据摘要。")
                        return _fallback_outcome(fallback, attempt, notes, DegradeReason.UPSTREAM)
                    issues = list(reviewed.issues)

            if (
                not issues
                and drafted.draft is not None
                and reviewed.verdict is not None
                and reviewed.verdict.passed
            ):
                notes.append(f"第 {attempt} 轮通过本地校验和独立复核前后比对")
                return QualityOutcome(drafted.draft, QualityStatus.PASSED, attempt, notes, None)

            notes.append(f"第 {attempt} 轮回答被打回：{'；'.join(issues)}")

        notes.append("达到最大重试次数，使用确定性降级结果")
        return _fallback_outcome(fallback, self._max_attempts, notes, DegradeReason.VALIDATION)
```

伪代码中的 `reviewed` 在进入 Reviewer 分支前初始化为 `ReviewAttempt(verdict=None, raw_text="", issues=(), failure_kind=None)`，避免引用未赋值变量；只允许在 Reviewer 实际运行且 `verdict.passed=true` 时返回 `PASSED`。

`ReviewService` 必须把失败拆成三类：HTTP、超时、网络返回 `AttemptFailureKind.UPSTREAM`；单请求或每日预算返回 `AttemptFailureKind.BUDGET`；空正文、非法 JSON、字段不完整或自相矛盾的 verdict 返回 `failure_kind=None` 与可回喂 `issues`，进入下一轮。不得继续把所有 `ValueError` 都压成“Reviewer 暂不可用”。

`ReviewVerdict` 的一致性约束**不对称**，这是有意的：

- `passed=false` 且 `issues=[]` → `ValidationError`。打回却不说原因，回喂时没有内容可回喂，这一轮必然白跑，必须当成不合格输出。
- `passed=true` 且 `issues` 非空 → **归一化，不报错**。模型经常输出「通过，但建议补充同比」这类形态；把它判成不合格会在 `QUALITY_MAX_ATTEMPTS=2` 下吃掉唯一一次重试机会，把已经通过复核的回答推向降级。改为在 model validator 里把 `issues` 移入新字段 `advisory_notes: list[str] = []` 并清空 `issues`，由 `QualityLoop` 追加进 `notes`，对用户可见但不触发重试。

`QualityLoop` 判定通过时仍必须显式检查 `verdict.passed`，不得以 `issues` 是否为空代替 verdict——归一化之后 `issues` 恒为空，用它判断等于永远放行。

- [ ] **Step 5: 跑本任务全部定向测试，确认解析重试、Reviewer 一致性、预算分类与主路径全部通过**

- [ ] **Step 6: 先修改产品与精确契约，再放宽所有消费者约束**

按权威顺序执行：

1. `docs/PRD.md` 把最大能力改为 3 轮，并注明 Railway 初期配置为 2；
2. `docs/backend-development-plan.md` 全文更新 `quality_attempts` 0～3、状态语义与验收表：精确契约表及其“>2 拒绝”断言、B5 的固定轮次任务、重试后失败状态、Agent 流程图、Definition of Done 和环境变量示例中的 `MAX_REVIEW_ATTEMPTS` 必须一起改；用 `rg "quality_attempts|MAX_REVIEW_ATTEMPTS|FAILED"` 确认没有遗留旧语义；
3. `app/schemas/chat.py` 的 `ChatResponse`、历史消息两处改为 `le=3`；
4. 重新导出 `docs/api.md` / `docs/api.json`，重新生成 `frontend/src/api/generated.ts`；
5. `frontend/src/api/adapters/chat.ts` 的 `.max(2)`（`chat.ts:91`）改为 `.max(3)`，契约测试覆盖 3 接受、4 拒绝；
6. `.env.example` 删除旧 `MAX_REVIEW_ATTEMPTS`（`.env.example:22`，当前是 `config.py` 读不到的死变量），统一为 `QUALITY_MAX_ATTEMPTS`；
7. 清扫另外两处旧「最多两轮」语义：`docs/project-progress.md:46`（B5 那句「独立 Reviewer，最多两轮」）与 `docs/yshopping-parity-audit.md:200`（`loopAttempts` 对照行）。第 4 稿的 `rg` 清单漏了这两处。

新语义必须写清：`PASSED` 表示 Reviewer 实际执行并通过；`DEGRADED` 表示上游/预算/缺 Reviewer 或校验用尽后返回确定性摘要；`NOT_RUN` 只用于本来就不需要质量循环的回答且 attempts=0。`FAILED` 为向后兼容保留枚举，新质量循环不返回未经复核的失败候选；若决定删除该枚举，必须另开契约变更，不得在本任务顺手删除。

- [ ] **Step 7: 轮次改为可配置**

```python
    # 2026-08-18 审查建议：代码支持 3 轮，Railway 初期跑 2 轮，观察真实用量与延迟后再放开。
    quality_max_attempts: int = Field(default=3, ge=1, le=3)
```

Railway 变量设 `QUALITY_MAX_ATTEMPTS=2`。

同一步必须修改 `app/api/dependencies.py`：构造 `MerchantQaGraph` 时显式传入 `quality_max_attempts=settings.quality_max_attempts`，Graph 再用该值构造 `QualityLoop`。新增依赖装配测试，分别用 1/2/3 验证配置值到达循环；禁止 Graph 留下与 Settings 不同的第二套默认轮次。

- [ ] **Step 8: graph 两节点合并为调用 `QualityLoop`**

`_compose_answer` 保留「纯明细空正文」与非 METRIC/DETAIL 分支；METRIC/DETAIL 且已查到数据时调用 `QualityLoop.run()`。不得保留“节点名称还叫独立复核、实际工作却全在 compose 内完成”的虚假轨迹：把原 `local_validate` / `review_answer` / `decide_retry` 三个占位节点收敛为一个真实 `quality_loop` 轨迹节点，或由循环提供阶段事件。

**改节点名会连带打断前端 fixture 门禁，这一步必须一起做完：**

1. `app/agent/graph.py` 的 `GRAPH_NODES` 与 `_STEP_LABELS` 同步收敛，并删掉已无意义的 `MAX_REVIEW_ATTEMPTS` 常量（`graph.py:66`）；
2. 后端 SSE / 思考步骤测试同步；
3. **重新生成前端 fixture**：`frontend/src/api/mock/fixtures.generated.ts` 有 7 处写死了 `local_validate` / `review_answer` / `decide_retry`，由 `backend/scripts/export_chat_fixtures.py` 产出、`npm run fixtures` 同步、`npm run fixtures:check` 把守。不重新生成并提交，前端门禁必然红。
4. 同时更新 `app/agent/graph.py` 里 `quality_attempts=state["attempt"] if outcome.succeeded else 0` 一带的响应装配（`graph.py` 的 `_response` / `_response_quality`），让它读 `QualityOutcome.attempts` 而不是旧的 `state["attempt"]` 约定。

- [ ] **Step 9: 全量门禁（前后端都要跑）+ 检查 diff**

后端：

Run: `uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app && uv run pytest -q`

前端（本任务改了 `generated.ts`、`adapters/chat.ts` 与 fixture，只跑后端门禁挡不住漂移）：

Run: `cd ../frontend && npm run codegen:check && npm run fixtures:check && npm run lint && npm run typecheck && npm run test`

最后 `git diff`。

Expected: 既有断言 `quality_attempts` 的用例需按新语义更新；更新时必须写清新语义，不得只改数字。前端三条 check 全绿才算这一步完成。

### Task B3: 数字守卫升级为事实校验

> **执行优先级：** B3 必须在 B2 与 B5 之前完成并通过测试；它产出的 issues 与 `FactSummary` 是两者的输入接口。

**Files:**
- Modify: `backend/app/services/answer_service.py`
- Test: `backend/tests/unit/services/test_answer_service.py`

**设计（本稿建议 D1，待用户明确确认）：** 后端先计算可信摘要（合计、最新值、峰值、变化率），把它们**放进事实包**交给模型，模型只能引用这些数；守卫的允许集 = 行内数值 ∪ `total_rows` ∪ 事实包日期成分 ∪ **派生摘要**。

**与兜底文案天然合流：** Task B5 的兜底本来就要算合计/最新/峰值，同一份 `_derive_summary()` 既喂模型、也进允许集、也生成兜底正文，只算一次。

**一处必须说清的限制：** 派生摘要**不能单独解决空档日期**——模型说「8/14 至 8/16 无记录」时，14 与 16 不在任何集合里。因此 `_ISO_DATE` / `_CN_DATE` / `_SLASH_DATE` / `_DURATION` 的日期与时长剥除**继续保留**，不做删减。派生摘要解决的是「模型算出的合计和变化率被当成编造」，两者互补而非替代。

- [ ] **Step 1: 写失败测试**

```python
def test_derived_summary_numbers_are_citable() -> None:
    """模型说「合计 18 件，较首期增长 400%」不是幻觉——这些是后端算给它的事实。

    修复前这类派生数字一律被判越界，逼得模型只能复述原始行，分析价值大打折扣。
    """

    from app.schemas.chat import Recommendation
    from app.services.answer_service import AnswerDraft, AnswerService

    draft = AnswerDraft(
        answer="合计 18 件，峰值 15 件出现在最新一天，较首期增长 400.0%。",
        recommendations=[
            Recommendation(title="a", evidence="峰值 15 件。", action="x"),
            Recommendation(title="b", evidence="合计 18 件。", action="y"),
        ],
    )

    assert AnswerService()._validate(draft, _trend_facts()) == []


def test_numbers_outside_rows_and_summary_are_still_rejected() -> None:
    """守卫本职不能丢：既不在行里、也不在派生摘要里的数字仍要拦下。"""

    from app.schemas.chat import Recommendation
    from app.services.answer_service import AnswerDraft, AnswerService

    draft = AnswerDraft(
        answer="退货量为 98765 件。",
        recommendations=[
            Recommendation(title="a", evidence="e1", action="x"),
            Recommendation(title="b", evidence="e2", action="y"),
        ],
    )
    issues = AnswerService()._validate(draft, _trend_facts())

    assert any("98765" in issue for issue in issues)


@pytest.mark.parametrize("field", ["title", "evidence", "action"])
def test_recommendation_fields_cannot_smuggle_numbers_outside_facts(field: str) -> None:
    recommendation = {
        "title": "建议",
        "evidence": "峰值 15 件。",
        "action": "继续观察。",
    }
    recommendation[field] = "建议按 98765 件执行"
    draft = AnswerDraft(
        answer="合计 18 件。",
        recommendations=[Recommendation(**recommendation), _valid_recommendation()],
    )

    issues = AnswerService()._validate(draft, _trend_facts())

    assert any("98765" in issue for issue in issues)


def test_equivalent_decimal_display_forms_are_citable() -> None:
    """事实 15.00 不应把模型常用的“15”误判为编造。"""

    assert "15" in _numeric_forms(Decimal("15.00"))
    assert "15.0" in _numeric_forms(Decimal("15.00"))
    assert "15.00" in _numeric_forms(Decimal("15.00"))


def test_truncated_rows_do_not_produce_total_or_change_pct() -> None:
    summary = AnswerService()._derive_summary(_trend_facts(truncated=True))

    assert summary.total is None
    assert summary.change_pct is None


def test_latest_is_selected_by_date_not_input_order() -> None:
    summary = AnswerService()._derive_summary(_trend_facts(descending=True))

    assert summary.latest_label == "2026-08-18"
    assert summary.latest_value == Decimal("15")


def test_non_temporal_grouping_has_no_latest_or_change() -> None:
    summary = AnswerService()._derive_summary(_category_facts())

    assert summary.latest_label is None
    assert summary.change_pct is None


def test_uuid_leak_becomes_an_issue_instead_of_raising() -> None:
    """现状三处 raise 之一。改成 issues 时不能只搬数字那一条。"""

    draft = _draft_with_answer("订单 3f6c1b2a-0000-4000-8000-000000000001 已完成。")

    issues = AnswerService()._validate(draft, _trend_facts())

    assert any("标识符" in issue for issue in issues)


def test_additive_claim_on_a_non_additive_metric_becomes_an_issue() -> None:
    """现状 `_ADDITIVE_CLAIM_PHRASES` 那条 raise，第 4 稿的测试清单漏了它。

    这条是可回喂的最佳例子：告诉模型「这个指标不能跨日合计」，它下一轮就能改对。
    """

    draft = _draft_with_answer("最近 7 天的平均客单价合计为 328。")

    issues = AnswerService()._validate(draft, _non_additive_facts(rows=3))

    assert any("非加和" in issue for issue in issues)
```

- [ ] **Step 2: 跑测试确认失败**（第一条因 18 / 400.0 越界而失败）

- [ ] **Step 3: 实现 `_derive_summary()` 并接入事实包、允许集、`_validate`**

```python
@dataclass(frozen=True)
class FactSummary:
    """后端算出的可信摘要。模型只能引用这里的数，不得自行计算。"""

    total: Decimal | None          # 非加和指标为 None
    latest_label: str | None
    latest_value: Decimal | None
    peak_label: str | None
    peak_value: Decimal | None
    change_pct: Decimal | None     # 末期较首期变化率，首期为 0 时为 None
```

`_validate` 的允许集加入摘要中每个非空数值的等价显示形态。新增 `_numeric_forms(value: Decimal | int | float) -> set[str]`，至少覆盖原始字符串、去无意义尾零形式、整数形式和一位小数形式；百分比按后端固定量化为一位小数。比较的是数值等价形态，不能让数据库里的 `15.00` 把回答里的 `15` 误判成幻觉。`_facts_json` 增加 `"summary"` 节，并在 `ANSWER_SYSTEM_PROMPT` 补一句：**「合计、峰值、变化率只能引用事实包 summary 中的值，不得自行计算」**。

`_derive_summary()` 只有在 `truncated=false`、结果中恰好有一个指标字段且存在可解析的日期维度时，才计算合计、最新、峰值与首末变化率；按解析后的业务日期排序，不能依赖查询返回顺序。全部计算使用 `Decimal`。非时间分组不得生成“最新/变化率”，截断结果不得把预览行冒充全量合计；非加和指标即使满足其他条件也不得跨日求和。

数字与 UUID 校验文本必须包含：`draft.answer`，以及每条建议的 `title`、`evidence`、`action`。四处使用同一拼接函数，禁止只检查 evidence。日期/时长剥除仍只应用于拼接后的展示文本，不能改变事实包本身。

- [ ] **Step 4: `_validate` 改为返回 issues 列表（供 Task B2 回喂）**

现状 `answer_service.py:141-160` 有**三处** `raise ValueError`，三处都要改成 append 到同一个 issues 列表，且一次调用要把三类问题一起报全（不再遇到第一个就中断）——回喂的价值正在于一次说清所有问题：

```python
        issues: list[str] = []
        if _UUID.search(raw_text):
            issues.append("回答含有内部标识符，不得出现在对商家的回答里")
        if result.non_additive and len(result.rows) > 1 and any(
            phrase in raw_text for phrase in _ADDITIVE_CLAIM_PHRASES
        ):
            issues.append("这是非加和指标，不能跨日合计或汇总，请逐行陈述")
        unexpected = sorted({n for n in _NUMBER.findall(text) if n not in allowed_numbers})
        if unexpected:
            issues.append("以下数字不在查询结果或事实摘要里，不得出现在回答中：" + "、".join(unexpected))
        return issues
```

调用方随之改动：`answer_service.compose()` 原来靠 `except ValueError` 接住校验失败，改成检查返回值；B2 的 `validate_issues()` 直接透传本函数结果。用 `rg "_validate\("` 确认没有遗漏的调用点仍在指望它抛异常。

- [ ] **Step 5: 确认通过 → Step 6: 全量门禁 → Step 7: 检查 diff**

### Task B4: 按 A 段实测重新标定预算

**依赖 Task A4 的实测数字。不得在 A4 完成前拍脑袋填。**

**本稿建议的 Railway 初期默认值（待用户明确确认）：**

| 变量 | 取值 |
| --- | --- |
| `LLM_MODEL` | `deepseek-v4-flash` |
| `QUALITY_MAX_ATTEMPTS` | **2**（代码支持 3） |
| `MAX_LLM_CALLS_PER_REQUEST` | **10**（第 4 稿写 8，算漏了 understand 的重试，见下） |
| `MAX_LLM_TOKENS_PER_REQUEST` | **25000** |
| `LLM_DAILY_BUDGET_TOKENS` | **500000**（维持不变） |

**第 4 稿把这里算错了，必须按真实调用图重算。** 原文写「classify + understand + catalog + (compose + review) × 2 = 7 次，确认 ≤ 8」，把 understand 当成 1 次调用。实际上：

- `app/intent/service.py:27` `MAX_INTENT_RETRIES = 2`，`:99` `for attempt in range(MAX_INTENT_RETRIES + 1)` —— understand 最坏 **3 次**；
- `app/api/dependencies.py:143-166` 把同一个 `LlmCostGuard` 同时传给 `intent_service_llm`、`catalog`、`answer_llm`、`reviewer_llm`，四者**共用一个 `LlmBudget`**，次数是全局累加的。

最坏路径：

```text
classify              1
understand            3   ← 第 4 稿按 1 算
指标口径 catalog       1
(compose + review)×2   4
                    ----
                       9
```

定 8 的后果不是「省钱」，而是：understand 一旦重试两次，质量循环第二轮就会撞上 `LlmBudgetExceededError`，被 B2 归类成 `BUDGET` 降级——一个本来能答的问题对外显示「今日模型用量已达上限」，且 `quality_notes` 会把排查方向指向预算而不是意图识别。因此初期定 **10**（9 次最坏 + 1 次余量）。

- [ ] **Step 1: 用 A4 的实测值按上面的调用图逐段核算**，逐段列出「期望次数 / 最坏次数」，确认最坏 ≤ `MAX_LLM_CALLS_PER_REQUEST`。**禁止再按「understand = 1 次」估算。**
- [ ] **Step 2: token 上限同样按最坏路径核算**（9 次调用而不是 7 次）。若实测超出 25000，先回头压提示词长度，不要直接调大上限。
- [ ] **Step 3: 记录一条待观察项**：`MAX_INTENT_RETRIES=2` 与 `QUALITY_MAX_ATTEMPTS` 是两套独立重试，叠加后最坏调用数是乘加关系。本计划不改前者，但要在 `docs/project-progress.md` 的「风险与约束」里写明这条耦合，供后续调参时一并考虑。
- [ ] **Step 4: 同步 `config.py` 默认值、`.env.example`、`docs/deployment.md` 变量表。** 注意 `MAX_LLM_CALLS_PER_REQUEST` / `MAX_LLM_TOKENS_PER_REQUEST` 是 `config.py:56-67` 上 `AliasChoices` 声明的别名，字段名是 `llm_max_calls_per_request` / `llm_max_tokens_per_request`，两个名字都要能读到。
- [ ] **Step 5: 全量门禁 + 检查 diff**

### Task B5: 兜底文案对齐参考项目

**Files:**
- Modify: `backend/app/services/answer_service.py`（`_fallback`）
- Test: `backend/tests/unit/services/test_answer_service.py`

复用 Task B3 的 `_derive_summary()`。

- [ ] **Step 1: 写失败测试**

```python
def test_fallback_reports_total_latest_and_peak_for_additive_metric() -> None:
    """参考实现 fallback() 给的是「合计 + 最新日期 + 峰值日期」；我方只报首行。"""

    draft = AnswerService().fallback_draft(_trend_facts())

    assert "合计" in draft.answer and "18" in draft.answer
    assert "峰值" in draft.answer and "15" in draft.answer


def test_fallback_refuses_to_total_a_non_additive_metric() -> None:
    draft = AnswerService().fallback_draft(_non_additive_facts())

    assert "不做跨日合计" in draft.answer
    assert "合计为" not in draft.answer


def test_fallback_marks_truncated_rows_as_preview_without_total() -> None:
    draft = AnswerService().fallback_draft(_trend_facts(truncated=True))

    assert "仅展示部分结果" in draft.answer
    assert "合计为" not in draft.answer


def test_fallback_uses_business_date_for_latest_even_when_rows_descend() -> None:
    draft = AnswerService().fallback_draft(_trend_facts(descending=True))

    assert "2026-08-18" in draft.answer
    assert "最新" in draft.answer


def test_fallback_does_not_call_category_grouping_latest() -> None:
    draft = AnswerService().fallback_draft(_category_facts())

    assert "最新" not in draft.answer
```

- [ ] **Step 2: 确认失败 → Step 3: 按“完整时间序列 / 非加和 / 截断预览 / 非时间分组”四套措辞重写指标分支**。复用 B3 的 `Decimal` 摘要和日期排序；没有可靠摘要时只描述已展示行，不推导全量合计、最新或变化率。
- [ ] **Step 4: 确认通过 → Step 5: 全量门禁 → Step 6: 检查 diff**

### Task B6: 降级原因据实分类

**Files:** Modify `backend/app/agent/graph.py`；Test `backend/tests/unit/agent/test_graph.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_local_validation_failure_is_not_reported_as_service_outage() -> None:
    """2026-08-18 线上实测：DeepSeek 正常返回也计了费，真实原因是我方守卫拒绝，
    界面却报「回答生成服务暂不可用」，把排查方向带偏了一整轮。
    """

    llm = FakeLlmClient(responses=[_draft_json(answer="退货量为 98765 件。")] * 3)
    result = await _run_metric_graph(llm)

    assert result.degraded_reason == "回答未通过质量校验，已返回受控数据摘要。"
```

- [ ] **Step 2: 确认失败 → Step 3: 按 `reason` 分派文案**

```python
_DEGRADE_REASON_TEXT: Final[dict[DegradeReason, str]] = {
    DegradeReason.UPSTREAM: "回答生成服务暂不可用，已返回受控数据摘要。",
    DegradeReason.VALIDATION: "回答未通过质量校验，已返回受控数据摘要。",
    DegradeReason.BUDGET: "今日模型用量已达上限，已返回受控数据摘要。",
}
```

- [ ] **Step 4: 确认通过 → Step 5: 全量门禁 → Step 6: 检查 diff**

### Task B7: B 段真实模型验收（**执行前按 R3 单独取得同意**）

- [ ] **Step 1: 说明费用并取得同意** —— 共 9 条问题：METRIC×6（趋势、分类、同比/环比、空结果、截断风险、非加和各 1 条）+ DETAIL×1 + RULE×1 + CHAT×1。执行前依据调用图逐类列出期望模型请求次数；单题受 `MAX_LLM_CALLS_PER_REQUEST=10`（B4 重算后的取值）约束，因此整个验收的理论硬上限为 **90 次模型请求**，实际目标（按最坏 9 次、常见 5～6 次估）应显著低于该值。模型 `deepseek-v4-flash`，预计 4~5 万 token，**会真实计费**。用户确认的调用次数与 token 上限必须写入验收记录，任一上限将被触及时立即停止，不得自动追加样例或重跑。
- [ ] **Step 2: 逐条记录** `degraded`、`quality_status`、`quality_attempts`、`quality_notes`、`data_rows`、图表与建议条数、端到端耗时。
- [ ] **Step 3: 出口判据** —— 上述 6 条 METRIC 全部 `degraded=false`（对照 2026-08-18 修复前 4 次采样 2 次失败的基线）；任何降级都能从 `quality_notes` 读出被打回的具体原因；`NOT_RUN` 与 `PASSED` 不得混淆。
- [ ] **Step 4: 结果写进 `docs/project-progress.md`。**

---

## §6 C 段 —— 演示数据增量滚动

### Task C1: 让单日数据与查询窗口解耦

**Files:**
- Modify: `backend/app/analytics/demo_data.py`
- Test: `backend/tests/unit/analytics/test_demo_data.py`

**背景（第 1 稿缺陷 4）：** 现在 `rng = random.Random(seed)`、`start_date = end_date - (days-1)`，所有行按顺序从同一个 rng 取值。换一个 `end_date` 重跑，**每一天的数据和主键 UUID 全部改变**，已落库 `answers` 引用的数字会对不上。

**修法：** 把数据拆成“稳定商品目录”和“按业务日确定的事实分区”。商品表受 `UNIQUE(merchant_id, product_code)` 约束且被订单明细外键引用，不能每天生成一套商品；订单、明细、退款、退货、工单等事实数据才按「商家 + 业务日」派生。同一业务日无论何时生成、窗口多长，结果完全一致。

- [ ] **Step 1: 写失败测试**

```python
def test_a_business_day_is_identical_regardless_of_the_window_it_was_generated_in() -> None:
    """演示数据每天滚动，但历史必须钉死。

    否则今天回答里的「8月17日退货 15 件」明天会变成别的数字，已落库的 answers 和
    会话历史全部对不上——这是第 1 稿「每日全量重建」方案的致命缺陷。
    """

    target = date(2026, 8, 17)
    wide = build_demo_dataset(merchant_id=MERCHANT, end_date=date(2026, 8, 18), days=180, seed=1)
    narrow = build_demo_dataset(merchant_id=MERCHANT, end_date=target, days=7, seed=1)

    def facts_on(dataset, day):
        return snapshot_fact_partition(dataset, day)

    assert facts_on(wide, target) == facts_on(narrow, target)
    assert wide.products == narrow.products
    assert len({(p["merchant_id"], p["product_code"]) for p in wide.products}) == len(wide.products)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/analytics/test_demo_data.py -k identical -v`
Expected: FAIL —— 两个窗口生成的同日数据完全不同

- [ ] **Step 3: 拆分稳定目录与按日事实分区**

```python
def _day_rng(merchant_id: UUID, business_day: date, seed: int) -> random.Random:
    """同一商家同一业务日永远得到同一条随机序列。

    种子只由「商家 + 业务日 + 全局 seed」决定，与生成窗口无关——这样每日增量滚动
    才不会改写历史，已落库的回答与会话依据才能长期成立。
    """

    return random.Random(f"{seed}:{merchant_id}:{business_day.isoformat()}")
```

新增两个明确入口：

```python
def build_demo_catalog(merchant_id: UUID, seed: int) -> list[dict[str, object]]:
    """生成稳定商品目录；product id、product_code 和静态属性不随日期变化。"""


def build_demo_partition(
    merchant_id: UUID,
    business_day: date,
    catalog: Sequence[Mapping[str, object]],
    seed: int,
) -> DemoFactPartition:
    """生成一个业务日的订单、明细、退款、退货和工单事实。"""
```

`build_demo_catalog()` 使用固定 `DEMO_CATALOG_EPOCH = date(2026, 1, 1)` 派生上架日，不得再依赖窗口起点。`build_demo_dataset()` 只生成一次 catalog，再组合目标窗口内的事实分区。订单和明细只归属下单日；退款、退货和工单如果允许延迟发生，则用确定性的来源订单 ID 建立外键，并按事件自己的 `business_date` 归入目标分区。实现时按最大延迟天数回看来源日，不能因为只生成当天订单而制造悬空外键。

所有 UUID、`order_no`、`ticket_no` 和事件抽样都必须由“商家 + 来源业务日 + 当日序号 + 事件类型 + 全局 seed”稳定派生；`ticket_no` 不得继续使用整个窗口的 `len(tickets)`。延期日直接计算，**不得**再用 `min(event_day, end_date)` 把未来事件挤到窗口末日；未来事件等实际业务日到达后再由对应分区生成。

滚动脚本兼容既有数据库时，商品以 `(merchant_id, product_code)` 执行 `ON CONFLICT DO NOTHING`，保留数据库里已有 Product 主键、上架日、价格和类目，再加载真实持久化目录并把 `product_code → persisted product_id` 映射传给事实生成器；不能更新会改变历史分类口径的属性，也不能替换被外键引用的 Product ID。新旧生成器交界后的最大延迟期内，延迟事件优先从已落库、符合条件的来源订单中按稳定排序选择；找不到来源则确定性跳过该事件，不得生成指向“新算法推算但数据库不存在”的订单 ID。

- [ ] **Step 4: 确认通过 → Step 5: 全量门禁 → Step 6: 检查 diff**

**兼容策略：** 不对已经上线的历史窗口做全量重灌。现有历史保持不动，新生成器从每个演示商家“当前最大业务日的下一天”开始接管；若确实要整体重置演示环境，必须另列一次性维护步骤、先备份并单独取得用户批准，不把它混进每日 Cron。

### Task C2: 增量滚动 Seed 脚本

**Files:**
- Create: `backend/app/jobs/__init__.py`、`backend/app/jobs/seed_demo_rolling.py`、`backend/tests/unit/jobs/test_seed_demo_rolling.py`、`backend/tests/integration/test_seed_demo_rolling.py`
- Create: `backend/app/core/seed_config.py`、`backend/tests/unit/core/test_seed_config.py`
- Modify: `backend/app/db/session.py`、`backend/tests/unit/db/test_session.py`
- Modify: `backend/scripts/seed_demo_analytics.py`（加与 Cron 互斥的全量重灌护栏，见 Step 5）
- Modify: `.env.example`（新增 `ALLOW_DEMO_DATA_REFRESH=false`）、`AGENTS.md`（登记非密钥的演示数据写权限变量）

- [ ] **Step 1: 写失败测试（真实 PostgreSQL）**

```python
@pytest.mark.asyncio
async def test_rolling_seed_appends_today_and_prunes_beyond_the_window(session) -> None:
    """补齐截至当天的全部漏跑日、清理 180 天以前，中间历史一行都不动。"""

    before = await _rows_by_date(session)
    await roll_forward(
        session, settings=demo_refresh_settings,
        business_day=date(2026, 8, 19), window_days=180,
    )
    after = await _rows_by_date(session)

    assert date(2026, 8, 19) in after
    assert date(2026, 2, 19) not in after            # 滑出窗口被清理
    for day in set(before) & set(after) - {date(2026, 8, 19)}:
        assert before[day] == after[day], f"{day} 的历史数据被改写了"


@pytest.mark.asyncio
async def test_rolling_seed_is_idempotent_for_the_same_day(session) -> None:
    """同一天重复执行不得产生重复行——Cron 可能因重试跑两次。"""

    await roll_forward(
        session, settings=demo_refresh_settings,
        business_day=date(2026, 8, 19), window_days=180,
    )
    snapshot = await _rows_by_date(session)
    await roll_forward(
        session, settings=demo_refresh_settings,
        business_day=date(2026, 8, 19), window_days=180,
    )

    assert await _rows_by_date(session) == snapshot


@pytest.mark.asyncio
async def test_rolling_seed_catches_up_every_missing_day(session) -> None:
    await _seed_through(session, date(2026, 8, 16))

    await roll_forward(
        session, settings=demo_refresh_settings,
        business_day=date(2026, 8, 19), window_days=180,
    )

    assert await _business_days(session) >= {
        date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)
    }


@pytest.mark.asyncio
async def test_rolling_seed_rejects_a_database_with_non_demo_merchants(session) -> None:
    await _insert_real_merchant(session)

    with pytest.raises(RuntimeError, match="仅允许写入专用演示数据库"):
        await roll_forward(
            session, settings=demo_refresh_settings,
            business_day=date(2026, 8, 19), window_days=180,
        )


@pytest.mark.asyncio
async def test_first_partition_after_legacy_handoff_has_no_dangling_foreign_keys(session) -> None:
    await _seed_legacy_history_through(session, date(2026, 8, 18))

    await roll_forward(
        session, settings=demo_refresh_settings,
        business_day=date(2026, 8, 19), window_days=180,
    )

    assert await _dangling_fact_foreign_key_count(session) == 0
```

- [ ] **Step 2: 跑测试确认失败**（模块不存在）

- [ ] **Step 3: 实现 `roll_forward`**

要求逐条落实：

1. **专用配置模型**：Railway 只需给 `SeedSettings` 提供 `DATABASE_URL`、`APP_ENV`、`ALLOW_DEMO_DATA_REFRESH`、`BUSINESS_TIMEZONE`。模型内部给 `db_statement_timeout_ms=5000`、`db_connect_max_attempts=5`、`db_connect_retry_seconds=1.0` 安全默认值，不得实例化 Web 应用的完整 `Settings`，避免 Cron 被 `FRONTEND_ORIGIN`、`EXPORT_SIGNING_SECRET` 等无关必填项卡住。`db/session.py` 把 `Database` 的构造参数类型由具体 `Settings` 收窄为包含上述四个数据库字段的 `Protocol`，并补 mypy/单元测试，保证 Web `Settings` 与 `SeedSettings` 都可安全复用同一连接生命周期。
2. **写入前双重护栏**：必须显式设置 `ALLOW_DEMO_DATA_REFRESH=true`；随后用 `default_merchants()` 的 3 个固定 UUID 作为唯一允许集合，在任何 DELETE/INSERT 前校验数据库里的商家 UUID 集合与之**完全相等**，多一个、少一个都拒绝。不能只比名称或数量。`DEMO_DEPLOYMENT_MODE` 只控制演示端点开放，不承担破坏性数据写权限。
3. **单事务**：校验、追加与清理在同一事务内完成，失败整体回滚。
4. **数据库锁防并发**：入口取 `pg_advisory_xact_lock(2026081801)`，两个 Cron 实例同时触发时第二个等待而不是交叉写入；该常量写入脚本并在测试中复用，不从用户输入派生。
5. **补齐所有漏跑日期**：按商家读取最大业务日，逐日生成从 `max_date + 1` 至 `business_day` 的闭区间；不得只补当天。若最大业务日已达到当天则直接 no-op，不先删后插。
6. **目录稳定、兼容新旧边界、事实有序写入**：商品目录按业务键 `ON CONFLICT DO NOTHING`，保留已有 Product 主键及历史属性，不按日重建也不做窗口清理；按 `product_code` 排序加载持久化目录后再生成订单项，不能依赖数据库无序返回。第一批新分区的延迟事件只能引用数据库里真实存在的来源订单；事实表按父表到子表顺序插入，商家也按固定 UUID 排序处理。

   **随机基线必须沿用既有写入路径的取值，不能另起一个。** 真正把演示经营数据写进库的是 `backend/scripts/seed_demo_analytics.py:61,84`，它用的是**每商家 `20260804 + index`**；`scripts/seed_demo_data.py` 里的 `--random-seed 20260730` 只 seed 商家表，根本不调 `build_demo_dataset()`。第 4 稿写的 `DEMO_RANDOM_SEED = 20260730` 是拿错了常量——用它接管会让新旧两段历史落在两条完全不同的随机序列上，分布出现肉眼可见的断层，也让 C1「同一业务日与窗口无关」的验收跨不过交界。固定为：

   ```python
   #: 与 backend/scripts/seed_demo_analytics.py 既有取值一致，第 i 个演示商家用 BASE + i。
   DEMO_ANALYTICS_SEED_BASE: Final[int] = 20260804
   ```

   并在 C1/C2 的测试里各留一条断言，钉住「滚动生成器与既有脚本对同一商家使用同一 seed」。不能由 Cron 每次启动随机生成。
7. **外键安全清理**：窗口外数据按子表到父表删除。若窗口内退款/退货仍引用窗口外订单或明细，则保留相应父行，直到引用事件也滑出窗口；不得删除仍被引用的 Product。
8. **历史不可变**：集成测试对滚动前后的历史分区做行内容 checksum；绝不触碰 `conversations` / `messages` / `answers` / `feedback`。
9. **连接回收**：脚本入口在 `finally` 中调用 `await database.dispose()`（`app/db/session.py:69` 的既有方法；不存在 `dispose_database()` 这个自由函数，第 4 稿写错了名字），成功、失败都不得把连接挂到进程结束。

`SeedSettings` 必须令 `allow_demo_data_refresh: bool = False`，环境变量别名固定为 `ALLOW_DEMO_DATA_REFRESH`；未设置、空字符串、拼写错误都按 false 处理。`.env.example` 只能给 false，不得为了方便把破坏性写权限默认打开。`AGENTS.md` R6 在密钥清单后单独注明它是“非密钥但高风险的显式写权限”，避免被误解为可以写进前端或构建产物。

脚本计算目标业务日必须显式按业务时区换算，不能用容器默认 UTC 的 `date.today()`。**直接复用既有的 `app.analytics.dates.business_today(now, timezone=...)`**（`backend/scripts/seed_demo_analytics.py:37-45` 已经在用它，并在注释里写清了为什么），不要在 jobs 里另写一份 `ZoneInfo` 逻辑——两份实现迟早会漂移。单元测试固定 `2026-08-18T16:10:00Z`，断言 Asia/Shanghai 的目标业务日为 `2026-08-19`；否则 00:10 的 Cron 会永远只补到“昨天”。

- [ ] **Step 4: 确认通过（需真实 PostgreSQL，`REQUIRE_INTEGRATION_DB=1`）**

- [ ] **Step 5: 给旧的全量重灌脚本加与 Cron 互斥的护栏**

`backend/scripts/seed_demo_analytics.py` 是现在唯一真正写演示经营数据的入口，它的 `_seed()` 会先 `delete()` 六张经营表该商家的**全部**行再整批重写。滚动 Cron 上线后，任何人手滑跑一次它，就会把 Cron 累积出来的历史连同已落库 `answers` 的数据依据一起抹掉——这正是 C1「历史必须钉死」要防的事，只是换了个触发源。本步骤必须：

1. 在该脚本的写入路径前加一道显式确认参数（例如 `--force-full-rebuild`），缺参数时打印「演示数据现在由 app.jobs.seed_demo_rolling 每日滚动维护；全量重灌会抹掉历史，需显式确认」并以非零码退出；
2. 保留它现有的 `reject_production()` 生产护栏，不因为新增参数而放宽；
3. 补一条单元测试：不带确认参数时不执行任何 DELETE。

不删除这个脚本——「整体重置演示环境」仍然需要它，只是从默认可跑改成需要明确意图。

- [ ] **Step 6: 验证可执行模块随镜像发布**

入口放在 `backend/app/jobs/`，因此现有 Dockerfile 的 `COPY app ./app` 已经覆盖，无需额外复制仓库根或 `scripts/`。模块 import 不得读取配置或连接数据库，只有 `main()` 才执行；本地先验证：

Run: `uv run python -m app.jobs.seed_demo_rolling --help`

Expected: exit 0，显示用途、业务时区、窗口天数等参数说明，不连接 PostgreSQL。

- [ ] **Step 7: 全量门禁 + 检查 diff**

### Task C3: 独立 Cron Service

**Files:**
- Create: `backend/railway.cron.json`
- Modify: `docs/deployment.md`

**关键：不得复用 `backend/railway.json`。** 它带 `healthcheckPath: /api/health` 与 `preDeployCommand`；一次性任务不监听端口，健康检查必然失败。`preDeployCommand` 会在该 Service 每次部署时执行，并非每次计划任务执行；Cron Service 不需要重复承担 Web Service 的迁移职责。

- [ ] **Step 0: 取得 Railway 正式变更授权（硬门）**

向用户明确说明将创建一个新的 Railway Cron Service、让它连接现有演示 Neon PostgreSQL、每天执行增量写入，并列出将设置的四个变量。只有用户对这次**正式部署动作**明确同意后，才能继续 Step 1～5。D3 的方案确认、代码合并许可或真实模型费用许可都不能替代本步骤；未获授权时 C1/C2 可在本地完成，C3 保持未执行。

- [ ] **Step 1: 新建 `backend/railway.cron.json`**

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": { "builder": "DOCKERFILE", "dockerfilePath": "Dockerfile" },
  "deploy": {
    "startCommand": "python -m app.jobs.seed_demo_rolling",
    "cronSchedule": "10 16 * * *",
    "restartPolicyType": "NEVER"
  }
}
```

无 `healthcheckPath`、无 `preDeployCommand`、失败不自动重启（避免坏数据被反复写入）。Start Command 与 Cron Schedule 写进该 Service 独占的配置文件，避免控制台值与仓库文档漂移。`$schema` 与现有 `backend/railway.json` 保持同一个域名（`railway.app`），不要一个文件用 `railway.app`、另一个用 `railway.com`。

- [ ] **Step 2: 在 Railway 新建 Cron Service**

Root Directory `/backend`；Config File Path **`/backend/railway.cron.json`**。部署详情必须显示 Start Command 与 Cron Schedule 均来自配置文件：`10 16 * * *`（UTC = Asia/Shanghai 每日 00:10）、`python -m app.jobs.seed_demo_rolling`。如果控制台残留了同名覆盖值，先清理并重新核对部署详情；不能接受“仓库写一套、控制台实际跑另一套”。这样相对日期查询在当天开始约 10 分钟后即可看到新分区，而不是等到 02:00。

Railway Cron 按 UTC 调度且不保证精确到秒；如果上一次执行仍在运行，下一次可能被跳过。因此 C2 的漏跑追赶是正确性要求，不只是容错优化。脚本必须在完成后退出，不能启动 Uvicorn 或常驻循环。

启用 Cron 前先确认同一环境的 Backend Web Service 已完成 Alembic 迁移并通过 `/api/ready`；Cron 自身不跑迁移，缺表或版本不符时必须失败退出，不能尝试自动修库。

- [ ] **Step 3: 变量最小化**

只给 `DATABASE_URL`、`APP_ENV=production`、`ALLOW_DEMO_DATA_REFRESH=true`、`BUSINESS_TIMEZONE=Asia/Shanghai`。**不给 `LLM_API_KEY`、不给 `ADMIN_TOKEN`、不给 `FRONTEND_ORIGIN`、不给 `EXPORT_SIGNING_SECRET`** —— `SeedSettings` 不读取这些变量，造数也不需要它们。

- [ ] **Step 4: Seed 的生产护栏改为显式开关**

```python
def require_demo_refresh_permission(settings: SeedSettings) -> None:
    """生产运行环境也必须显式授予演示数据刷新权限。"""

    if not settings.allow_demo_data_refresh:
        raise RuntimeError("未启用 ALLOW_DEMO_DATA_REFRESH，拒绝修改演示数据")
```

配套测试至少覆盖：未开开关时拒绝；开关开启但商家集合不精确匹配仍拒绝；只有显式开关与专用演示库校验同时通过才允许写入。

- [ ] **Step 5: 手工触发一次并验收**

Railway 执行记录显示任务正常退出；日志出现「补齐 D 天 / 已追加 N 行 / 清理 M 行」；每个演示商家的 `max(business_date)` 等于当天；随机抽一个历史日期，比对执行前后 checksum 完全一致；同日重跑日志为 no-op；故意漏跑两天后触发能一次补齐；日志与镜像中不出现任何未授权密钥。

- [ ] **Step 6: 写进 `docs/deployment.md` 新章节「演示数据的每日滚动」**，写清 `ALLOW_DEMO_DATA_REFRESH` 是独立写权限、Cron 只能连接专用演示数据库、商家集合精确校验、00:10 调度、漏跑追赶、历史不重灌与手工禁用/恢复步骤。真实商家数据库永远不得配置该 Cron Service。

### Task C4: 文档登记

**Files:** Modify `docs/yshopping-parity-audit.md`、`docs/project-progress.md`、`AGENTS.md`

- [ ] **Step 1: 在 §5「⚪ 有意偏离」新增三条**

1. **演示数据生成策略**：参考项目写死 3 天且无刷新（`seed_yshopping_doris_july.py:32-33`）；我方采用稳定商品目录、180 天事实窗口、漏跑追赶与每日增量。理由：参考做法会让所有相对时间问题从第一天起就查不到数据。
2. **数字守卫升级为事实校验**：参考项目本地校验无数字检查；我方保留守卫并由后端派生可信摘要供模型引用。理由：确定性拦截优于纯模型判断。
3. **结构化步骤关闭推理**：参考项目基于非推理模型，无此概念；我方对 classify / understand / 指标口径 / Reviewer 关闭 thinking，回答生成保留。理由见 §2 实测。

- [ ] **Step 2: 更新 `docs/project-progress.md`** 的「下一步」与「风险与约束」；在 `AGENTS.md` 后端目录索引登记新建的 `app/jobs/seed_demo_rolling.py` 与 `app/core/seed_config.py`，满足“规划路径首次创建后同步索引”的规则；同时在 R6 环境变量说明中登记 `ALLOW_DEMO_DATA_REFRESH` 为“默认 false、仅 Cron 使用、不得暴露给前端的高风险写权限”，并确认 `.env.example` 仍为 false。

- [ ] **Step 3: 登记两条演示数据的运维事实**

1. **两个写入入口的分工**：`app/jobs/seed_demo_rolling.py` 是每日增量、唯一常态入口；`backend/scripts/seed_demo_analytics.py` 是全量重灌，只用于一次性重置，已加 `--force-full-rebuild` 显式确认（C2 Step 5）。两者互斥，重灌前必须先停用或跳过一次 Cron。写进 `docs/deployment.md` 的「演示数据的每日滚动」章节。
2. **随机种子的唯一来源**：`DEMO_ANALYTICS_SEED_BASE = 20260804`，第 i 个演示商家用 `BASE + i`；`scripts/seed_demo_data.py` 的 `--random-seed 20260730` 只作用于商家表，与经营数据无关。这条写进 `docs/project-progress.md` 的关键入口，避免下一个人再拿错常量。

---

## §7 自检

**规格覆盖：** §1 五条参考事实分别由 B2（统一循环）、B3（本地校验形态，有意偏离并登记）、B1（宽松解析）、B5（兜底文案）、C1–C3（演示数据，有意偏离并登记）覆盖；§2 五条实测结论由 A3（关推理 + JSON Output）与 B4（预算标定）覆盖；§0 的审查结论逐条对应到任务。

**完整性扫描：** 未保留待补标记或“照某任务类推”的模糊指令。B2 Step 8、B5 Step 3、C1 Step 3 给的是精确局部改法而非整段复制，因为它们修改既有长函数，整段覆盖会误伤无关逻辑。所有外部写入与真实模型调用均有独立授权门，所有验证命令均使用 `ruff format --check`。

**跨栈门禁：** 凡改动 `docs/api.json`、`frontend/src/api/**` 或 `GRAPH_NODES` 的任务（当前只有 B2），门禁必须同时包含后端四条与前端 `codegen:check` / `fixtures:check` / `lint` / `typecheck` / `test`。只跑后端门禁挡不住 `generated.ts` 与 `fixtures.generated.ts` 的漂移。

**类型一致性：** `extract_json_object`（B1）→ B2 使用；`AttemptFailureKind` / `DraftAttempt` / `ReviewAttempt`（B2 的 `quality_types.py`）→ Answer、Reviewer 与循环共同使用；`ReviewVerdict` 的不对称一致性约束（`passed=false` 必须带 issues；`passed=true` 归一化进 `advisory_notes`）→ QualityLoop 显式检查 `verdict.passed`，绝不以 issues 是否为空代替；`_validate` 返回 `list[str]` 且一次报全三类问题（B3 Step 4）→ B2 经 `validate_issues` 调用；`FactSummary`（B3）→ B5 复用；`QualityOutcome.reason`（B2）→ B6 消费；`QualityOutcome.attempts`（B2）→ `graph._response` 的 `quality_attempts`；`LlmFailureKind` / `LlmResult.failure_kind` / `LlmResult.usage_known`（A1）→ A2 的 guard 分支判据与落库；`LlmCallOptions`（A3）→ guard、fake 与四个结构化调用点，回答生成取默认值；`quality_max_attempts`（Config）→ dependencies → Graph → QualityLoop；`DEMO_ANALYTICS_SEED_BASE`（C1/C2）→ 与 `scripts/seed_demo_analytics.py` 既有取值一致；`SeedSettings`（C2）→ 脚本入口与写入护栏。名称跨任务一致。

**与既有代码的对齐点（第 5 稿逐条核对过，实施时若发现不符先停下来问）：** `MAX_INTENT_RETRIES=2`（`intent/service.py:27`）；四个 LLM 客户端共用一个 `LlmBudget`（`dependencies.py:143-166`）；`quality_attempts` 的 `le=2` 在 `schemas/chat.py:167,315` 两处、`adapters/chat.ts:91` 一处，数据库无此字段故不需要迁移；`.env.example:22` 的 `MAX_REVIEW_ATTEMPTS` 是 `config.py` 读不到的死变量；迁移编号从 `20260813_0010` 续到 `0011`；`Dockerfile:16` 的 `COPY app ./app` 已覆盖 `app/jobs/`；products 是维度表 `date_filtered=False`（`analytics/contract.py:167`），所以 C1 把商品目录冻结到 `DEMO_CATALOG_EPOCH` 不会让「商品明细」查空。

**执行顺序约束：**

```text
A1 → A2 → A3 → A4 → B4

B1 → B3 → B2 → B6 → B7
      └──→ B5 ───────→ B7

C1 → C2 → C3 → C4
```

- A1/A2 先建立可信错误与用量语义，A3/A4 才能用可靠数据验收降本；B4 只能消费 A4 实测。
- B2 依赖 B1 的宽松解析与 B3 的 issues/FactSummary；B5 依赖 B3；B6 依赖 B2 的类型化 reason；B7 在 B2/B4/B5/B6 全部完成后执行。
- C2 依赖 C1 的按日确定性；C3 是带独立用户授权门的正式部署；只有 C3 实际验收后才能把 C4 的线上状态写成完成。C2 Step 5（给旧全量脚本加护栏）必须在 C3 启用 Cron **之前**完成，否则线上会同时存在一个每日增量入口和一个默认可跑的全量抹除入口。
- 只有 A 段与 C1/C2 这类没有共享文件写冲突的任务可以并行；任何并行执行都不得同时编辑 `answer_service.py`、`config.py`、`.env.example`、`AGENTS.md` 或 `docs/project-progress.md`。

**已知未覆盖（不属本计划范围，已在 `docs/project-progress.md` 登记）：** `knowledge_documents` 仍为 0 行，RULE 类问题无知识依据；`backend/scripts/import_wiki.py` 与参考项目 43 份文档的导入未排期。
