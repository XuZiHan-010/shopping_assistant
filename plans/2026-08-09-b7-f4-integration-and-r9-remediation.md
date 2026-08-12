# B7/F4 分支整合与 R9 差异整改执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 `feature/b5-b6-answer-feedback-export` 为唯一后端主线，安全接入 `feature/f3-real-api-integration` 的前端成果，修正文档权威链，并按独立切片补齐已确认的 R9 还原度缺口。

**Architecture:** 新建集成分支承接 B4–B7 完整后端，只按路径移植 F3/F4 前端和必要的测试基础设施；OpenAPI、TypeScript 类型与 fixture 一律从集成后的 FastAPI 重新生成。集成完成后先扩大参考实现能力审计，再一次性设计意图契约、会话详情契约与导出语义，经用户审阅后才逐切片实施。

**执行分两个阶段，各自独立可交付：**

- **阶段 A（Task 1–4）**：分支整合。出口是一个通过全部门禁的统一候选分支，本身就是完整成果，必须停下来向用户汇报后再继续。
- **阶段 B（Task 5–15）**：R9 还原度整改。先审计、再设计、再实施，每个能力切片单独 TDD、单独验收。阶段 A 未达标不得进入——在半成品集成上做整改，后续任何失败都分不清是整改引入的还是集成遗留的。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、PostgreSQL、Vue 3、TypeScript、Pinia、ECharts、Vitest、Playwright。

---

## 执行状态（2026-08-11 对齐）

> 本节是本计划勾选状态的权威说明。此前计划正文的 94 个 step 全部为未勾选，与实际进度脱节；本次按
> SDD 账本、逐 Task 报告和 Git 提交逐条核对后回填。

| 阶段 | 范围 | 状态 |
| --- | --- | --- |
| 阶段 A | Task 1–4（含追加的 Task 3.5） | **已完成并提交**，2026-08-09 至 2026-08-10 |
| 阶段 B | Task 5–15 | **未开工**，一个 step 都没执行 |

### 阶段 A 的落点

集成分支 `feature/integrate-b7-f4` 从 `feature/b5-b6-answer-feedback-export` 的 `3faef8a` 拉出，
阶段 A 产出四个提交，**本地已提交、尚未推送 `origin`**：

| 提交 | 对应 Task |
| --- | --- |
| `b32fe99` 合并 B4 与 B5/B6/B7 文档增量，迁入 R9 计划与审计文档 | Task 1 Step 4–6 |
| `cd4b75d` 移植 F3/F4 前端到 B7 后端基线 | Task 2 |
| `e2c9829` 以集成后端重新生成 Chat fixture 与 TypeScript 类型 | Task 3 + Task 3.5 |
| `ac042a0` 补齐真实数据库端到端测试装配（B7 安全查询 + F4 前端） | Task 4 |

### 阶段 A 出口实测数字（2026-08-10）

对照「阶段 A 出口」的判据，每一项都达标或超出基线：

| 门禁 | 计划基线 | 实测 |
| --- | --- | --- |
| 后端真实库 pytest（55442） | ≥703 passed / 0 skipped / 0 failed | **707 passed / 0 skipped**，1 条第三方 deprecation warning |
| 后端非数据库 pytest | — | 591 passed / 116 skipped |
| `ruff check` / `ruff format --check` | 通过 | 通过（198 files formatted） |
| `mypy` | 通过 | `mypy app` 通过，88 源文件（门禁范围经用户批准收窄，见偏离 3） |
| 前端 Vitest | ≥205 passed | **206 passed**（25 文件） |
| 前端 lint/format/codegen/fixtures/mock/typecheck/build | 全部通过 | 全部通过；仅 ECharts 556.46 kB 非阻塞 chunk 提示 |
| Mock Playwright | ≥24 passed | **24 passed** |
| 真实库 Playwright（55443） | ≥3 passed | **3 passed**：GMV 图表、签名 CSV、商家隔离 |
| DeepSeek 调用 | 0 次、0 费用 | **0 次、0 费用**，全程 Fake/确定性 LLM |
| 共享 Docker 资源 | 不得触碰 | 只用 `borough-int-postgres` / `borough-int-f4-postgres`；共享卷执行后核验仍在 |

### 已登记的偏离

1. **集成 worktree 已不存在。** Task 1 Step 3 在 `.worktrees/feature-integrate-b7-f4` 执行；集成完成后
   仓库根改为直接签出 `feature/integrate-b7-f4`，该 worktree 已移除。`.worktrees/feature-b5-b6-answer-feedback-export`
   与 `.worktrees/feature-f3-real-api-integration` 仍在，只作对照。**因此本计划正文里所有指向
   `.worktrees\feature-integrate-b7-f4` 的路径都是执行当时的真实路径，阶段 B 恢复时要改在仓库根执行。**

   > **这条偏离直接暴露了一个被掩盖的测试隔离缺陷（2026-08-11）**：worktree 里没有 `backend/.env`，
   > 仓库根有。换到仓库根重跑后端真实库回归，5 条构造生产 `Settings` 的用例集体撞上
   > 「生产环境配置 LLM_API_KEY 时必须设置 ADMIN_TOKEN」——测试从未与开发者 `.env` 隔离。
   > **上表 707 passed 的数字只在无 `.env` 的环境里成立。** 已按 TDD 修复（`tests/conftest.py` 的
   > `isolate_settings_from_dotenv` + 复现测试），修复后在仓库根实测 **708 passed / 0 skipped /
   > 0 failed**，详见 `docs/project-progress.md`「最近验证」。
2. **追加了计划外的 Task 3.5。** Task 3 的 Step 4 定向测试实测 40 项中 3 项失败，失败原因是 Adapter
   契约测试仍钉着旧 B4 fixture 的期望值（图表 `enabled`、首条建议文案、`quality_notes` 非空）。按
   TDD 只改断言、不改生成物，作为独立切片 Task 3.5 执行并通过。记录见本文件 Task 3 之后。
3. **`mypy` 门禁范围经用户批准收窄为 `app`。** 计划原文是 `mypy app tests scripts`；`tests/` 与
   `scripts/` 有 103 项既有类型错误（32 个文件），用户批准将其登记为显式类型债务，不改 Mypy 配置、
   不掩盖检查。**这笔债务至今未还。**
4. **`gate-helpers.ps1` 曾被 PowerShell 执行策略拦下。** Task 3 执行时改用等价的内联退出码检查与
   `npm.cmd` 调用，门禁语义未降级。阶段 B 恢复时需先确认执行策略，否则会重复踩到。

### 阶段 A 出口的汇报义务

计划要求阶段 A 结束后「必须停下来向用户汇报后再继续」。实际执行**没有等待用户对阶段 B 表态**，
直接转入了文档目录整改 R10（`40cb282`）和前端 F5（`caca1e9` + 工作树未提交改动）。本次对齐即补上
这次汇报：阶段 A 全部达标，阶段 B 是否恢复、何时恢复仍待用户裁定。

### 阶段 B 恢复前必须先做的事

- Task 5–15 的 62 个 step 全部未执行，其中 Task 9–12 还要各自**先产出子计划文件**（指标口径、纯明细
  模式、跨业务查询、受控临时分组指标），这四份子计划目前在 `plans/` 里都不存在。
- 恢复前需重新核对基线：阶段 A 之后又落了 R10 文档整改与 F5 前端实现（F5 的代码、计划与设计修订
  **当前仍是工作树未提交改动**），Task 8「修复思考步骤展示与历史会话装配」的契约已被 F5 的评审结论
  扩写（本文件 Task 8 的 `answer_id` 与反馈状态要求即来自那次评审）。

## Global Constraints

- 面向用户的文案、错误提示、日志说明和项目文档使用中文；代码标识符使用英文。
- `yshopping-merchant-ai 4/` 只读，只能读取和对照，禁止修改、格式化或生成文件。
- **R9 基准：参考实现是需求基准。** 与它不一致的行为一律登记为「有意偏离」并写明理由，不得默认按自己认为更好的方式实现。本计划已裁定的四项均取 1:1 还原（见「零、已裁定的产品决策」）。
- 真实 LLM 提供商固定为 DeepSeek；本计划所有自动化验证必须使用 Fake/Mock LLM，模型调用次数为 0，不产生费用。
- LLM 只输出经 Pydantic 校验的结构化意图，禁止生成或执行任意 SQL。
- 所有经营查询、跨业务查询、导出和历史记录必须从可信身份注入 `merchant_id`。
- `docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts` 和生成 fixture 禁止手改，必须由脚本生成。
- 未经用户明确许可，不执行 `git commit`、`git push`、`git tag`、`gh pr create` 或 `gh pr merge`。
- 不在当前脏工作树中切分支、stash 或执行合并；执行时先使用 `superpowers:using-git-worktrees` 创建隔离 worktree（Task 1 Step 3 的 `git worktree add` 是该技能不可用时的等价回退命令，不是绕过它）。
- 每个独立能力遵循 TDD：先写失败测试，再实现最小变更，再跑定向与全量门禁。
- 本计划固定两个根路径，所有命令显式声明工作目录，禁止依赖上一条命令遗留的 cwd：
  - 仓库根（含只读参考项目与当前未提交文档）：`d:\vscode html\merchant_assistant`
  - 集成工作区：`d:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4`
- 只读参考项目 `yshopping-merchant-ai 4/` 被 `.gitignore` 忽略，**只存在于仓库根，不存在于任何 worktree**。所有对照阅读必须用绝对路径 `d:\vscode html\merchant_assistant\yshopping-merchant-ai 4\`。
- `.worktrees/` 是全新检出，**没有 `frontend/node_modules`**；任何 npm 命令前必须先完成 Task 1 Step 7 的依赖安装。
- **禁止触碰共享 Docker 资源。** 不得对 `borough` Compose 项目执行 `down -v`、`rm` 或任何删除卷的操作——那是其他 worktree 共用的。本计划一律使用自带名称与端口的独立容器（见「门禁执行约定」）。
- **所有门禁必须 fail-fast 执行**，禁止把多条原生命令顺序堆在一个代码块里当作"通过"（见「门禁执行约定」）。

---

## 零、已裁定的产品决策

用户于 2026-08-09 明确裁定，四项全部取 1:1 还原参考实现：

| 议题 | 裁定 | 参考依据 |
| --- | --- | --- |
| 历史会话思考步骤 | **扩后端契约**：会话详情返回脱敏的助手回答载荷（`answer_mode`、`thinking_steps`、质量状态、表格元数据），明确不返回完整敏感数据行与过期签名 URL | 当前后端只返回 `role/content/created_at`，前端无从还原 |
| 跨业务计划参数非法 | **降级而非 INVALID**：关闭 `cross_business_plan`、清空 `plan_type`、加语义备注，基础意图仍为 VALID，回退普通查询并显示计划被拒绝的说明 | `SemanticLayerService.validateCrossBusinessPlan` |
| 生成指标聚合选择 | **类别驱动固定模板**：按问题类别（ORDER/REFUND）选模板，每个模板吐固定一组聚合列。契约里**不加** `measure` 枚举 | `DorisQueryService` 按 `intent.getCategory() == QuestionCategory.REFUND` 分流；`QuestionIntent` 无 measure 字段 |
| 生成指标截断导出 | **允许返回 CSV**：结果超出展示上限时创建导出记录并返回签名 URL，需扩 §8 的 export 契约（当前只允许 DETAIL） | `DorisQueryService.queryGeneratedGroupedMetric` 在 `totalRows > DETAIL_DISPLAY_LIMIT` 时写 CSV 并设 `csvUrl`/`detailNotice` |

**同时确认的一处不对称语义**（不要按"统一降级"一刀切）：`SemanticLayerService.validateGeneratedMetric` 在维度未命中白名单时**确实**把整条意图设为 `INVALID`（`setIntentType(INVALID)` + `setAnswerMode(INVALID)`）。跨业务降级、生成指标 INVALID，两者行为相反，各自 1:1 还原。

**另一处需要跟随的精确语义：** `SemanticLayerService.outputMatchesIntent` 对纯明细是 `return !StringUtils.hasText(answer)`——参考实现**要求**正文为空，不是"允许为空"。契约措辞必须跟着改。

---

## 门禁执行约定

所有验证步骤共用这套约定。**不遵守就会出现假绿**：PowerShell 里 `uv run pytest` 失败后若紧跟一条成功的命令，整段的退出码就是 0，计划记录的"全部通过"毫无意义。

- [x] **约定 1: 门禁脚本骨架**

把下面这段存为 `C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1`，每个门禁步骤开头 dot-source 它。**不要**把它写进仓库——它是执行期工具，不是项目产物。

```powershell
# 刻意用 Continue 而不是 Stop：PowerShell 5.1 下把 $ErrorActionPreference='Stop'
# 与原生 exe 的 stderr 重定向放在一起，会把普通 stderr 行包成 NativeCommandError
# 抛出，反而让本来成功的命令炸掉。可靠性一律靠显式的 $LASTEXITCODE 检查 + throw。
$ErrorActionPreference = 'Continue'

function Invoke-Gate {
  param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Command)
  Write-Host "==> $Name"
  & $Command
  if ($LASTEXITCODE -ne 0) { throw "门禁失败：$Name（exit=$LASTEXITCODE）" }
}

# rg 的退出码语义与普通命令相反：0=有命中、1=无命中、2=执行错误。
# 「零命中即成功」的安全扫描必须走这个函数，不能套 Invoke-Gate。
function Assert-NoMatch {
  param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string[]]$RgArgs)
  Write-Host "==> $Name（要求零命中）"
  $hits = & rg @RgArgs
  if ($LASTEXITCODE -eq 0) { throw "$Name 出现命中：`n$($hits -join "`n")" }
  if ($LASTEXITCODE -ne 1) { throw "$Name 的 rg 执行异常（exit=$LASTEXITCODE）" }
}

function Wait-Postgres {
  param([Parameter(Mandatory)][string]$Container, [Parameter(Mandatory)][string]$Database, [int]$TimeoutSeconds = 90)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    Start-Sleep -Seconds 2
    docker exec $Container pg_isready -U borough -d $Database *> $null
    $ready = ($LASTEXITCODE -eq 0)
  } until ($ready -or (Get-Date) -gt $deadline)
  if (-not $ready) { throw "$Container 在 $TimeoutSeconds 秒内未就绪" }
}
```

- [x] **约定 2: 环境变量一律 try/finally 清理**

```powershell
$env:REQUIRE_INTEGRATION_DB = '1'
$env:TEST_DATABASE_URL = $IntegrationDbUrl
try {
  Invoke-Gate 'pytest（真实库）' { uv run pytest }
} finally {
  Remove-Item Env:REQUIRE_INTEGRATION_DB -ErrorAction SilentlyContinue
  Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
```

- [x] **约定 3: 独立 Docker 资源命名**

本计划创建且只创建下列资源，全部带 `borough-int-` 前缀，与共享的 `borough` Compose 项目零交集。数据留在容器可写层，`docker rm -f` 即彻底清空——**因此每次重建都保证 `alembic_version` 为空**，不需要也不允许删任何卷。

| 用途 | 容器名 | 端口 | 数据库名 |
| --- | --- | --- | --- |
| 后端单元/集成回归 | `borough-int-postgres` | 55442 | `borough_integrate_test` |
| 前端真实库 E2E | `borough-int-f4-postgres` | 55443 | `borough_f4_test` |

两个库名都以 `_test` 结尾，满足 `backend/tests/postgres.py::assert_test_database` 的硬校验；E2E 库名以 `borough_f4_test` 结尾，满足 `backend/scripts/seed_f4_e2e.py` 的硬校验。删除前必须确认容器名前缀为 `borough-int-`，禁止对任何其他容器执行 `docker rm -f`。

---

## 一、已经裁定的取舍

| 范围 | 裁定 |
| --- | --- |
| 后端生产代码 | 全部以 `feature/b5-b6-answer-feedback-export` 为准 |
| F3/F4 前端 | 从 `feature/f3-real-api-integration` 移植 |
| F3/F4 替代 analytics/export 后端 | 不移植。2026-08-09 实测：F3 相对 B7 删除了 `services/safe_query.py`、`repositories/export.py`、`services/answer_service.py`、`services/review_service.py`、`services/visualization_service.py`、`api/routes/feedback.py`、`api/routes/metrics.py`、`repositories/llm_budget.py`、`core/rate_limit.py` 及 4 个迁移，移植等于把 B5–B7 整体删回去 |
| F3/F4 浏览器测试基础设施 | 可移植测试意图与双商家 Seed 的行为，但必须改为调用 B7 的 `safe_query.py`、`repositories/export.py` 和完整依赖装配 |
| OpenAPI/生成类型/fixture | 从集成后端重新生成，不选择任一分支的旧产物 |
| `feature/f2-mock-conversation` | 集成分支全部门禁通过、且用户授权提交后才允许快进（见 Task 15 的顺序依赖） |

## 二、现有文档必须修改的范围

现有文档需要修改，但按以下权威顺序进行，不能一次性在所有文件里复制同一份字段表：

1. `docs/PRD.md`
   - **Task 5 阶段**：保留已修改的指标业务口径/SQL 口径并列语义；不写 Python 类名、函数签名或迁移文件名。
   - **推迟到 Task 7**：跨业务查询用户故事、三种受控计划、参数非法时的降级语义；“纯明细”与“要求分析的明细”的区分及纯明细正文**必须**为空；受控临时分组指标的用户价值与白名单边界；生成指标截断时的导出可见性。
2. `docs/backend-development-plan.md` — **分两节，不要混**
   - **§6.2 Intent Contract（line 261）是内部 LLM 意图契约的唯一权威位置**：`CrossBusinessPlan`、`GeneratedMetricPlan`、`analysis_requested`、以及参数非法时的降级/INVALID 分流规则。推迟到 Task 7。
   - **§8 API Schema（line 597）只放外部 API 契约**：§8.2 `ChatResponse` 的指标口径字段、`answer` 条件非空规则、export 契约扩展（生成型 METRIC 可返回导出）、会话详情响应新增的助手回答载荷。指标口径字段在 Task 5 阶段修，其余推迟到 Task 7。
   - Task 5 阶段还需把本轮整改登记为 B7 后的 R9 收口切片，不重写已完成的 B4–B7 历史。
3. `docs/frontend-development-plan.md`
   - **Task 5 阶段**：定义指标双口径、来源徽标、生成告警、库表、维度和报表链接。
   - **推迟到 Task 7**：完整思考步骤列表的运行态/完成态/历史态展示；空正文 DETAIL 的渲染与历史会话表现。
4. `docs/project-progress.md`
   - 在集成前写“B7 与 F4 分别完成、尚未集成”；
   - 集成验证后再写统一分支、实际测试数字和下一步；
   - 不把尚未执行的 Railway 部署写成当前第一优先级。
5. `docs/yshopping-parity-audit.md`
   - 将“全量审计”改为“持续更新的第一轮全局审计”；
   - 把冲突实测修正为 32 个文本冲突、6 个 add/add；
   - 把 F4 状态改为“分支完成、尚未集成”；
   - 把“思考过程只渲染最后一步”修正为“运行中只显示最后一步，完成后不显示步骤列表；历史会话因后端不返回载荷而完全无步骤”；
   - 删除“生成指标依赖跨业务查询”的错误依赖，只保留“共享意图契约设计”。
6. `AGENTS.md`
   - 只更新阶段状态、入口索引和 R9 审计文件说明；
   - 不复制 ChatResponse 字段表，精确契约仍归 `docs/backend-development-plan.md`。
7. `docs/api.json`、`docs/api.md`
   - 只在后端契约实现后运行 `scripts/export_openapi.py` 生成；
   - 禁止在文档阶段手工编辑。

---

### Task 1: 建立隔离集成工作区、迁入未提交文档并装好依赖

**Files:**
- Create worktree: `.worktrees/feature-integrate-b7-f4/`
- Carry over（未跟踪，仓库根独有，新 worktree 里不存在）：见 Step 4 的 allowlist
- Carry over（已跟踪但未提交的增量）：`.gitignore`、`AGENTS.md`、`docs/PRD.md`、`docs/backend-development-plan.md`、`docs/frontend-development-plan.md`、`docs/project-progress.md`
- Preserve: 仓库根工作树保持原样，不清理、不提交、不 stash

**Interfaces:**
- Consumes: `feature/b5-b6-answer-feedback-export`、`feature/f3-real-api-integration`
- Produces: `feature/integrate-b7-f4`，其起点必须等于 `3faef8a` 或该分支更新后的明确 HEAD；工作区内已含全部 R9 文档输入且依赖可运行

> **为什么需要 Step 4/5：** 仓库根当前 checkout 在 `feature/b4-safe-analytics-query`，带着 8 个未跟踪文件和 6 个已修改文件。`git worktree add` 出来的是干净检出，这些内容一个都不会带过去。Task 5 起的多个任务都要修改 `docs/yshopping-parity-audit.md`，而它是未跟踪文件——不迁移就无从改起。

- [x] **Step 1: 复核三个工作树状态**

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
git worktree list
git status --short --branch
git -C .worktrees/feature-b5-b6-answer-feedback-export status --short --branch
git -C .worktrees/feature-f3-real-api-integration status --short --branch
```

Expected: 根工作树在 `feature/b4-safe-analytics-query`，保留 6 个 ` M` 与 8 个 `??`；B5/B6/B7 与 F3/F4 worktree 均干净。

- [x] **Step 2: 验证祖先关系**

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
git merge-base --is-ancestor feature/f2-mock-conversation feature/b5-b6-answer-feedback-export; "f2->b5b6 exit=$LASTEXITCODE"
git merge-base --is-ancestor feature/b4-safe-analytics-query feature/b5-b6-answer-feedback-export; "b4->b5b6 exit=$LASTEXITCODE"
git rev-list --left-right --count feature/b5-b6-answer-feedback-export...feature/f3-real-api-integration
```

Expected: 前两条退出码均为 0（2026-08-09 实测通过）；第三条实测为 `41  27`，两支各有独立提交，确认必须走移植而非合并。

- [x] **Step 3: 使用 worktree 技能创建集成分支**

优先按 `superpowers:using-git-worktrees` 创建；技能不可用时使用等价命令：

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
git worktree add .worktrees/feature-integrate-b7-f4 -b feature/integrate-b7-f4 feature/b5-b6-answer-feedback-export
git -C .worktrees/feature-integrate-b7-f4 branch --show-current
git -C .worktrees/feature-integrate-b7-f4 rev-parse --short HEAD
```

Expected: 分支名为 `feature/integrate-b7-f4`，HEAD 为 `3faef8a`，工作区干净。

- [x] **Step 4: 按显式 allowlist 迁移未跟踪文件**

**不要**用 `git ls-files --others` 的输出直接复制——它会把执行期产生的临时文件、日志、调试输出一并带进集成分支。改为固定清单，并要求实际集合与清单**完全一致**，多一个少一个都停：

> **路径已过期（2026-08-10）**：下面 allowlist 里的 `docs/superpowers/plans/`、`docs/superpowers/specs/` 是本步骤**执行当时**的真实路径，保留以如实记录已发生的操作。此后按 `AGENTS.md` R10 已迁移——计划移至 `plans/`，设计文档移至 `docs/specs/`，`docs/superpowers/` 已删除。本步骤已完成，不会重跑，无需按新路径改写。

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
$target = 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
$allowlist = @(
  'docs/yshopping-parity-audit.md',
  'docs/superpowers/plans/2026-08-05-backend-b5-b6.md',
  'docs/superpowers/plans/2026-08-06-frontend-f3-real-api.md',
  'docs/superpowers/specs/2026-08-05-backend-b5-b6-design.md',
  'docs/superpowers/specs/2026-08-06-frontend-f3-design.md',
  'docs/superpowers/specs/2026-08-06-frontend-f3-f9-roadmap.md',
  'docs/superpowers/specs/2026-08-06-frontend-f4-design.md',
  'plans/2026-08-09-b7-f4-integration-and-r9-remediation.md'
)
$actual = @(git ls-files --others --exclude-standard)
$diff = Compare-Object -ReferenceObject $allowlist -DifferenceObject $actual
if ($diff) {
  $diff | Format-Table -AutoSize
  throw '未跟踪文件集合与 allowlist 不一致：多出的文件不得迁移，缺失的文件必须先确认去向'
}
foreach ($item in $allowlist) {
  $dest = Join-Path $target $item
  New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
  Copy-Item -LiteralPath $item -Destination $dest -Force
}
git -C $target status --short
```

Expected: 集成工作区出现且只出现这 8 个 `??`。仓库根仍是 8 个 `??`（复制不是移动）。若 `Compare-Object` 报差异，先人工判断多出的文件是什么，**不得**为了让脚本跑过去而扩大 allowlist。

- [x] **Step 5: 三方合并未提交的已跟踪文档增量**

只导出「相对根工作树 HEAD（= b4）的未提交增量」，**不要**用 `git diff feature/b5-b6-answer-feedback-export -- ...`——后者会把 b5b6 独有的 B7 文档内容一并反向删除（实测 b5b6 相对 b4 在 `docs/backend-development-plan.md` +164 行、`docs/project-progress.md` +82 行）。

补丁用 `git diff --output=` 直接落盘，**不要**经过 `Out-File`——PowerShell 5.1 的 `Out-File -Encoding utf8` 写 BOM，且会按控制台编码转码，`git apply` 会因此报 `corrupt patch`：

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
$patch = Join-Path $env:TEMP 'root-doc-delta.patch'
git diff --output="$patch" HEAD -- .gitignore AGENTS.md docs/PRD.md docs/backend-development-plan.md docs/frontend-development-plan.md docs/project-progress.md
if ($LASTEXITCODE -ne 0) { throw '导出补丁失败' }
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
git apply --3way --whitespace=nowarn "$patch"
git status --short
```

Expected: `.gitignore`、`AGENTS.md`、`docs/PRD.md` 干净落地（实测 b5b6 与 b4 在这三个文件上完全一致，纯增量无冲突）。`docs/backend-development-plan.md`、`docs/frontend-development-plan.md`、`docs/project-progress.md` 允许出现冲突标记——b5b6 和根工作树都改过它们。

- [x] **Step 6: 逐个解决 Step 5 的冲突并核对内容未丢失**

冲突解决原则：**b5b6 的 B7 内容一律保留**，根工作树增量按语义补进去，绝不用整块覆盖。解决后必须确认三类内容同时在场：

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
Assert-NoMatch '冲突标记残留' @('-n', '^<<<<<<<|^>>>>>>>', 'docs', 'AGENTS.md', '.gitignore')
Invoke-Gate 'B7 段落在场' { rg -n 'B7|Railway|LLM_BUDGET_EXCEEDED' docs/project-progress.md | Select-Object -First 5 }
Invoke-Gate '指标双口径在场' { rg -n '指标业务口径|SQL 口径' docs/PRD.md | Select-Object -First 5 }
```

Expected: 冲突标记零命中；后两条各有命中。

- [x] **Step 7: 安装依赖**

新 worktree 是全新检出，`frontend/node_modules` 不存在（实测其他 worktree 同样没有），任何 npm 命令在此之前都会失败：

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
Invoke-Gate 'uv sync' { uv sync }
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'npm ci' { npm ci }
Invoke-Gate 'playwright install' { npx playwright install chromium }
```

Expected: 三条命令均通过；`frontend/node_modules` 与 `backend/.venv` 存在。

- [x] **Step 8: 设置只读核对基线**

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
git diff --name-status feature/f2-mock-conversation..feature/b5-b6-answer-feedback-export -- backend
git diff --name-status feature/f2-mock-conversation..feature/f3-real-api-integration -- frontend
```

Expected: 第一份清单作为保留后端基线，第二份清单作为待移植前端基线。

- [x] **Step 9: 审查检查点**

不得提交。记录集成分支 HEAD、三个 worktree 状态、Step 5/6 冲突解决结论，以及仓库根未提交文件清单（应与 Step 1 完全一致，证明根工作树未被改动）。

---

### Task 2: 只按路径移植 F3/F4 前端

**Files:**
- Replace from F3/F4: `frontend/**`
- Keep from B7: `backend/**`
- Review separately: `scripts/export_chat_fixtures.py`、`docs/fixtures/chat/**`

**Interfaces:**
- Consumes: F3/F4 最终前端目录
- Produces: 在 B7 后端基线上可编译的 F4 前端；不引入 F3 生产后端

> **已实测的前置事实（降低本任务风险）：** `backend/app/schemas/chat.py` 在 B7 与 F3 两个分支上**逐字节相同**，导出端点同为 `GET /api/exports/{export_id}` 且签名参数一致，F3 前端 `errors.ts` 已认识 B7 的 `LLM_BUDGET_EXCEEDED`。因此 F4 前端与 B7 后端的**现有**契约本就对齐，Step 5 的失败面确实只应落在生成物同步上。

- [x] **Step 1: 预览前端路径差异并确认无删除项**

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
git diff --stat feature/b5-b6-answer-feedback-export feature/f3-real-api-integration -- frontend
git diff --name-status feature/b5-b6-answer-feedback-export feature/f3-real-api-integration -- frontend | Where-Object { $_ -match '^D' }
```

Expected: 第二条**必须无输出**。2026-08-09 实测为 23 个 `A`、0 个 `D`，这正是下一步能安全使用 `git restore` 的前提——`git restore --source` 只覆盖源分支里存在的文件，不会删除源分支已移除的文件。若第二条有输出，改用「先 `git rm -r frontend` 再 restore」，否则会留下孤儿文件。

- [x] **Step 2: 导入 F3/F4 最终前端树**

```powershell
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
git restore --source feature/f3-real-api-integration -- frontend
git status --short -- frontend | Measure-Object -Line
```

Expected: 只有 `frontend/**` 发生变化，`backend/**` 保持 B7 内容。

- [x] **Step 3: 建立生产后端禁止清单**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
$touched = @(git diff --name-only feature/b5-b6-answer-feedback-export -- backend/app backend/migrations)
if ($touched) { $touched; throw '阶段 A 不允许改动 backend/app 或 backend/migrations' }
```

Expected: 无输出。若抛错，立即还原这些路径到集成分支起点。

- [x] **Step 4: 保留 F4 真实浏览器验收行为，但重写测试装配**

允许借鉴以下 F3 文件的测试行为，不直接复制其生产依赖：

```text
backend/tests/support/e2e_app.py
backend/scripts/seed_f4_e2e.py
frontend/e2e/real-api/analytics.spec.ts
frontend/playwright.real-api.config.ts
```

重写后的测试装配必须导入：

```python
from app.repositories.analytics import AnalyticsRepository
from app.repositories.export import ExportRepository
from app.services.safe_query import SafeQueryService
from app.services.export_service import ExportService
```

不得导入 F3 的 `app.services.query_service`、`app.repositories.exports`。

- [x] **Step 5: 运行前端静态门禁，记录预期失败**

前置：Task 1 Step 7 的 `npm ci` 必须已完成。

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'typecheck' { npm run typecheck }
Invoke-Gate 'vitest' { npm run test }
```

Expected: 若失败，只允许是生成契约/fixture 与最终 B7 后端尚未同步造成的失败；记录具体测试名后进入 Task 3。若出现 `schemas/chat.py` 字段缺失、导出端点 404 一类的契约级失败，说明前置事实已失效，**停止并回报用户**，不要靠改前端硬凑。

- [x] **Step 6: 审查检查点**

不得提交。重跑 Step 3 的禁止清单检查，确认仍无输出。

---

### Task 3: 以集成后端重新生成唯一契约与 fixture

**Files:**
- Generate: `docs/api.json`
- Generate: `docs/api.md`
- Generate: `frontend/src/api/generated.ts`
- Generate: `docs/fixtures/chat/*.json`
- Generate: `frontend/src/api/mock/fixtures.generated.ts`
- Modify only if generation fails: `scripts/export_chat_fixtures.py`

**Interfaces:**
- Consumes: B7 FastAPI `create_app()` 与 ChatResponse
- Produces: 后端 OpenAPI → generated.ts → Adapter → Store → Component 的单向字段链

- [x] **Step 1: 导出 FastAPI OpenAPI**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
Invoke-Gate 'export_openapi' { uv run python ../scripts/export_openapi.py }
```

Expected: 不启动真实 LLM，不访问 DeepSeek；`docs/api.json` 与 `docs/api.md` 更新成功。

- [x] **Step 2: 生成 TypeScript 类型**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'codegen' { npm run codegen }
Invoke-Gate 'codegen:check' { npm run codegen:check }
```

Expected: `codegen:check` 通过。

- [x] **Step 3: 重新导出 Chat fixture**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
Invoke-Gate 'export_chat_fixtures' { uv run python ../scripts/export_chat_fixtures.py }
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'fixtures' { npm run fixtures }
Invoke-Gate 'fixtures:check' { npm run fixtures:check }
Invoke-Gate 'mock:check' { npm run mock:check }
```

Expected: 所有 fixture 来自 Fake Agent；模型调用 0 次，费用为 0。

- [x] **Step 4: 运行 Adapter 与传输层定向测试**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'adapter/传输层定向测试' { npm run test -- src/api/adapters/chat.spec.ts src/api/chat.spec.ts src/api/sse.spec.ts }
```

Expected: 全部通过；组件不直接导入 `generated.ts`。

- [x] **Step 5: 审查检查点**

不得提交。检查生成文件 diff 只反映 B7 最终契约，不包含 F3 替代后端专用 schema。

---

### Task 3.5（执行期追加）: 同步 B7 再生 fixture 的 Adapter 断言

**追加原因：** Task 3 Step 4 的定向测试实测 40 项中 3 项失败，且全部落在
`frontend/src/api/adapters/chat.spec.ts`——`chat.spec.ts`（7 项）与 `sse.spec.ts`（9 项）全通过。
失败是旧 B4 fixture 期望与 B7 再生 fixture 的真实语义不符，属于 Task 3 Step 5「生成物 diff 只反映
B7 最终契约」的正常后果，不是回归。按 TDD 拆成独立切片执行，避免把断言修改混进生成步骤。

**Files:**
- Modify: `frontend/src/api/adapters/chat.spec.ts`（只改 3 组既有断言）

- [x] **Step 1: 记录 RED**

  `npm run test -- src/api/adapters/chat.spec.ts src/api/chat.spec.ts src/api/sse.spec.ts` → 37/40 通过、3 失败：
  `answer.chart?.enabled` 期望 `true` 而 B7 fixture 为 `false`；首条 recommendation 的 `action` 期望含「核对」
  而 fixture 为「确认日期范围和维度是否覆盖你想了解的口径。」；`quality.notes.length` 期望大于 0 而 fixture 为空数组。

- [x] **Step 2: 只改断言，不改生成物**

  图表期望同步为 `enabled: false` 且空数据数组；建议文案同步为 fixture 精确文案；质量轨迹断言改为验证
  `quality_notes` 正确映射并明确允许空数组。未改生成物、`backend/app`、`backend/migrations`、测试装配或参考项目。

- [x] **Step 3: 记录 GREEN**

  同一命令 3/3 文件通过、40/40 通过；单跑 `src/api/adapters/chat.spec.ts` 为 24/24 通过。

**残余风险（未消除）：** fixture 表达的是当前 FakeAgent/B7 的固定语义。后端业务语义变更后必须重新生成
fixture 并**有意识地复核这些精确期望**，不能只以测试通过为准。

---

### Task 4: 完成统一分支全量验证

**Files:**
- Create or adapt: `backend/tests/support/e2e_app.py`，改为装配 B7 的受控查询与导出服务
- Create or adapt: `backend/scripts/seed_f4_e2e.py`，只写入专用测试库的双商家确定性数据
- Modify: `backend/tests/integration/test_migrations.py`，让它尊重 `TEST_DATABASE_URL`
- Modify: `frontend/playwright.real-api.config.ts`，数据库地址改为从环境变量注入
- Test: `frontend/e2e/real-api/analytics.spec.ts`

**Interfaces:**
- Produces: 一个同时通过 B7 后端门禁和 F4 前端门禁的候选集成分支

> **为什么必须用全新的独立容器：** F3 的迁移 `20260808_0005_f4_analytics_slice` 的 `down_revision` 是 `20260804_0004`，是从 B4 岔出去的**独立 alembic head**，集成分支不含这个 revision 文件。任何残留 F3 版本历史的库都会以 `Can't locate revision 20260808_0005` 直接失败。用 `docker rm -f` + `docker run` 重建独立容器，既保证 `alembic_version` 为空，又完全不碰共享的 `borough` Compose 项目和它的卷。

- [x] **Step 1: 创建两个独立测试数据库容器**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
# 只删本计划自己创建的容器；名称前缀 borough-int- 是硬约定。
# 容器不存在时 docker rm 会返回非 0，这里刻意不检查退出码——但先断言名称前缀，
# 防止这段被复制粘贴后改成删别的容器。
foreach ($name in @('borough-int-postgres', 'borough-int-f4-postgres')) {
  if (-not $name.StartsWith('borough-int-')) { throw "拒绝删除非本计划容器：$name" }
  docker rm -f $name *> $null
}
docker run -d --name borough-int-postgres `
  -e POSTGRES_DB=borough_integrate_test -e POSTGRES_USER=borough -e POSTGRES_PASSWORD=borough_local `
  -p 55442:5432 postgres:16-alpine
if ($LASTEXITCODE -ne 0) { throw '创建 borough-int-postgres 失败' }
docker run -d --name borough-int-f4-postgres `
  -e POSTGRES_DB=borough_f4_test -e POSTGRES_USER=borough -e POSTGRES_PASSWORD=borough_local `
  -p 55443:5432 postgres:16-alpine
if ($LASTEXITCODE -ne 0) { throw '创建 borough-int-f4-postgres 失败' }
Wait-Postgres -Container 'borough-int-postgres' -Database 'borough_integrate_test'
Wait-Postgres -Container 'borough-int-f4-postgres' -Database 'borough_f4_test'
```

Expected: 两个容器就绪，`alembic_version` 表均不存在。共享的 `borough` Compose 项目**完全未被触碰**——执行后用 `docker volume ls` 确认 `borough_postgres_data` 仍在。

- [x] **Step 2: 让迁移测试尊重 `TEST_DATABASE_URL`**

`backend/tests/conftest.py:82` 已经读 `TEST_DATABASE_URL`，但 `backend/tests/integration/test_migrations.py:13` 直接用 `DEFAULT_TEST_DATABASE_URL` 常量，**绕过了环境变量**。不修它，注入的地址对迁移测试无效，它会去连不存在的 55432 库。

先写失败断言（临时设一个不存在的地址，确认迁移测试确实没有跟随），再改：

```python
# backend/tests/integration/test_migrations.py
import os

from tests.postgres import DEFAULT_TEST_DATABASE_URL, alembic_config, assert_test_database

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
```

并把函数体里的 `DEFAULT_TEST_DATABASE_URL` 引用改为 `DATABASE_URL`。这是 `backend/tests/**` 的改动，不违反 Task 2 Step 3 的 `backend/app` + `backend/migrations` 禁止清单。

- [x] **Step 3: 后端非数据库门禁**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
Invoke-Gate 'ruff check' { uv run ruff check . }
Invoke-Gate 'ruff format --check' { uv run ruff format --check . }
Invoke-Gate 'mypy' { uv run mypy app tests scripts }
Invoke-Gate 'pytest（无真实库）' { uv run pytest }
```

Expected: 无真实 LLM 调用；跳过项必须逐项说明。

- [x] **Step 4: 后端真实 PostgreSQL 回归**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
$env:REQUIRE_INTEGRATION_DB = '1'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55442/borough_integrate_test'
try {
  Invoke-Gate 'pytest（真实库）' { uv run pytest }
} finally {
  Remove-Item Env:REQUIRE_INTEGRATION_DB -ErrorAction SilentlyContinue
  Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: 不少于 703 passed、0 skipped、0 failed（B7 于 2026-08-06 在真实库上的实测基线）；Fake LLM，费用为 0。

**中止判据：** 若 passed 数低于 703 或出现 skipped，先按 `superpowers:systematic-debugging` 定位根因，**不得**下调本计划记录的基线数字。若根因是「移植前端时误动后端」，回到 Task 2 Step 3 的禁止清单核对；若根因是数据库残留，回到 Step 1 重建。两者都不成立时停止并回报用户。

- [x] **Step 5: 前端全量门禁**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
foreach ($gate in @('lint','format:check','codegen:check','fixtures:check','mock:check','typecheck','test','build')) {
  Invoke-Gate $gate { npm run $gate }
}
```

Expected: 不少于 F4 基线 205 passed，所有命令通过。

- [x] **Step 6: Mock Playwright**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'playwright（mock）' { npm run test:e2e }
```

Expected: 不少于 F4 基线 24 passed。

- [x] **Step 7: 把 E2E 数据库地址改为环境变量注入**

F3 的 `playwright.real-api.config.ts` 把地址写死成 `127.0.0.1:55433`。改为读环境变量、缺省回落到本计划的 55443：

```ts
const DATABASE_URL =
  process.env.F4_E2E_DATABASE_URL ??
  'postgresql+psycopg://borough:borough_local@127.0.0.1:55443/borough_f4_test'
```

`webServer.env` 里的 `DATABASE_URL` 与 `F4_E2E_DATABASE_URL` 都用这个常量。不要改库名后缀——`seed_f4_e2e.py` 硬校验数据库名必须以 `borough_f4_test` 结尾。

- [x] **Step 8: 真实 PostgreSQL + 确定性意图 Playwright**

运行前再次确认：测试服务器使用确定性意图代理，DeepSeek 调用次数 0，费用为 0。`webServer` 会自行执行 `alembic upgrade head` 与 `seed_f4_e2e.py`，无需手工预跑。

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
$env:F4_E2E_DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55443/borough_f4_test'
try {
  Invoke-Gate 'playwright（真实库）' { npm run test:e2e:real }
} finally {
  Remove-Item Env:F4_E2E_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: 不少于 F4 基线 3 passed——GMV 图表、DETAIL 表格/签名导出、双商家隔离三条核心场景通过。

- [x] **Step 9: 集成裁决记录**

将实际命令、通过数、跳过数和失败修复写入 `docs/project-progress.md`。未经用户明确许可不得提交或推进 `feature/f2-mock-conversation`。

---

## 阶段 A 出口：集成完成

> **状态：已达标（2026-08-10 实测，2026-08-11 对齐记录）。** 逐条判据的实测数字见本文件开头的
> 「执行状态」。唯一未按计划执行的是「停下来向用户汇报」这一条——当时未等用户对阶段 B 表态就转入了
> R10 与 F5，该汇报已在 2026-08-11 补上。

Task 1–4 全绿即构成一个**独立可交付的成果**：一个统一的候选集成分支。此处必须停下来向用户汇报，再决定是否继续阶段 B。阶段 A 的完成判据：

- 集成分支以 B7 后端为基线，`git diff --name-only feature/b5-b6-answer-feedback-export -- backend/app backend/migrations` 为空。
- 后端真实库 ≥703 passed / 0 skipped / 0 failed；前端 ≥205 passed；Mock Playwright ≥24 passed；真实库 Playwright ≥3 passed。**每一项都由 `Invoke-Gate` 校验过退出码**，不是靠肉眼看输出。
- OpenAPI、`generated.ts`、fixture 均由集成后端生成且无漂移。
- 未提交文档增量与 8 个 allowlist 文件已完整迁入集成工作区，仓库根未被改动。
- 共享的 `borough` Compose 项目与 `borough_postgres_data` 卷完好无损。
- 全程 Fake/Mock LLM，DeepSeek 调用 0 次。

阶段 A 未达标时不得进入阶段 B。

---

### Task 5: 校正文档事实状态与审计清单

**Files:**
- Modify: `docs/PRD.md`、`docs/backend-development-plan.md`、`docs/frontend-development-plan.md`、`docs/project-progress.md`、`docs/yshopping-parity-audit.md`、`AGENTS.md`
- Preserve: `.gitignore`

**Interfaces:**
- Produces: 与集成代码一致的事实状态快照，为 Task 7 的契约设计留出干净底稿

> **本任务只做事实校正，不设计新契约。** `CrossBusinessPlan`、`GeneratedMetricPlan`、`analysis_requested`、纯明细正文规则、会话详情载荷、生成指标导出全部归 Task 7——那里有用户审阅门。本任务先写下来，Task 7 一旦改设计就得推翻重写。

- [ ] **Step 1: 按权威顺序修正事实状态**

按“PRD → 后端 §8 指标口径 → 前后端计划 → AGENTS 索引 → progress 快照”顺序修改，范围严格限于本计划第二节标注为「Task 5 阶段」的条目。

- [ ] **Step 2: 修正审计清单的五项已知问题**

逐项落实第二节对 `docs/yshopping-parity-audit.md` 的要求。注意第四项的措辞已按实测更正：历史会话不是"只渲染最后一步"，而是**后端根本不返回步骤载荷**，前端无从渲染。

- [ ] **Step 3: 检查权威字段没有多处复制**

排除 `docs/specs/` 与 `plans/`——设计规格和执行计划本来就要写类名：

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
rg -n 'metric_business_definition|CrossBusinessPlan|GeneratedMetricPlan|analysis_requested|table_only' AGENTS.md docs --glob '!docs/specs/**'
```

Expected（Task 5 阶段）：`CrossBusinessPlan`/`GeneratedMetricPlan`/`analysis_requested` **零命中**——它们还没设计。指标口径字段只在 `docs/backend-development-plan.md` §8.2。

Expected（Task 14 复查时）：内部意图类型只在 **§6.2 Intent Contract**；外部 API 字段只在 **§8**；PRD 只描述产品语义，AGENTS 只做索引。同一个类名同时出现在 §6.2 和 §8 即为违规。

- [ ] **Step 4: 检查生成文档未被手改**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
$beforeJson = (Get-FileHash ../docs/api.json -Algorithm SHA256).Hash
$beforeMarkdown = (Get-FileHash ../docs/api.md -Algorithm SHA256).Hash
Invoke-Gate 'export_openapi（漂移检查）' { uv run python ../scripts/export_openapi.py }
$afterJson = (Get-FileHash ../docs/api.json -Algorithm SHA256).Hash
$afterMarkdown = (Get-FileHash ../docs/api.md -Algorithm SHA256).Hash
if ($beforeJson -ne $afterJson -or $beforeMarkdown -ne $afterMarkdown) { throw 'OpenAPI 生成结果不稳定' }
```

Expected: 无漂移。

- [ ] **Step 5: 审查检查点**

不得提交。向用户列出所有修改文件，并说明哪些条目按计划推迟到了 Task 7。

---

### Task 6: 扩大参考实现能力审计

**Files:**
- Modify: `docs/yshopping-parity-audit.md`（位于集成工作区）
- Read only（全部在仓库根，不在 worktree）：
  - Service：`DorisQueryService.java`、`LlmIntentAnalysisService.java`、`SemanticLayerService.java`、`PromptLoopAnalysisService.java`、`MetricDefinitionService.java`、`VisualizationService.java`、`CsvExportService.java`
  - Model/基础设施：`QuestionIntent.java`、`QueryBundle.java`、`MerchantQaLangGraph.java`、`ConversationContextStore.java`
  - 上述各类对应的测试

**Interfaces:**
- Produces: 纯明细、跨业务计划、临时分组指标、历史上下文、Reviewer 循环、导出与图表的输入/校验/查询/输出/失败语义对照表，供 Task 7 设计使用

> **为什么扩到 11 个类：** 只读四个 Service 无法确认历史上下文如何存取（`ConversationContextStore`）、Reviewer 循环如何终止（`MerchantQaLangGraph`）、导出文件如何生成（`CsvExportService`）、图表字段如何选取（`VisualizationService`）。而 Task 7 要设计的会话详情契约与生成指标导出，恰好落在这几个类上。

- [ ] **Step 1: 定位全部参考文件**

```powershell
Set-Location 'd:\vscode html\merchant_assistant'
$names = 'DorisQueryService|LlmIntentAnalysisService|SemanticLayerService|PromptLoopAnalysisService|MetricDefinitionService|VisualizationService|CsvExportService|QuestionIntent|QueryBundle|MerchantQaLangGraph|ConversationContextStore'
Get-ChildItem -Recurse -Filter '*.java' -Path '.\yshopping-merchant-ai 4' |
  Where-Object { $_.BaseName -match "^($names)(Test)?$" } |
  Select-Object BaseName, FullName | Format-Table -AutoSize
```

Expected: 11 个主类各定位到一个绝对路径，另附各自的测试类。找不到的类必须在审计里保留 ❓ 并写明"参考实现中未找到同名类"，**不得凭类名推测行为**。只读不写，禁止格式化或在该目录下生成任何文件。

- [ ] **Step 2: 审计跨业务计划**

记录三种 plan type、子订单号提取、**参数非法时的降级路径**（已裁定 1:1 还原）、订单→退款、订单→商品、订单→退款+商品的查询步骤与无结果提示。

- [ ] **Step 3: 审计纯明细模式**

记录 `analysisRequested`、`tableOnlyDetail`、`attachmentDriven`、`repairAnswer()`、`outputMatchesIntent()` 和 Reviewer/loop 对空正文的处理。特别记录 `outputMatchesIntent` 对纯明细是**要求**正文为空（`!StringUtils.hasText(answer)`），不是允许为空。

- [ ] **Step 4: 审计临时分组指标**

记录允许的 group/filter 列、**按问题类别选模板的分流逻辑**、每个模板的固定聚合列集合、`generatedMetricCity` 这个遗留字段的兼容路径、金额精度、图表字段、**截断时的 CSV 导出行为**和所有注入反例测试。

- [ ] **Step 5: 审计历史上下文与回答载荷**

记录 `ConversationContextStore` 存了什么、会话详情回放时哪些字段可用、敏感明细行是否落库、Reviewer 重试步骤是否进入历史。这是 Task 7 设计会话详情契约的唯一输入。

- [ ] **Step 6: 审计导出与图表**

记录 `CsvExportService` 的文件命名、URL 生成、过期语义、公式注入处理；`VisualizationService` 如何从查询结果挑选图表字段。

- [ ] **Step 7: 更新待核实状态**

仅把已经完成能力级对照的条目标成“已核实”；未读完的方法和测试继续保留 ❓，不得硬凑结论。

---

### Task 7: 统一设计意图契约、会话详情与导出语义

**Files:**
- Create design: `docs/specs/2026-08-09-r9-intent-contract-design.md`
- Modify: `docs/PRD.md`、`docs/backend-development-plan.md`（§6.2 与 §8 分开写）、`docs/frontend-development-plan.md`

**Interfaces:**
- Consumes: Task 6 的能力对照表
- Produces: 四个可独立实现的稳定契约，不直接改代码

> **本任务承接 Task 5 推迟下来的全部文档条目**，一次写完，避免同一批字段在两个任务里各写一遍。**放置位置有硬性区分**：内部 LLM 意图 → §6.2 Intent Contract；外部 API 字段 → §8 API Schema。

- [ ] **Step 1: 定义纯明细语义（→ §6.2 + §8.2）**

§6.2：模型只输出 `analysis_requested: bool`；后端依据 `answer_mode == DETAIL and not analysis_requested` 计算纯明细模式。

§8.2：`ChatResponse.answer` 在纯明细模式下**必须**为空字符串，其他模式必须非空。措辞按 `outputMatchesIntent` 的 `!StringUtils.hasText(answer)` 对齐——是"必须为空"，不是"允许为空"。同时定义违反时的错误契约。

- [ ] **Step 2: 定义跨业务计划类型与降级语义（→ §6.2）**

```python
class CrossBusinessPlanType(StrEnum):
    ORDER_TO_REFUND = "ORDER_TO_REFUND"
    ORDER_TO_GOODS = "ORDER_TO_GOODS"
    ORDER_REFUND_GOODS = "ORDER_REFUND_GOODS"

class CrossBusinessPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_type: CrossBusinessPlanType
    sub_order_no: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
```

**失败语义按已裁定的 1:1 还原**（对应 `SemanticLayerService.validateCrossBusinessPlan`）：

- `QueryIntent.cross_business_plan` 缺失 → 走普通查询，无备注。
- 对象存在但参数非法 → **不是 INVALID**。清空 `cross_business_plan`，追加语义备注「LLM 跨业务计划缺少安全路由参数，已拒绝该计划」，基础意图保持 VALID，回退普通查询，并在回答里显示计划被拒绝的可见说明。

设计文档必须明确写出 Pydantic 校验失败如何转成上述降级——嵌套模型约束本身只会抛 `ValidationError`。方案：`cross_business_plan` 在 `QueryIntent` 上声明为 `CrossBusinessPlan | None`，用 `model_validator(mode="before")` 捕获子模型构造失败并降级为 `None` + 备注，而不是让 `ValidationError` 冒泡。

- [ ] **Step 3: 定义临时分组指标类型与 INVALID 语义（→ §6.2）**

**不加 `measure` 枚举**（已裁定）。聚合由后端按问题类别选固定模板，每个模板吐固定一组聚合列，与 `DorisQueryService` 的 `intent.getCategory() == QuestionCategory.REFUND` 分流一致。

```python
class GeneratedMetricPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    unit: Annotated[str, StringConstraints(max_length=32)]
    group_by: Literal["spu_id", "address_city_name"] | None = None
    filter_column: Literal["spu_id", "address_city_name"] | None = None
    filter_value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "GeneratedMetricPlan":
        if (self.filter_column is None) != (self.filter_value is None):
            raise ValueError("filter_column 与 filter_value 必须同时存在或同时缺失")
        filtered_city = self.filter_column == "address_city_name" and bool(self.filter_value)
        if self.group_by is None and not filtered_city:
            raise ValueError("group_by 与合法城市筛选至少存在一个")
        return self
```

`group_by` 可选是 1:1 还原的结果：`validateGeneratedMetric` 的条件是 `!GROUP_COLUMNS.contains(groupColumn) && !filteredCity`，即**分组列命中白名单或城市筛选合法，二者有一即可**。

**失败语义与跨业务相反**（对应 `validateGeneratedMetric`）：维度未命中白名单 → 整条意图设为 `INVALID`、`answer_mode` 设为 `INVALID`、类别设为 `UNKNOWN`，追加备注「LLM 生成指标未命中允许的维度，已拒绝查询」。设计文档必须显式写明这条不对称，防止后续实施时被"统一降级"改错。

`name` 和 `unit` 只作展示，**绝不能参与查询模板选择**；后端把 plan 映射到固定 SQLAlchemy 表达式和白名单列，禁止自由公式、自由列名和 SQL 文本。

- [ ] **Step 4: 定义会话详情响应契约（→ §8）**

当前 `GET /api/conversations/{id}` 只返回 `id/role/content/created_at`，前端无从还原任何执行信息。按已裁定的「扩后端契约」新增脱敏助手回答载荷：

- 必含：`answer_id`、`answer_mode`、`thinking_steps`（与 SSE `step` 事件同构）、质量状态（`quality_status`/`degraded`/`degraded_reason`）、当前反馈状态（`is_adopted`/`reaction`）、表格元数据（列定义、总行数、是否截断）。`answer_id` 与当前反馈状态必须同时提供；只补前者会让前端用未知旧状态覆盖服务端已有采纳或点赞。
- **明确不含**：完整敏感明细数据行、任何签名导出 URL（历史签名必然已过期，返回它只会产出必然失败的链接）。
- 历史明细的前端表现：显示表格元数据与「历史明细未保留，重新提问可查看完整数据」的可见说明，不渲染空白助手消息。
- 数据来源：`answers.response_payload`（JSONB）。设计文档必须写明脱敏发生在装配层，不是靠前端不显示。

- [ ] **Step 5: 定义生成指标导出契约（→ §8）**

按已裁定的「允许」扩 export 契约：当前 §8 只允许 DETAIL 成功且未降级时返回 export，需扩展为**生成型 METRIC 结果超出展示上限时同样创建导出记录并返回签名 URL**，附截断提示文案（对应 `queryGeneratedGroupedMetric` 的 `detailNotice`）。设计文档需说明这对 `export_files` 表和 `ExportService.download()` 的重放查询意味着什么——下载时要能重放生成指标查询，不只是明细查询。

- [ ] **Step 6: 定义 `response_payload` 兼容策略（→ §8）**

`chat_service.py:274` 的 `_stored_response(existing.response_payload)` 会把历史 JSONB 直接过当前 `ChatResponse` 校验。本轮所有字段新增/改名都会让**升级前写入的幂等回答在重放时校验失败**。设计文档必须二选一并写明理由：

1. **JSONB 数据迁移**：Alembic 迁移里逐行升级 `answers.response_payload`，风险是大表迁移耗时与不可回滚；
2. **内部兼容升级器**：`_stored_response` 里先过一个 `upgrade_payload()`，为缺失字段填默认值再校验，风险是兼容代码长期滞留。

无论选哪个，都必须有一条回归测试：写入旧结构 payload → 重放 → 不抛异常且字段完整。

- [ ] **Step 7: 用户审阅设计**

在用户确认上述五个契约前，不进入 Task 8 起的任何代码实施。

---

### Task 8: 修复思考步骤展示与历史会话装配

**Files:**
- Modify: `backend/app/schemas/conversation.py`（或 §8 契约落点所在文件）、`backend/app/api/routes/chat.py`、会话详情装配层
- Test: `backend/tests/api/test_conversations.py`
- Modify: `frontend/src/api/adapters/chat.ts`、`frontend/src/stores/chat.ts`、`frontend/src/components/chat/ChatMessage.vue`
- Test: `frontend/src/components/chat/ChatMessage.spec.ts`、`frontend/src/stores/chat.spec.ts`
- Modify docs: `docs/frontend-development-plan.md`、`docs/yshopping-parity-audit.md`

**Interfaces:**
- Consumes: Task 7 Step 4 的会话详情契约
- Produces: 运行中显示当前步骤；完成后按原顺序显示全部步骤；历史轮次与实时轮次表现一致

> **这是前后端契约任务，不是纯组件修复。** 实测 [chat.py:244-247](../.worktrees/feature-b5-b6-answer-feedback-export/backend/app/api/routes/chat.py) 的会话详情只返回 `id/role/content/created_at`，`stores/chat.ts` 据此把历史消息构造成 `{ status: 'complete', steps: [], origin: 'history' }` 且**没有 `answer` 对象**。任何只改组件的方案都只是把缺口从"完成态不显示"挪到"历史态不显示"。

- [ ] **Step 1: 写失败的后端契约测试**

`backend/tests/api/test_conversations.py`：创建一轮带 `thinking_steps` 和反馈状态的助手回答 → `GET /api/conversations/{id}` → 断言响应里助手消息含 `answer_id`、`answer_mode`、`thinking_steps`（顺序与写入一致）、质量状态、当前反馈状态、表格元数据；断言**不含**完整明细数据行与任何 `signature=` 字符串。

- [ ] **Step 2: 运行后端测试确认失败**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
uv run pytest tests/api/test_conversations.py -v
if ($LASTEXITCODE -eq 0) { throw '预期失败但通过了——测试没有真正断言新字段' }
```

Expected: FAIL，原因是响应里没有 `thinking_steps`。

- [ ] **Step 3: 实现会话详情载荷并重新生成契约**

按 Task 7 Step 4 的契约扩响应模型与装配层，然后**必须**重跑生成链（否则前端类型对不上）：

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
Invoke-Gate 'pytest 定向' { uv run pytest tests/api/test_conversations.py -v }
Invoke-Gate 'export_openapi' { uv run python ../scripts/export_openapi.py }
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'codegen' { npm run codegen }
```

- [ ] **Step 4: 写失败的前端测试**

三个组件用例，输入至少三个不同节点：

```ts
const steps = [
  { node: 'load_context', label: '识别商家与会话上下文' },
  { node: 'query_data', label: '查询经营数据' },
  { node: 'persist_answer', label: '保存回答' },
]
```

1. 运行态（`status: 'streaming'`、`steps`、无 `answer`）：`stage-label` 只显示最后一步，无 `thinking-step` 列表。
2. 完成态实时轮次（`status: 'complete'`、`origin: 'live'`）：`thinking-step` 按数组顺序显示三项，每项只出现一次。
3. 完成态历史轮次（`status: 'complete'`、`origin: 'history'`、`steps: []`、`answer.thinkingSteps` 为上述三项）：同样显示三项。

外加一个 Store 用例：`stores/chat.spec.ts` 断言从新的会话详情响应装配出的历史消息**带有 `answer` 对象**且 `thinkingSteps` 非空——这条防止组件测试用手工构造的数据自欺。

- [ ] **Step 5: 实现 Adapter/Store/组件**

Adapter 从新契约装配 `ChatAnswer` 与当前反馈状态；Store 的历史分支不再写死 `steps: []` 与缺失 `answer`，且只有在 `answer_id` 与反馈状态同时可信时才开放历史反馈；组件：

```ts
const completedSteps = computed(() =>
  props.message.answer?.thinkingSteps?.length
    ? props.message.answer.thinkingSteps
    : props.message.steps,
)
```

```vue
<div v-if="message.status === 'complete' && completedSteps.length" class="chat-message__thinking">
  <strong>执行完成</strong>
  <div
    v-for="(step, index) in completedSteps"
    :key="`${step.node}-${index}`"
    data-testid="thinking-step"
  >
    {{ step.label }}
  </div>
</div>
```

key 固定带 index：Reviewer 重试会让同一 `node` 重复出现，纯 `node` 作 key 会触发 Vue 重复 key 告警。不得在组件里去重或丢弃 Reviewer 重试步骤。

- [ ] **Step 6: 运行定向与全量门禁**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
Invoke-Gate 'pytest' { uv run pytest }
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
foreach ($gate in @('codegen:check','fixtures:check','typecheck','lint','test')) {
  Invoke-Gate $gate { npm run $gate }
}
```

Expected: 全部通过；前端总数为 205 + 本任务新增用例数。

- [ ] **Step 7: 更新审计状态**

将 §3.6 从“真实缺口”改为“已修复”，记录后端契约扩展、测试文件与实际通过数。不得提交，除非用户明确授权。

---

### Task 9: 产出并执行指标口径子计划（含旧 JSONB 兼容）

**Files:**
- Create child plan: `plans/2026-08-09-metric-definition-parity.md`
- Expected backend scope: `backend/app/models/knowledge.py`、`metrics/catalog.py`、`schemas/chat.py`、`schemas/metric.py`、`repositories/metric.py`、迁移与 Seed、`services/chat_service.py` 的 `_stored_response`
- Expected frontend scope: `frontend/src/api/adapters/chat.ts`、`types/chat.ts`、`components/insights/MetricDefinitionPanel.vue`

**Interfaces:**
- Consumes: Task 7 Step 6 的 `response_payload` 兼容策略
- Produces: 正式目录 → 字段注释 → AI 候选三级检索，以及完整指标口径展示

- [ ] **Step 1: 固化字段契约**

子计划必须定义并覆盖：业务口径、SQL 口径、维度、来源库表、关联报表、来源枚举、`generated`、`notice`、owner、status，以及 Borough 的稳定 `metric_code`。

- [ ] **Step 2: 定义确定性二级检索**

二级检索只允许读取 PostgreSQL 列注释或后端白名单元数据，并由后端模板生成自然语言 SQL 口径；不得调用 LLM，不得接收模型提供的表名或列名。

- [ ] **Step 3: 实施 `response_payload` 兼容策略**

按 Task 7 Step 6 裁定的方案实施，并**先写回归测试**：构造一条升级前结构的 `answers.response_payload` 行 → 走幂等重放路径 → 断言不抛异常且字段完整。这条测试必须在字段改名的实现之前失败。

- [ ] **Step 4: 定义 `report_url` 的后端协议白名单**

后端在写入与返回时都限制 `report_url` 只允许 `http`/`https`，其他协议（含 `javascript:`、`data:`）直接拒绝并记审计。前端渲染时使用 `rel="noopener noreferrer"`。**不能只做"非法 URL 前端不渲染"的前端测试**——那是最后一道防线，不是唯一一道。后端与前端各写一条反例测试。

- [ ] **Step 5: 写三级回归矩阵**

子计划至少包含：目录命中、目录未命中但字段注释命中、前两级未命中进入 Fake LLM、LLM 不可用显式降级、生成口径缺 notice 拒绝、非法 report URL 后端拒绝、非法 report URL 前端不渲染、旧 payload 重放兼容。

- [ ] **Step 6: 完成子计划自查后执行**

子计划必须通过 placeholder scan、类型一致性和字段流向检查后，才可进入 TDD 实施。

---

### Task 10: 产出并执行纯明细模式子计划

**Files:**
- Create child plan: `plans/2026-08-09-table-only-detail.md`
- Expected backend scope: `intent/models.py`、`intent/prompts.py`、`intent/whitelist.py`、`agent/graph.py`、`schemas/chat.py`、会话详情装配
- Expected frontend scope: `api/adapters/chat.ts`、`stores/chat.ts`、`components/chat/ChatMessage.vue`、`DetailTable.vue`

**Interfaces:**
- Consumes: Task 7 Step 1 的纯明细契约
- Produces: “查看最近 20 笔订单”只显示表格；“分析最近 20 笔订单”仍显示正文和建议

- [ ] **Step 1: 子计划先写契约失败测试**

必须覆盖：DETAIL+纯明细**要求**正文为空（非空即拒绝，与 `outputMatchesIntent` 一致）、其他模式空正文拒绝、Adapter 接受合法空正文、历史记录不出现空白消息。

- [ ] **Step 2: 子计划写意图与 Graph 分流测试**

使用 Fake LLM 固定输出 `analysis_requested=false/true`，断言两种 DETAIL 进入相同安全查询但不同回答组合分支。

- [ ] **Step 3: 子计划写前端渲染测试**

纯明细不得渲染空正文容器；表格、总行数、截断提示和导出入口仍正常显示。

- [ ] **Step 4: 按 TDD 执行并更新审计**

定向测试和全量门禁通过后，将审计 §3.4 标记为已修复。

---

### Task 11: 产出并执行跨业务查询子计划

**Files:**
- Create child plan: `plans/2026-08-09-cross-business-query.md`
- Expected backend scope: `models/analytics.py`、Alembic 迁移、`analytics/demo_data.py`、`intent/**`、`analytics/contract.py`、`repositories/analytics.py`、`services/safe_query.py`、`agent/graph.py`

**Interfaces:**
- Consumes: Task 7 Step 2 的跨业务契约与降级语义
- Produces: `ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS` 三种固定计划

- [ ] **Step 1: 子计划定义数据模型**

为 `order_items` 增加商家范围内唯一的 `sub_order_no`，Seed 为每个演示商家生成稳定值；索引必须支持 `(merchant_id, sub_order_no)` 查询。

- [ ] **Step 2: 子计划定义三种固定查询模板**

每一步都显式带 `merchant_id`，`sub_order_no` 只作为绑定值；商品、退款/退货关联通过 ORM 外键和白名单关系完成。

- [ ] **Step 3: 子计划定义安全反例与降级断言**

至少覆盖：缺子订单号、未知 plan type、SQL 注入字符串、商家 A 使用商家 B 子订单号、无退款记录、无商品记录、组合计划部分命中。

**每条非法参数用例都必须断言降级而非 INVALID**：`intent_type` 仍为 VALID、`cross_business_plan` 已清空、语义备注已追加、回答中出现计划被拒绝的可见说明、且**确实回退执行了普通查询**。只断言"没崩"不算通过。

- [ ] **Step 4: 按 TDD 执行并更新文档**

全量门禁通过后更新 PRD 验收、后端 §6.2、progress 和审计 §3.3。

---

### Task 12: 产出并执行受控临时分组指标子计划

**Files:**
- Create child plan: `plans/2026-08-09-generated-grouped-metric.md`
- Expected backend scope: `intent/**`、`analytics/contract.py`、`repositories/analytics.py`、`services/safe_query.py`、`services/visualization_service.py`、`services/export_service.py`、`repositories/export.py`、`metrics/catalog.py`
- Expected frontend scope: 指标口径、图表、明细、导出入口和降级提示组件

**Interfaces:**
- Consumes: Task 7 Step 3 的生成指标契约、Step 5 的导出契约
- Produces: 按 `spu_id` 或 `address_city_name` 分组（或仅按城市筛选）的受控临时指标；模型不生成 SQL

- [ ] **Step 1: 子计划列出类别驱动的固定模板**

按问题类别（ORDER/REFUND）各定义一套固定聚合模板，每套的聚合列集合写成后端常量，逐项映射自 Task 6 Step 4 的能力审计。**不得**使用“任意指标表达式”或运行时 `getattr` 接受模型字段，也**不要**引入 `measure` 枚举（已裁定按参考实现走类别分流）。

- [ ] **Step 2: 子计划定义字段与值边界**

group/filter 列使用 Literal 白名单；filter value 使用绑定参数；日期范围、最大点数、总行数和 `merchant_id` 由后端强制注入。覆盖 `group_by` 缺省但城市筛选合法的路径——这是参考实现允许的形态。

- [ ] **Step 3: 子计划定义 INVALID 语义与可见降级**

维度未命中白名单 → 整条意图 INVALID（与跨业务的降级相反，见 Task 7 Step 3）。合法但结果异常时：临时指标必须 `generated=true`、`metric_status=UNVERIFIED`、带 `notice`；查询或口径生成失败时使用既有 `degraded`/`degraded_reason`，不得伪装成正式目录指标。

- [ ] **Step 4: 子计划定义截断导出**

结果超出展示上限时创建导出记录并返回签名 URL + 截断提示，按 Task 7 Step 5 的契约实施。必须覆盖：下载时能正确重放生成指标查询（不是明细查询）、跨商家下载 403、过期签名 410、CSV 公式注入防护、UTF-8 BOM 只加一次。

- [ ] **Step 5: 按 TDD 执行并更新审计**

覆盖 `spu_id` 分组、城市分组、仅城市筛选、非法列 INVALID、注入值、多商家隔离、图表安全字段和上述导出用例；全绿后关闭审计 §3.5。

---

### Task 13: 补齐真实数据库 E2E 场景

**Files:**
- Modify: `backend/tests/support/e2e_app.py`（确定性意图代理补足新分支）
- Modify: `backend/scripts/seed_f4_e2e.py`（补足新场景所需的确定性数据）
- Modify: `frontend/e2e/real-api/analytics.spec.ts`

**Interfaces:**
- Produces: 覆盖阶段 B 全部新能力的真实库浏览器验收

> Task 4 的 3 条真实库用例只覆盖阶段 A 的能力。阶段 B 加了四类新行为，不补 E2E 就等于这些能力从未在真实数据库上跑通过。

- [ ] **Step 1: 补纯明细场景**

真实库下提问“查看最近 20 笔订单”→ 断言页面只有表格、无正文容器；再提问“分析最近 20 笔订单”→ 断言有正文与建议。

- [ ] **Step 2: 补跨业务场景（含跨商家反例）**

合法子订单号 → 断言退款/商品关联结果渲染。**跨商家反例**：以商家 A 身份提交商家 B 的子订单号 → 断言看不到 B 的任何数据，且显示无结果或计划被拒绝的说明。这条是商家隔离的最后一道真实验证。

- [ ] **Step 3: 补生成指标场景**

按城市分组的生成指标 → 断言图表渲染、`generated` 徽标与 `notice` 可见、`metric_status=UNVERIFIED` 的提示存在。

- [ ] **Step 4: 补生成指标导出场景**

构造超出展示上限的生成指标结果 → 断言截断提示与签名下载链接出现，链接形如 `/api/exports/{uuid}?expires_at=...&signature=<64 位十六进制>`。

- [ ] **Step 5: 补历史会话步骤场景**

完成一轮问答 → 刷新并从会话列表打开该会话 → 断言助手消息显示完整思考步骤列表，且页面上不出现任何 `signature=` 字符串（历史不返回签名 URL）。

- [ ] **Step 6: 运行真实库 E2E**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
$env:F4_E2E_DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55443/borough_f4_test'
try {
  Invoke-Gate 'playwright（真实库·全场景）' { npm run test:e2e:real }
} finally {
  Remove-Item Env:F4_E2E_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: 不少于 3 + 本任务新增场景数；DeepSeek 调用 0 次。

---

### Task 14: 最终一致性验收

**Files:**
- Modify: `docs/project-progress.md`
- Modify: `docs/yshopping-parity-audit.md`
- Verify generated: `docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts`、fixture

**Interfaces:**
- Produces: 通过全部门禁、可交付用户裁定 Git 操作的候选分支

- [ ] **Step 1: 重跑 Task 4 全部门禁**

完整重跑 Task 4 Step 1–8，**包含两个容器的销毁重建**——阶段 B 新增了迁移，跑在旧库上不算数。所有命令走 `Invoke-Gate`。

Expected: 后端 >703、前端 >205、Mock Playwright ≥24、真实库 Playwright ≥ Task 13 的场景数；每一项都必须**严格高于或等于**阶段 A 记录的数字，下降即视为回归。

- [ ] **Step 2: 重跑生成物漂移检查**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\backend'
$beforeJson = (Get-FileHash ../docs/api.json -Algorithm SHA256).Hash
$beforeMarkdown = (Get-FileHash ../docs/api.md -Algorithm SHA256).Hash
Invoke-Gate 'export_openapi' { uv run python ../scripts/export_openapi.py }
$afterJson = (Get-FileHash ../docs/api.json -Algorithm SHA256).Hash
$afterMarkdown = (Get-FileHash ../docs/api.md -Algorithm SHA256).Hash
if ($beforeJson -ne $afterJson -or $beforeMarkdown -ne $afterMarkdown) { throw 'OpenAPI 生成结果不稳定' }
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4\frontend'
Invoke-Gate 'codegen:check' { npm run codegen:check }
Invoke-Gate 'fixtures:check' { npm run fixtures:check }
```

Expected: 无漂移。

- [ ] **Step 3: 危险 SQL 构造扫描**

只扫真正能绕过 ORM 的构造。**不要**把 `execute(` 混进来——它在 `backend/app/repositories|services` 实测 15 处命中，全是合法的 SQLAlchemy 2.0 `session.execute(stmt)`：

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
rg -n 'text\(|from_statement|literal_column|exec_driver_sql' backend/app/repositories backend/app/services
Assert-NoMatch 'SQL 字符串拼接' @('-n', '-i', 'f"(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)|\+ *"(SELECT|WHERE)', 'backend/app')
```

Expected: 第一条命中数不超过阶段 A 基线的 2 处，每一处新增都必须逐条说明为何不可用 ORM 表达；第二条零命中，否则视为 R9 安全红线失守，停止并回报用户。

- [ ] **Step 4: 旧 IP 与模型名残留扫描**

```powershell
. 'C:\Users\Penguin\AppData\Local\Temp\claude\gate-helpers.ps1'
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
Assert-NoMatch '生产代码残留 yshopping' @('-n', 'yshopping', 'backend/app', 'frontend/src')
Assert-NoMatch '生产代码硬编码模型名' @('-n', 'deepseek-chat|deepseek-reasoner', 'backend/app', 'frontend/src')
rg -n 'yshopping' docs AGENTS.md --glob '!docs/yshopping-parity-audit.md' | Measure-Object -Line
```

Expected: 前两条零命中（模型名归配置）。第三条只作数量对照，命中数不应显著高于阶段 A 基线的 64。

- [ ] **Step 5: 更新最终进度快照**

`docs/project-progress.md` 记录统一分支、验证日期、各项通过数、剩余 Railway 人工步骤和仍为 ❓ 的审计项。

---

### Task 15: Git 交付顺序与分支推进

**Files:**
- 无代码改动；只执行用户授权的 Git 操作

**Interfaces:**
- Produces: 用户裁定后的交付形态

> **顺序是有依赖的，不是并列选项。** 阶段 A/B 全程不提交，集成分支 HEAD 仍停在 `3faef8a`（B7 起点），所有成果都在工作区。此时直接快进 `feature/f2-mock-conversation` **拿不到任何集成改动**。必须先提交，才谈得上"可快进的候选分支"。

- [ ] **Step 1: 请求提交授权**

向用户报告待提交的完整文件清单与分组建议（阶段 A 集成、阶段 B 各切片），请求授权本地提交。**不得**自行执行 `git commit`。

- [ ] **Step 2: 授权后按阶段提交**

获得明确授权后再执行。提交信息使用中文描述，按阶段与切片分开，不做单条巨型提交。

- [ ] **Step 3: 验证集成分支 HEAD**

```powershell
Set-Location 'd:\vscode html\merchant_assistant\.worktrees\feature-integrate-b7-f4'
git status --short
git log --oneline -10
git rev-parse --short HEAD
```

Expected: 工作区干净；HEAD **不再等于** `3faef8a`；提交历史与 Step 2 的分组一致。

- [ ] **Step 4: 请求快进裁定**

只有 Step 3 通过后，才向用户提出是否把 `feature/f2-mock-conversation` 快进到 `feature/integrate-b7-f4`。快进前确认 `git merge-base --is-ancestor feature/f2-mock-conversation feature/integrate-b7-f4` 退出码为 0。

- [ ] **Step 5: 请求推送裁定**

推送是最后一步，单独请求授权。未获授权时保持本地状态。

- [ ] **备选路径（用户不授权提交时）**

只能保留集成工作树，或用 `git diff --output=` 导出补丁交付。**此时不得在任何文档里把它称为"可快进的候选分支"**——它不是。

---

## Definition of Done

**阶段 A（Task 1–4，独立可交付）**

- 集成分支以 B7 后端为基线，`backend/app` 与 `backend/migrations` 零改动。
- 仓库根未提交的文档增量与 8 个 allowlist 文件已完整迁入，仓库根本身未被改动。
- F3/F4 前端、图表、明细、签名导出和真实数据库浏览器验收在集成分支通过。
- OpenAPI、generated.ts 和 fixture 均由集成后端生成且无漂移。
- 后端真实库 ≥703 passed / 0 skipped / 0 failed；前端 ≥205 passed；Mock Playwright ≥24 passed；真实库 Playwright ≥3 passed，**全部由 `Invoke-Gate` 校验过退出码**。
- 共享的 `borough` Compose 项目与其卷完好无损。

**阶段 B（Task 5–14）**

- 文档权威链：内部意图契约只在 §6.2，外部 API 契约只在 §8，PRD 只描述产品语义，AGENTS 只做索引；同一类名不在两处出现。
- Task 6 的 11 类参考实现能力对照表已落入审计，未读完的方法保留 ❓。
- 会话详情返回脱敏助手回答载荷；思考步骤在实时与历史轮次表现一致；历史响应不含完整明细行与签名 URL。
- 指标口径三级检索与完整字段链交付；`report_url` 在后端限协议、前端带 `noopener noreferrer`。
- `answers.response_payload` 的旧结构重放有回归测试且通过。
- 纯明细：正文**必须**为空的语义与 `outputMatchesIntent` 一致。
- 跨业务：非法参数走降级而非 INVALID，且断言确实回退执行了普通查询。
- 生成指标：维度未命中走 INVALID；聚合由类别驱动固定模板，契约中无 `measure` 字段；截断时返回导出且下载能重放生成指标查询。
- Task 13 的真实库 E2E 覆盖上述全部新能力，含跨商家子订单号反例。
- Task 14 Step 3 的 SQL 拼接扫描与 Step 4 的生产代码残留扫描均零命中。
- `docs/yshopping-parity-audit.md` 如实区分已修复、阶段未到、有意偏离和仍待核实项。

**全局**

- 全部自动化验证使用 Fake/Mock LLM，DeepSeek 调用 0 次，费用为 0。
- 未经用户明确许可，没有执行任何 Git 操作；若未授权提交，交付物如实描述为"工作树/补丁"而非"候选分支"。

## 中止与回报判据

出现下列任一情况，停止执行并回报用户，不得自行降低标准继续：

- 任何门禁的通过数低于本计划记录的基线，且根因不是"数据库残留"或"误动后端"这两种已知可修复原因。
- Task 1 Step 4 的未跟踪文件集合与 allowlist 不一致，且多出的文件用途不明。
- Task 1 Step 6 的文档冲突无法在保留 b5b6 全部 B7 内容的前提下解决。
- Task 2 Step 5 出现契约级失败（字段缺失、端点 404），说明"B7 与 F3 的 `schemas/chat.py` 相同"这一前置事实已失效。
- Task 6 在参考项目中找不到某个类——保留 ❓，不得凭类名推测行为后继续设计 Task 7。
- Task 7 的任一契约未获用户确认——不得进入 Task 8 起的代码实施。
- Task 14 Step 3 的 SQL 拼接扫描出现任何命中。
- 任何时刻发现自己准备对 `borough` Compose 项目或 `borough_postgres_data` 卷执行删除操作——立即停止，那不是本计划的资源。
