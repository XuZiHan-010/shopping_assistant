# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。每次完成一段可验证工作后，更新日期、状态、验证结果、下一步和风险。

**最后更新：2026-08-12**

> **当前优先快照（2026-08-12，覆盖下方较早的集成与 F6 叙述）**：用户已裁定 `main` 为唯一主线；
> `feature/integrate-b7-f4` 是当前集成分支，已推送至 `origin/feature/integrate-b7-f4`，未创建 PR，
> 也未改动 `main`。阶段 0 的静态门禁与独立空 PostgreSQL 库实测已完成：后端
> `ruff check`、`ruff format --check`、`mypy app` 全绿；前端 Vitest **245 passed**、lint、格式、
> codegen/fixture/mock/密钥/首屏门禁、类型检查和构建全绿；独立空库
> `borough_stage0_20260812_test` 上真实数据库 pytest **717 passed / 0 failed / 1 条第三方警告**。
> DeepSeek 调用 **0**、费用 **0**。旧 `borough_test` 的 Alembic 版本 `20260808_0005` 不属于当前迁移图，
> 因此未删除该持久库。现正执行 R9 阶段 B 的 Task 5–7：文档事实校正、参考能力审计与契约设计；
> **R9 阶段 B Task 8 已完成（2026-08-12，待本轮提交）**：会话详情已为助手消息返回脱敏
> `answer_payload`（回答 ID、模式、完整步骤、质量状态/备注、当前反馈和表格元数据），严格不返回明细行、
> 导出 URL 或签名。完成态实时与历史回答都按原顺序展示全部步骤；历史明细只展示元数据并引导重新提问。
> 后端真实 PostgreSQL 全量回归 **718 passed / 0 failed / 1 条第三方警告**；前端完整 Vitest
> **26 文件 / 249 passed**，类型检查、lint、格式、OpenAPI codegen 与 fixture 检查均通过。全程
> DeepSeek 调用 **0**、费用 **0**。下一步是 R9 Task 9：先产出并审阅指标口径子计划，再开始该切片代码。

> **当前集成验收快照（2026-08-11，优先于下方历史阶段摘要）**：B7 + F4 集成工作已在
> `feature/integrate-b7-f4` 完成**并提交**（`3faef8a`…`ac042a0`），**尚未推送到
> `origin`**。仓库根工作目录当前直接签出该分支（不再是独立 worktree）；
> `.worktrees/feature-b5-b6-answer-feedback-export` 与
> `.worktrees/feature-f3-real-api-integration` 仍各自保留，供比对但不再是主线。
> 集成验收当时（2026-08-10）的实测数字：后端在专用 PostgreSQL（55442）上为
> **707 passed / 0 skipped / 1 个第三方弃用警告**；非数据库路径为 **591 passed / 116 skipped /
> 1 warning**。`ruff check`、`ruff format --check` 与获批的 `mypy app`（88 个源文件）均通过。
> 前端 lint、格式、OpenAPI/fixture/mock 边界、类型检查、构建均通过，Vitest 为
> **206 passed**，Mock Playwright 为 **24 passed**，专用 F4 真实 API Playwright 为 **3 passed**。
> 全程使用 Fake/确定性 LLM 覆盖，DeepSeek 调用 **0**、费用 **0**；仅使用
> `borough-int-postgres`（55442）与 `borough-int-f4-postgres`（55443），未操作共享 Compose
> 或 `borough_borough_postgres_data`。后续类型债务为 `tests/`/`scripts/` 的 103 项既有 Mypy
> 错误（32 个文件）；ECharts 仍有非阻塞的 556.46 kB chunk-size 提示。
>
> **集成完成之后（2026-08-10 起）**：
> 1. 按 `AGENTS.md` R10，`docs/superpowers/plans/`（10 份）与 `docs/superpowers/specs/`
>    （13 份）迁至 `plans/` 与 `docs/specs/`，`docs/superpowers/` 已删除，交叉引用已修复
>    （提交 `40cb282`）。
> 2. 未等待用户就集成整改计划「阶段 B」（R9 差异整改，Task 5–15）表态，转而开始下一个
>    前端 MVP 阶段 **F5「质量轨迹、反馈与无障碍基础」**：设计说明
>    `docs/specs/2026-08-10-frontend-f5-design.md` 首版已提交（`caca1e9`），经第一轮评审后的
>    修订版与实施代码已于 2026-08-12 追加提交（`414d267`）。F5 已按 TDD 实现并完成前端门禁：
>    Vitest **238 passed**、Mock Playwright **25 passed**；lint、格式、OpenAPI/fixture/mock
>    边界、类型检查和构建均通过。DeepSeek 调用 **0**、费用 **0**。
> 3. 集成整改计划（`plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`）的 SDD 账本
>    （`.superpowers/sdd/2026-08-09-b7-f4-integration-and-r9-remediation/progress.md`）只记
>    到 Task 4（阶段 A 出口）；Task 5–15（阶段 B）未开工。
> 4. **计划勾选状态已对齐（2026-08-11）**：该计划正文此前 94 个 step 全部未勾选，与实际进度脱节。
>    已按 SDD 账本、逐 Task 报告与 Git 提交回填——阶段 A（Task 1–4 及执行期追加的 Task 3.5）共 35 项
>    勾为完成，阶段 B 的 62 项保持未勾。计划开头新增「执行状态」一节，记录阶段 A 的四个提交
>    （`b32fe99`、`cd4b75d`、`e2c9829`、`ac042a0`）、出口实测数字，以及四项偏离：集成 worktree 已移除
>    改在仓库根、追加 Task 3.5、`mypy` 门禁经批准收窄为 `app`（`tests/`+`scripts/` 103 项类型债务未还）、
>    `gate-helpers.ps1` 曾被 PowerShell 执行策略拦下。阶段 A 出口要求的「停下来向用户汇报」当时被跳过，
>    已于 2026-08-11 补上。
> 5. **进入前端 F6「Railway 部署就绪」（2026-08-11 起，2026-08-12 更新）**：用户已决定在 F5 之后
>    直接推进 F6，而不是先返回阶段 B。按 `plans/2026-08-11-frontend-f6-railway-mvp-closeout.md`
>    （对应设计说明 `docs/specs/2026-08-11-frontend-f6-design.md`），计划拆成 F6-0（两个后端前置
>    切片）→ F6-A（纯前端与构建配置，本地可完成）→ F6-B（依赖用户在 Railway 控制台操作）共 12 个
>    Task。**Task 1–7（F6-0 全部 + F6-A 本地收口）已完成，并于 2026-08-12 分别提交为
>    `d0dcace`（F6-0）与 `49fadc4`（F6-A）**：Task 1 显式演示部署模式
>    （`demo_deployment_mode` 配置项 + 运维状态字段）；Task 2 修正未配置 LLM 客户端时仍会预扣预算
>    的缺陷；Task 3 用生产构建 + preview 复现「ECharts chunk 出现在首屏请求」的红灯证据；Task 4 用
>    显式 `chartMountable` 挂载开关把 ECharts 移出首屏，并把静态门禁增强为三层检查；Task 5 生产
>    构建 Mock 硬防线；Task 6 前端 `railway.json` 与构建产物密钥扫描。全程零 DeepSeek 调用、零费用。
>    **F6 的 SDD 账本（`.superpowers/sdd/2026-08-11-frontend-f6-railway-mvp-closeout/progress.md`）
>    只记到 Task 4，Task 5/6 的完成状态目前只体现在各自的 `task-5-report.md`/`task-6-report.md`，
>    账本尚未回填**——核对 F6 真实进度时以逐 Task 报告为准，不要只看账本。
>
> Task 1–8 与 Task 12 已完成：F6 的代码、部署配置、部署手册和出口证据矩阵均已就绪；Task 9–11
> （Railway 控制台部署与两轮线上验收）仍完全待用户操作。详见
> `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md`：**前端 F0–F6 代码与文档已完成，Railway 部署就绪；
> Railway 尚未部署，MVP 尚未宣告完成。**

## 产品裁决：参考项目是需求基准（2026-08-09）

用户裁定本项目的目标是把 `yshopping-merchant-ai 4/` **1:1 还原**成 Python + TypeScript 版本；
当我们自己的 `docs/PRD.md` 或开发计划与参考项目实际实现冲突时，**改我们的文档去跟随参考项目**，
不得反过来用「PRD 没写」论证参考项目里存在的字段可以不做。规则已固化为 `AGENTS.md` R9。

首次适用是指标口径契约。差异审计结论：参考项目 `MetricDefinitionPayload` 有 13 个字段，
我们的 `MetricDefinitionResponse` 只兑现了 7 个。缺失项与处置：

| 参考项目字段 | 我们的状态 | 处置 |
| --- | --- | --- |
| `sqlMeaning`（SQL 口径） | 库里 `metric_definitions.sql_definition` 有真实值，但未出口到 API | 补字段 |
| `dimensions`（维度集合） | 完全没有 | 补字段（P1） |
| `reportUrl`（关联报表） | 完全没有，且前端计划曾写「不在契约内就删掉 UI」 | 补字段（P1），前端计划那句已删 |
| `databaseName` / `tableName`（来源库表） | 完全没有 | 补字段 |
| `generated`（是否模型生成） | 无，前端用 `status === 'UNVERIFIED'` 反推 | 补独立布尔字段 |
| `notice`（待核验文案） | 无，文案写死在前端 | 改为后端返回 |
| `source` 语义 | 我们是自由文本（"Borough 指标目录"），参考项目是枚举 | 改为 `METRIC_CATALOG` / `COLUMN_COMMENT` / `AI_GENERATED` |
| 三级降级检索 | `app/metrics/catalog.py` 只有两级，缺「字段注释」中间级 | 补第二级 |

我们比参考项目多出的 `metric_code`（稳定英文标识）与 `metric_status` 予以保留——参考项目没有稳定
指标标识是它的缺陷，不是需要还原的行为。

已同步修订：`AGENTS.md`（新增 R9）、`docs/PRD.md`（§6.3 补 3 条用户故事并说明双口径不可合并、
§10 Metric Catalog 补三级检索来源表、§11.3 按模式必填表拆分业务口径/SQL 口径、§12.1 演示数据要求；
新增故事导致原 19–67 号顺延为 22–70）、`docs/frontend-development-plan.md`（§5.6 接口定义与 F4
验收项按参考项目重写，删除「不展示报表」条款）、`docs/backend-development-plan.md`（§8.2 字段表、
必测项、B4 口径端点登记未完成项）。

**代码实现尚未开始。** 落点应为 `feature/b4-safe-analytics-query`（`/api/metrics/{code}` 与
`metric_definitions` 表都在该分支），改动链路：迁移加列 → Seed 补值 → `MetricDefinitionResponse` /
`MetricPayload` / `ChatResponse` 加字段并完成旧业务口径键的语义改名
→ 重跑 `codegen` 与 `fixtures` → 前端 `MetricDefinitionPanel.vue` 按参考项目版式还原。
注意 F4 已在 `feature/f3-real-api-integration` 上完成并提交，该前端改动会与其产生冲突，
需要先确定两个分支的合并顺序。

## 当前阶段

- 后端：**B4「安全经营数据查询」已收口并完成终审修复轮**，分支为 `feature/b4-safe-analytics-query`。Task 1–10 均已实现、复查并提交（Task 10 在 `72b2190`，REFUND 明细路由修复在 `7d28552`）。终审修复轮已提交（`b174bd9` 修掉 1 Critical + 6 Important，`50a28e6` 清理指向本阶段的过期文案并加机械防线）。
- 后端：**B5「回答、图表和 Reviewer」、B6「反馈与 CSV 导出」代码已完成并提交**，分支 `feature/b5-b6-answer-feedback-export`（提交 `7c60b12`/`18ba978`/`b494277`/`acc7efa`，2026-08-06）。之前这批工作只存在于本地 worktree 且未提交；本轮先修完 `ruff check`/`ruff format` 未通过的 10 处问题（都在下面提到的 B7 附带代码里），再按 Task 边界拆成 4 个提交落地。分支去向（合并/开 PR/保留）尚未决定。
- 后端：**B7「Railway、费用防护与 MVP 收口」代码层面已完成并提交**，分支 `feature/b5-b6-answer-feedback-export`（提交 `1efb79c`…`310fc42`，2026-08-06）。费用守卫、限流、可信 IP 补齐了必测；Docker 优雅关闭、`OperationalMetrics` 可观测性、`GET /api/admin/ops/status` 运维端点、`railway.json`、`docs/deployment.md` 均已实现。`REQUIRE_INTEGRATION_DB=1 pytest` 在真实 PostgreSQL 上跑通 **703 passed、0 skipped、0 failed**（首次跑通时发现一个真实 bug 并已修复，见「最近验证」）；`ruff`/`ruff format`/`mypy`（88 源文件）全绿。**未完成的只剩需要人工在 Railway 控制台操作的部分**：实际创建 Railway 项目、连接 PostgreSQL、填写环境变量、执行部署，以及依赖真实部署环境的验收项（见 `docs/backend-development-plan.md` §B7「验收（MVP 出口）」）。
- 前端：F0–F5 均已完成并集成于 `feature/integrate-b7-f4`。F5 的质量轨迹、实时回答反馈和无障碍回归已在本地提交 `414d267`；历史会话质量轨迹和反馈受会话详情契约限制，归阶段 B Task 8。
- 前端：**前端 F0–F6 代码与文档已完成，Railway 部署就绪；Railway 尚未部署，MVP 尚未宣告完成。** F6 Task 1–8 与 Task 12 已完成：生产演示模式、未配置 LLM 的费用守卫、首屏 ECharts 显式挂载、生产 Mock/密钥门禁、前端 `railway.json`、文档同步、部署手册与出口证据矩阵均已落地。前端本地命令中 lint、格式、codegen、fixtures、类型检查、Vitest（**26 文件 / 245 passed**）、构建、Mock、首屏静态与密钥门禁均已通过；专用首屏 Playwright 的测试断言输出 `ok 1`，但同样因 Windows `webServer` 清理挂起以 exit 124 结束，不能计为全绿门禁。常规 Playwright 的 **26/26** 断言亦均输出 `ok`，但 CLI 随后清理超时（exit 124），因此该命令不能记为成功退出。后端 `ruff`、格式与 `mypy app`（**88 source files**）通过；Docker 引擎不可用，未运行 `REQUIRE_INTEGRATION_DB=1 pytest`。Task 9–11（用户控制台部署、无 LLM 线上验收、经 R3 授权后的真实模型验收）尚未执行。逐项证据与未验证缺口见 `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md`。
- F1 遗留：1440×1000 人工视觉比对待本地 Windows Computer Use helper 可用后补做；不影响已通过的结构、几何和无障碍自动化验收。
- **仓库结构提示（本轮确认，2026-08-11）**：主目录现直接签出 `feature/integrate-b7-f4`（不再是独立 worktree）。仍保留的历史 worktree 只剩 `.worktrees/feature-b5-b6-answer-feedback-export/`（`feature/b5-b6-answer-feedback-export`，已推到 `origin`）与 `.worktrees/feature-f3-real-api-integration/`（`feature/f3-real-api-integration`）；两者内容已分别并入集成分支，留作对照，不再是主线。`feature/b4-safe-analytics-query` 的独立 worktree 已不存在。

## 已完成

- 后端 B0–B3：FastAPI 工程、演示商家身份与商家隔离、PostgreSQL/Alembic、会话和回答持久化、Chat JSON/SSE 双路径、幂等、跨商家审计和服务端推荐问题；指标/维度/筛选白名单、知识检索、Fake/DeepSeek LLM Client、两阶段结构化意图和 LangGraph 问答图均已落地。真实 DeepSeek 尚未调用。
- 后端 B4 Task 1–2：创建订单、订单项、退款、退货、商品和工单六张经营数据表与迁移；完成可重复的 180 天演示经营数据 Seed。
- 后端 B4 Task 3–4：建立指标、维度与筛选 SQL 契约，完成业务时区日期解析和查询范围控制；完全落在未来的日期范围会显式拒绝，不再被静默截断。
- 后端 B4 Task 5–6：完成受控指标聚合和五类受控明细查询。已修复订单按商品/类目拆分时的 join 放大问题：GMV 改按订单项金额聚合，订单数去重，并由真实 PostgreSQL 回归测试覆盖。
- 后端 B4 Task 7：完成 Safe Query Service，按白名单路由指标和明细查询，强制商家范围、绑定筛选值、限制预览行数，并确保拒绝原因与查询计划不暴露表名、列名或 SQL 片段。
- 后端 B4 Task 8：新增 `GET /api/metrics/{code}` 指标口径接口；OpenAPI、`docs/api.md`/`docs/api.json` 和前端生成类型已同步。已废弃指标可供口径面板查询，但不会重新进入聊天查询路径。
- 后端 B4 Task 9：`MerchantQaGraph` 的 `query_data` 节点已接入 `SafeQueryService`。`METRIC` 和 `DETAIL` 回答可返回真实数据行、总数、截断状态、查询计划和 `DATABASE` 数据来源；没有查询服务、查询被拒绝或失败时仍返回可见降级；有查询结果时不再输出否认查询发生的建议文案。
- 后端 B4 Task 10：新增 `tests/integration/services/test_safe_query_security.py`（6 个用例），把§B4 验收清单里「跨商家隔离」「SQL 注入」「180 天上限」「statement timeout」「拒绝原因不泄漏 SQL/表名」逐条钉成可独立失败的测试（跨商家用例特意让两个商家在同一天持有不同金额的数据，避免用两个空集合互相比较导致测不出回归）；`tests/integration/test_migrations.py` 补充断言六张经营表由迁移建出。详见 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/task-10-report.md`。
- 后端 B4 收尾（`7d28552`）：`REFUND` 分类的明细按「维度/筛选字段 → 分类关键词 → 兜底查退款」三级信号分流到 `returns` 或 `refunds`。此前 `DETAIL_BY_CATEGORY` 把 REFUND 写死指向 `refunds`，退货明细永远查不到，§B4 验收的「退货明细可查询」实际不可达。分流规则写在 `docs/backend-development-plan.md` §B4「实现说明」的第 4 条偏离里。
- 后端 B4 终审修复轮（2026-08-05，`b174bd9`、`50a28e6`）：修掉 1 条 Critical 与 6 条 Important——`ChatResponse.answer` 有查询结果时不再否认查询发生过（自洽性不变量扩到 `answer`/`recommendations`/`quality_notes`/`degraded_reason` 四个字段）；仓储与问答图之间补上 `SQLAlchemyError → UnsupportedQueryError` 异常边界，并校验 `date` 筛选值、夹紧 `limit` 下界，合法意图不再可能返回 500；`scripts/seed_demo_analytics.py` 补生产环境护栏、`--dry-run`，默认 `--end-date` 改按业务时区推导；商品明细改为不按业务日过滤（`DetailSpec.date_filtered`）；补齐商品与工单两张明细表、`support_ticket_count` 聚合的运行时测试，以及「契约列名 ↔ ORM 列」的参数化不变量。
- 后端 B4 文案卫生防线（`50a28e6`）：`test_stage_reference_hygiene.py` 用 AST 扫 `app/agent/**` 的非 docstring 字符串字面量、并递归扫每个已发布 fixture 的字符串值，禁止出现指向**当前阶段**的前向引用（指向后续阶段的引用是诚实的，不禁）。指向本阶段的「将在 B4 接入」两次躲过人工评审——一次漏在 `answer`、一次漏在 `fallback_reason`——所以改用机械防线。**该测试的 `CURRENT_STAGE` 常量需在每个阶段合并时更新**（本轮已随 B6 提交改成 `"B6"`）。同轮补齐 `DIMENSION_SPECS` 的「契约列名 ↔ ORM 列」参数化不变量。
- 前端 F0–F2：Vue 3 + TypeScript + Vite 工程、三栏商家助手布局、SSE 解析、Mock 传输、会话状态机、取消/重试、演示商家切换、会话历史与轮次目录均已交付；F2 审查整改已包含降级状态展示、商家切换清理和并发提交保护。
- 后端 B5（`7c60b12`）：`VisualizationService`（只用 `QueryResult` 已登记的维度/指标列生成图表，不信任模型字段名）、`AnswerService`（结构化回答草稿 + 本地确定性校验：数字幻觉、非加和指标合计、内部标识符泄露三类拦截）、`ReviewService`（独立 Reviewer，只出「通过/问题列表」，不改写回答，最多两轮）均已接入 `MerchantQaGraph`；`quality_status` 覆盖 `PASSED`/`DEGRADED`/`FAILED`/`NOT_RUN`，`quality_attempts`/`quality_notes` 如实记录。
- 后端 B6（`18ba978`/`b494277`/`acc7efa`）：`POST /api/answers/{id}/feedback`（商家范围内幂等采纳/点赞点踩，跨商家 403 + 审计）、`GET /api/exports/{id}`（HMAC 签名 URL、15 分钟过期、下载时重新执行受控明细查询、UTF-8 BOM、公式注入防护、`Referrer-Policy: no-referrer`）、`export_files` 迁移与 `ChatService` 导出接线（只在 DETAIL 成功且未降级时创建导出记录）均已实现。此前一轮复审已修过 5 处问题（导出 CSV 双重 BOM、本地校验缺两条方案要求的检查、导出记录未排除降级回答、签名密钥兜底值重复、feedback/exports 路由完全没有 HTTP 层测试），新增 24 条测试后全量后端测试从 628 涨到 652 passed；随后 B7 Task 1-18 又新增测试，2026-08-06 用真实 PostgreSQL 复核全分支得到 703 passed、0 failed，见「最近验证」。
- 后端 B7（`1efb79c`…`310fc42`，2026-08-06）：`LlmCostGuard`/`SlidingWindowRateLimiter`/`resolve_client_ip` 补齐单元测试，新增伪造 `X-Forwarded-For` 的端到端信任边界测试和 `LlmBudgetRepository` 并发原子扣减的真实库回归；`app/run.py` 显式声明 30 秒优雅关闭窗口并记录「保持单 worker」的架构决策；新增 `OperationalMetrics`（进程内运维指标：路由/Agent 节点耗时、错误码分布、限流命中、降级计数）并接入请求中间件、异常处理器、`ChatService`、`MerchantQaGraph`；新增 `require_admin_token` 依赖（只认 `X-Admin-Token`）与 `GET /api/admin/ops/status`（未配置 `ADMIN_TOKEN` 时整体不挂载路由）；新增 `railway.json` 与 `docs/deployment.md`；`CURRENT_STAGE` 推进到 `"B7"`。**实际 Railway 部署未执行**——按计划约束本轮只产出配置产物，创建项目/连接数据库/填写环境变量/验证部署留给用户。
- B7/F4 分支整合「阶段 A」（`3faef8a`…`ac042a0`，2026-08-10）：按 `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md` Task 1–4，以 B7（`feature/b5-b6-answer-feedback-export`）为后端基线、按路径移植 F3/F4 前端（不引入 F3 的替代 analytics/export 后端），以集成后端重新生成 OpenAPI/`generated.ts`/Chat fixture，新增 `e2e_app.py`/`seed_f4_e2e.py` 装配 B7 的 `SafeQueryService`/`ExportService` 供真实数据库 Playwright 使用；结果即上方「当前集成验收快照」的数字。SDD 账本见 `.superpowers/sdd/2026-08-09-b7-f4-integration-and-r9-remediation/progress.md`（只记到 Task 4，Task 5–15「阶段 B」未开工）。
- 文档目录整改 R10（`40cb282`，2026-08-10）：按用户裁决，技能产出的计划与设计文档改用项目自己的目录——`docs/superpowers/plans/`（10 份）迁至 `plans/`，`docs/superpowers/specs/`（13 份）迁至 `docs/specs/`，`docs/superpowers/` 已删除，修复 7 处因移动断链的交叉引用；`AGENTS.md` 新增 R10 固化此规则；新增 `CLAUDE.md`（内容为 `@AGENTS.md`）。
- 前端 F5（2026-08-11，提交 `414d267`）：按 `docs/specs/2026-08-10-frontend-f5-design.md` 与 `plans/2026-08-11-frontend-f5-implementation.md` 实现质量轨迹、反馈与无障碍收口。`ChatMessage.vue` 展示四种质量状态、校验次数、备注和中文来源；反馈通过 Adapter/API/Store 分层接入 B6，覆盖失败保留、同值重试、持久化粘性和 reset 中止；新增仅用键盘完成提问与采纳的 Playwright。历史消息因会话详情缺 `answer_id` 与当前反馈状态而不开放反馈，边界已登记到阶段 B Task 8。
- 前端 F6 Task 1–6（2026-08-11～2026-08-12，提交 `d0dcace` 与 `49fadc4`）：Task 1 新增 `Settings.demo_deployment_mode`，生产环境默认关闭演示商家端点、只在显式开启时放行，`GET /api/admin/ops/status` 同步返回该布尔字段；OpenAPI/`docs/api.md`/前端生成类型已重新导出同步。Task 2 修正 `LlmCostGuard.complete()`：未配置底层 LLM 客户端时直接抛 `LlmUnavailableError`，不再先预扣预算和用量计数。Task 3 新增 `frontend/e2e/first-paint.spec.ts` 与独立的 `playwright.first-paint.config.ts`（生产构建 + preview），先立证据证明 `AssistantView` 静态引入 `MetricChartPanel` 会让 `echarts-*.js` 出现在首屏请求里。Task 4 把图表面板改为 `defineAsyncComponent` + 显式 `chartMountable` 挂载开关（空闲回调或收到图表回答才挂载），首屏改渲染带无障碍属性的占位；`scripts/check-first-paint.mjs` 经用户同意增强为「预加载检测 + 入口静态 import 链 + `v-if` 存在性」三层静态门禁，并修复了组件卸载时未清理空闲回调/回退计时器、导致测试销毁后仍触发图表 loader 的缺陷。Task 5 新增 `frontend/src/build/mock-flag.ts`（`assertMockDisabledInProduction`），在 `vite.config.ts` 用 `loadEnv` 于配置解析期调用，`VITE_USE_MOCK=true` 时生产构建直接报错拒绝；`Dockerfile` 同步声明并透传该构建参数；经用户授权在根 `.gitignore` 为 `frontend/src/build/` 新增最窄反忽略规则使新源文件可追踪。Task 6 新增 `frontend/railway.json`（前端 Railway 配置即代码）与 `frontend/scripts/check-no-secrets.mjs`（扫描 `dist/` 拦截 DeepSeek Key、PostgreSQL 连接串、`DEMO_MERCHANT_TOKENS`、`ADMIN_TOKEN`、`EXPORT_SIGNING_SECRET` 形态字符串），均用真实构建产物做过变异验证（人为注入密钥后扫描能命中，清理后恢复通过）。
- 前端 F6 Task 7（2026-08-12）：完成路径与 F6 文档同步；`DEMO_DEPLOYMENT_MODE`、Service Root 内的 `backend/railway.json`/`frontend/railway.json`、`docs/deployment.md` 及两个新增构建门禁均已登记。全量前端本地门禁的成功退出结果为 lint、格式、codegen、fixtures、类型检查、Vitest（**26 文件 / 245 passed**）、构建、Mock、`firstpaint:check`、密钥扫描。专用首屏 Playwright 的测试断言输出 `ok 1`，但 Windows `webServer` 清理挂起使命令以 exit 124 结束，**不计为全绿门禁**；常规 Playwright 的 **26/26** 测试也均输出 `ok`，但同样在清理超时（exit 124），仅记录断言结果。`REQUIRE_INTEGRATION_DB=1 pytest` 也未运行：`borough-int-postgres` 不可用，Docker npipe 不存在。两项变异验证仍有效：无条件图表挂载会被首屏静态门禁拦截，构建产物临时注入密钥后会被密钥扫描拦截；均已恢复干净状态。全程 DeepSeek 调用 **0**、费用 **0**。

## 最近验证

- **阶段 0 全量门禁复核（2026-08-12）**：后端 `ruff check .`、`ruff format --check .` 与
  `mypy app`（88 个源文件）通过；前端 lint、格式、codegen、fixtures、类型检查、Vitest（**26 个文件 /
  245 passed**）、生产构建、Mock、密钥与首屏静态门禁均通过。真实 PostgreSQL 全量 pytest 首次指向
  持久化的 `borough_test` 时被历史 Alembic 版本 `20260808_0005` 阻断；该版本不属于当前分支迁移图。
  为避免删除现有卷，改用独立空库 `borough_stage0_20260812_test` 重跑，结果为 **717 passed / 0 failed /
  1 条第三方弃用警告**。全程使用 Fake/确定性 LLM，DeepSeek 调用 **0**、费用 **0**。

- **前端 F6 Task 1–7 定向与门禁验证（2026-08-11～2026-08-12）**：后端 Task 1 定向回归
  `tests/unit/core`、`tests/api/test_demo_merchants.py`、`tests/api/test_admin_ops.py` 共
  **28 passed、1 skipped**（跳过项是本机无真实 PostgreSQL 导致的既有集成用例，非新增缺陷）；
  `ruff check`、`ruff format --check`、`mypy app` 全绿。Task 2 定向 `tests/unit/llm`、
  `tests/api/test_chat.py` 共 **30 passed、4 skipped**（同样因本机无真实库跳过），guard 单测
  **6 passed**；两个 Task 均做过变异验证（临时改回原实现，对应新测试真实失败，验证后已还原）。
  前端 Task 3 用生产构建 + preview 独立复现红灯（`echarts-*.js` 出现在首屏请求），随后由 Task 4
  修复；Task 4 直接单测 **27 passed**（`AssistantView.spec.ts` + `InsightPanels.spec.ts`），静态
  门禁 `firstpaint:check` 变异验证：无条件渲染时被增强后的三层检查拦下（`exit 1`），恢复 `v-if`
  后放行（`exit 0`）；同轮修复了组件卸载未清理回退计时器导致的测试间干扰。Task 5/6 完成后于
  2026-08-12 重新执行前端完整门禁：**Vitest 26 文件、245/245 passed**，`typecheck`/`build`/
  `mock:check`/`secrets:check` 全部通过；`secrets:check` 做过真实构建变异验证（临时注入密钥字符串
  后命中，清理后恢复通过）。全程 DeepSeek 调用 **0**、费用 **0**。**已知不属于本轮修复范围的环境
  噪音**：Playwright CLI 在本机执行完用例后不主动退出，需靠外层超时结束进程（不影响断言结果本身）；
  常规 E2E 曾观察到的 `responsive.spec.ts › 输入提示和侧栏说明文字达到 WCAG AA 对比度` 已定位并修正为
  F6 图表显式挂载后失效的计数断言（首屏不再存在 `chart-empty` 的两项文本）；现有五项文字均为
  `rgb(89, 101, 121)`，对白背景约 **5.95:1**，满足 AA。修复后常规 E2E 26/26 断言均为 `ok`，但 CLI
  清理超时仍是环境限制。

- **集成分支全量复核 + 测试隔离缺陷修复（2026-08-11，仓库根实跑）**：在专用容器
  `borough-int-postgres`（55442）/`borough-int-f4-postgres`（55443）上重跑全部门禁。首轮后端真实库
  pytest 为 **702 passed、5 failed**，5 条全部报 `生产环境配置 LLM_API_KEY 时必须设置 ADMIN_TOKEN`。
  根因**不是产品代码回归**，而是测试没有与开发者的 `backend/.env` 隔离：`Settings.model_config` 声明
  `env_file=(".env", "../.env")`，这些用例故意不传 `llm_api_key`/`admin_token` 来验证生产禁令，却被
  仓库根 `backend/.env` 里的 `LLM_API_KEY`（且该文件无 `ADMIN_TOKEN`）污染。**2026-08-10 那次
  707 passed 是在没有 `.env` 的 worktree 里跑的，缺陷一直存在、被环境掩盖**，与 B7 的
  `llm_daily_budget` 漏 TRUNCATE 属同一类。已按 TDD 修复：`tests/conftest.py` 新增 session 级 autouse
  fixture `isolate_settings_from_dotenv`，测试期关闭 Settings 的 dotenv 来源并在结束后还原；
  `tests/unit/core/test_config.py` 新增 `test_settings_in_tests_ignore_ambient_dotenv`，用 `tmp_path`
  自造 `.env` 复现，不依赖本机文件。变异验证：停掉 fixture 该测试真实失败，还原后无残留。
  修复后全量真实库 **708 passed、0 skipped、0 failed**；`ruff check`、`ruff format --check`（198 files）、
  `mypy app`（88 源文件）全绿。前端 lint/format/codegen:check/fixtures:check/typecheck/build/mock:check
  全部通过，Vitest **238 passed**（25 文件），Mock Playwright **25 passed**，真实库 Playwright
  **3 passed**。DeepSeek 调用 **0**、费用 **0**；共享卷 `borough_borough_postgres_data` 执行后核验仍在。
  **同轮补齐环境变量向量（R9 依据）**：初版只关闭 dotenv 来源，进程环境变量仍可污染测试。核对参考
  项目后按 R9 补齐——`yshopping-merchant-ai 4/` 的 12 个测试一律 `new AppProperties()` 手工赋值，
  既无 `application-test.yml`，也无 `@SpringBootTest`/`@TestPropertySource`，测试与主代码均零处
  `System.getenv`，配置解析只发生在 Spring 运行时路径上，测试根本不走那条路径。因此「只堵 `.env`
  而放行环境变量」只还原了一半。fixture 已改名为 `isolate_settings_from_ambient_config`，通过覆盖
  `Settings.settings_customise_sources` 把来源链裁到只剩 `init_settings`，语义等价于参考项目的
  `new AppProperties()`；`tests/unit/core/test_config.py` 相应新增
  `test_settings_in_tests_ignore_ambient_environment_variables`。变异验证：只放回 env 来源时，
  环境变量那条真实失败而 dotenv 那条仍通过，证明两条测试各守一个来源。补齐后全量真实库
  **709 passed、0 skipped、0 failed**；`ruff check`、`ruff format --check`、`mypy app` 全绿。
  该隔离同时消除了一个此前存在的费用风险面：修复前测试构造的 Settings 会拿到 `backend/.env` 里的
  真实 `LLM_API_KEY`，而 `app/api/dependencies.py:142` 正是「有 key 就用 `DeepSeekLlmClient`」，
  只要有测试路径未覆盖 LLM 依赖就可能发出真实调用；现在测试永远拿不到该 key。

- 前端 F5（2026-08-11）：`lint`、`format:check`、`codegen:check`、`fixtures:check`、`mock:check`、`typecheck`、`build` 全部通过；Vitest **238 passed**（25 个文件），Mock Playwright **25 passed**。构建仅有既有 ECharts 556.46 kB chunk-size 提示；全程未调用 DeepSeek。

- B4 Task 5 的聚合修复：目标 PostgreSQL 集成测试 12 项通过；全量后端测试 510 项通过。
- B4 Task 7 修复后：目标测试 15 项通过；全量后端测试 528 项通过。
- B4 Task 8：口径端点及 OpenAPI/前端类型同步已完成，`codegen:check` 通过。
- B4 Task 9：后端测试 536 项通过；前端测试 118 项通过；fixture 漂移检查通过。
- **B4 Task 10（2026-08-05，真实库实跑）**：在测试用 PostgreSQL（`borough_test`）上依次执行
  `alembic upgrade head` → 播种三个演示商家 → `scripts/seed_demo_analytics.py`（写入 17538 行）→
  全量 `pytest`，**544 passed、0 skipped**（较收口前的 538 新增 6 条安全回归用例）。
  `ruff check`、`ruff format --check`、`mypy`（69 个源文件）全绿。
  三条最容易「测不出回归」的用例做过手工变异验证：临时把商家过滤条件改成恒真、
  把 180 天截断分支临时禁用，两次都能让对应测试真实失败（分别报出 1099.00 的跨商家泄漏总额、
  和缺失的截断说明），验证后已还原，`git diff` 确认改动未残留。
- **B4 终审修复轮（2026-08-05）**：后端 **612 passed、0 skipped**（较修复前的 550 新增 62 条），
  `ruff check`、`ruff format --check`、`mypy`（69 个源文件）全绿；Chat Fixture 已重新导出并同步前端，
  `fixtures:check` 一致，前端 **118 passed**、`lint`/`format:check` 全绿。
  商品明细的时间窗修复做过手工变异验证：把 `DETAIL_SPECS["products"].date_filtered` 改回 `True`，
  4 条新用例（契约层 1 条 + 仓储层 2 条 + 服务层 1 条）同时真实失败，验证后已还原。
- **B5/B6 提交前复核（2026-08-06）**：提交前发现 `ruff check` 有 21 处错误（导入排序 2 处 + 行长超限
  19 处，全部集中在 B6 提交里附带的 B7 限流/成本守卫代码，以及 `answer_service.py`/`operations.py`/
  迁移文件里少数几行）、`ruff format --check` 要求重排 15 个文件——**此前记录的「652 passed，ruff/mypy
  全绿」并不准确，本轮已实际修复并重新验证**：修复后 `ruff check`/`ruff format --check`/`mypy`（86 个
  源文件）全绿。因本机 Docker Desktop 引擎当时不可用（`npipe` 连接失败），**本轮只重新跑通了非 DB 用例
  （549 passed、112 项因缺数据库被跳过），没有重新用真实 PostgreSQL 复核此前声称的 652 passed**；
  合并/开 PR 前必须先起 `docker-compose -p borough up -d postgres` 补跑一次
  `REQUIRE_INTEGRATION_DB=1 pytest`。`docs/api.json` 当时相对实际 FastAPI schema 有漂移（403 状态码
  说明文案），已用 `uv run python ../scripts/export_openapi.py` 重新导出并随 B6 Task 5 提交。
- **B7 收口 + 真实 PostgreSQL 首次复核（2026-08-06）**：`docker-compose -p borough up -d postgres` 起库后
  跑 `REQUIRE_INTEGRATION_DB=1 pytest`，**首次运行 701 passed、2 failed**——`tests/api/test_feedback.py`
  里排在后段的两个用例稳定收到 `503 LLM_BUDGET_EXCEEDED`。根因：`tests/postgres.py::TRUNCATE_ALL_TABLES`
  没有包含 `llm_daily_budget`；该表按 `usage_date` 记账，一整轮 pytest 在同一天内跑数百个真实请求，
  所有集成测试共用同一行预算，跑到后段就把默认 `llm_daily_budget_tokens=20_000` 耗尽，是真实的测试隔离
  缺陷而非误报——不跑真实库、只跑 Fake LLM 或单元测试都发现不了。补上 `llm_daily_budget` 后
  （提交 `64e60e3`）重新跑通：**703 passed、0 skipped、0 failed**（较 2026-08-05 收口时的 652 新增
  51 条，含 B7 全部必测）。`ruff check`、`ruff format --check`、`mypy`（88 个源文件）全绿。

## 下一步

1. **产出 R9 Task 9 指标口径子计划**：先固化三级检索、`response_payload` 兼容和 `report_url` 安全策略，
   经用户审阅后才以 TDD 实施。
2. **继续 R9 阶段 B Task 10–15**：纯明细、跨业务和临时指标均先各自产出子计划并经用户审阅，最后进行
   真实数据库 E2E 和可信客户端 IP 契约整改。
3. **执行 R9 阶段 B Task 9–15 与可信客户端 IP 契约整改**：四个能力切片先分别成文、经用户审阅后实施，
   随后修复 Railway 的 `X-Real-IP` 信任链并由用户裁定 `TRUSTED_PROXY_IPS` 策略。
4. **最后才进入 Railway 部署与线上验收**：完成 R9 与可信 IP 契约整改后，用户在控制台执行 F6 Task 9–10；
   真实 DeepSeek 验收仍须另行按 R3 说明模型、调用次数与费用并取得明确同意。

## 风险与约束

- 未获用户明确同意，不得调用真实 DeepSeek API、收费 OCR 或日报生成；单元测试必须 mock LLM。真实模型调用前须先说明模型、调用次数和预期费用。
- 商家身份只可由 Bearer Token 解析；后端所有经营查询必须强制注入 `merchant_id`，不得信任前端传入的商家编号。
- `backend/tests/unit/agent/test_stage_reference_hygiene.py` 的 `CURRENT_STAGE` 常量在集成分支
  `feature/integrate-b7-f4` 上是 `"B7"`（随集成保留 B5/B6/B7 收口时的值，未随之后的整合/文档提交改动）。
  该常量只扫 `app/agent/**` 的字符串字面量，F5 是纯前端阶段，预计不需要为它推进这个常量；若后续
  「阶段 B」（R9 整改）引入新的后端 stage，记得同步推进，否则该防线会继续只挡旧阶段字样。
- **Docker Desktop 在本机环境偶发无法启动**：曾出现引擎持续返回 `500 Internal Server Error`（不是
  常见的「还在启动」connection-refused 现象），完全重启 Docker Desktop 进程后仍未恢复，等了将近
  20 分钟后才自行恢复正常。如果下次又遇到真实 PostgreSQL 集成测试连不上库，先确认这不是环境本身的
  瞬时故障，必要时重启 Docker Desktop 并耐心等待，而不是假设代码或配置有问题。
- **本机 Playwright CLI 执行完用例后不会自行退出**：需要依赖外层超时（60–180 秒）结束进程；这是
  本机环境噪音，不代表测试挂起或断言未完成，但每次跑 E2E 都会看到看似「超时」的收尾，不要误判为
  用例失败。F6 Task 3/4 的报告已多次记录此现象。
- **`responsive.spec.ts` 存在一条与 F6 改动无关的既有失败**：`输入提示和侧栏说明文字达到 WCAG AA
  对比度`，F6 Task 3/4 验证常规 E2E 时观察到，尚未定位归因，不阻塞 F6 出口但需要单独排查。
- **F6 的 SDD 账本落后于实际执行**：`.superpowers/sdd/2026-08-11-frontend-f6-railway-mvp-closeout/
  progress.md` 只记到 Task 4，Task 5/6 已完成但账本未回填，核对进度时必须同时查看各 Task 的
  report 文件，不能只信账本本身。
- **`GET /api/admin/ops/status` 是新增的敏感面**：只认 `X-Admin-Token`（`hmac.compare_digest` 比较），
  `Authorization` 头一律忽略；`ADMIN_TOKEN` 未配置时端点整体不挂载路由（404，而非 401/403），避免
  「路由存在但认证总是失败」暴露端点存在性。修改这块代码时留意 `tests/api/test_admin_ops.py` 的
  401/403/404/200 四态断言仍然成立。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码、文案和资源必须使用 Borough。
- 后端 B4 的具体 Task 状态以 `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md` 和 Git 提交记录为准；该目录被 `.gitignore` 忽略，只存在于产出它的那个工作副本里，不会随分支/worktree 一起出现。B5/B6/B7 本轮没有对应的 SDD 账本，本文件是这段工作的权威摘要。B7/F4 集成（阶段 A）有对应账本，见下方「关键入口」。
- 本机存在多个 git worktree（见「当前阶段」末尾一条），核对进度前先用 `git worktree list` 和
  `git log <branch> --oneline` 确认自己看的是哪个分支的状态，不要只看主目录当前签出分支的文件是否存在
  就下结论。

## 关键入口

- `AGENTS.md`：项目规则、目录与开发顺序。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/backend-development-plan.md`：后端阶段、API/SSE 契约与 B4–B9 顺序。
- `docs/frontend-development-plan.md`：前端 F0–F9 阶段计划。
- `backend/app/services/safe_query.py`：B4 受控查询应用服务；`ExportSpec`/`export_detail` 供 B6 导出复用。
- `backend/app/repositories/analytics.py`：B4 指标聚合与明细数据访问；B6 的 `export_detail` 也在这里。
- `backend/app/agent/graph.py`：B4 真实查询、B5 回答/审核编排接入问答图的落点。
- `backend/app/services/answer_service.py`、`review_service.py`、`visualization_service.py`：B5 回答草稿、独立 Reviewer 与安全图表。
- `backend/app/services/export_service.py`、`feedback_service.py`：B6 签名 CSV 导出与商家反馈。
- `backend/app/api/routes/exports.py`、`feedback.py`：B6 对外端点。
- `backend/app/llm/guard.py`、`app/core/rate_limit.py`、`app/core/client_ip.py`、`app/repositories/llm_budget.py`：B7 费用防护/限流/可信代理 IP 基础设施，必测已补齐（`tests/unit/llm/test_guard.py`、`tests/unit/core/test_rate_limit.py`、`tests/unit/core/test_client_ip.py`、`tests/integration/repositories/test_llm_budget_repository.py`、`tests/api/test_rate_limit_trust_boundary.py`）。
- `backend/app/core/metrics.py`、`app/api/routes/admin.py`：B7 运维可观测性（`OperationalMetrics`）与 `GET /api/admin/ops/status` 运维端点。
- `backend/railway.json`、`docs/deployment.md`：B7 Railway 配置即代码与部署运维手册；实际部署仍需用户在 Railway 控制台执行。
- `backend/tests/integration/services/test_safe_query_security.py`：B4 §验收清单的安全回归测试（跨商家隔离、SQL 注入、180 天上限、statement timeout、拒绝原因不泄漏 SQL/表名）。
- `backend/tests/api/test_exports.py`、`test_feedback.py`：B6 端点的 HTTP 契约测试（签名、过期、跨商家、公式注入、BOM）。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/progress.md`：B4 逐 Task 账本、复查和延后项。
- `.superpowers/sdd/2026-08-04-backend-b4-safe-analytics-query/task-10-report.md`：B4 §验收清单逐条对照表、真实库端到端验收记录和文档改动说明。
- `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md`：B7/F4 分支整合（阶段 A，已完成）与 R9 差异整改（阶段 B，未开工）的执行计划；阶段 A 的实测基线数字都以此计划 Task 4 为准。
- `.superpowers/sdd/2026-08-09-b7-f4-integration-and-r9-remediation/progress.md`：上述整合计划的逐 Task 账本，只记到 Task 4。
- `docs/specs/2026-08-10-frontend-f5-design.md`：前端 F5（质量轨迹、反馈与无障碍基础）设计说明，当前工作树有未提交的评审修订。
- `plans/2026-08-11-frontend-f5-implementation.md`：F5 的 TDD 实施计划与验证命令。
- `plans/2026-08-11-frontend-f6-railway-mvp-closeout.md`：F6「Railway 部署就绪」实施计划（12 个 Task，第 2 稿），Task 1–8 与 Task 12 已完成；Task 9–11 均待用户在 Railway 控制台或线上环境执行，尚未开始。前端 F0–F6 代码与文档已完成、Railway 部署就绪，但 Railway 尚未部署，MVP 尚未宣告完成。
- `docs/specs/2026-08-11-frontend-f6-design.md`：F6 对应设计说明，状态待用户审阅。
- `.superpowers/sdd/2026-08-11-frontend-f6-railway-mvp-closeout/`：F6 逐 Task brief/report/review 账本目录；`progress.md` 只记到 Task 4，以逐 Task report 为准。
- `frontend/src/build/mock-flag.ts`、`frontend/scripts/check-first-paint.mjs`、`frontend/scripts/check-no-secrets.mjs`、`frontend/railway.json`：F6 新增的生产构建门禁与前端 Railway 配置即代码。
- `backend/app/core/config.py` 的 `demo_deployment_mode`、`backend/app/llm/guard.py` 的客户端可用性前置检查：F6 Task 1–2 触碰的后端生产代码。
