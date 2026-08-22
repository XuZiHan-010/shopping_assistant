# 还原缺口与简历目标功能路线图

> **这不是可执行计划。** 它是缺口全景与排期依据，可执行的实施计划见 §1 的索引。
> 不要直接照本文件写代码——本文件不含任务步骤，也不含代码。

**用途：** 把「参考项目有、我们没有」的还原缺口，与「简历上写了、代码里没有」的目标功能合并成一张全景表，指明每一项归哪份文档管、按什么顺序做。

**依据：** `docs/yshopping-parity-audit.md`、`docs/project-progress.md`、`plans/2026-08-19-codex-remaining-development-tasks.md`、用户提供的简历口径项目描述（V2/V3/V4，原文见 §2.1）。

---

## 1. 文档索引

| 文档 | 类型 | 状态 | 覆盖 |
| --- | --- | --- | --- |
| `plans/2026-08-21-workspace-closeout.md` | 可执行计划 | 待执行 | 当前脏工作区收尾 |
| `plans/2026-08-21-memory-compress-and-history-suggestions.md` | 可执行计划 | 待执行 | 手动记忆压缩端点、猜你想问接历史高频 |
| `docs/specs/2026-08-21-daily-report-contract.md` | 设计说明 | **待裁定（8 个问题）** | 每日日报的契约与业务规则 |
| 本文件 | 路线图 | — | 附件/OCR、Chat BI 看板、语义增强、文档同步 |

**顺序**：收尾 → 压缩与推荐 → 日报（先裁定 spec，再出实施计划）→ 其余按 §4 排。

---

## 2. 缺口全景

「参考」指 `yshopping-merchant-ai 4/`，「简历」指用户提供的项目描述。

| # | 能力 | 参考 | 简历 | 我们 | 归类 | 归哪份文档 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 记忆沉淀含历史问答 | ✅ `recentAnswers(id, 80)` | ✅ | ⚠️ 已改未提交 | 🔴 还原缺口 | 收尾计划 |
| 2 | 手动记忆压缩端点 | ✅ `POST /api/wiki/compress`（**已纳入管理员令牌过滤**） | ✅ 运营人工补充 | ❌ | 🔴 还原缺口 | 压缩与推荐计划 |
| 3 | 猜你想问按历史**高频** | ✅ `GROUP BY question ORDER BY COUNT(*) DESC` | ✅ 基于记忆沉淀提供素材 | ❌ 纯静态 | 🔴 还原缺口（2026-08-21 新发现） | 压缩与推荐计划 |
| 4 | 每日经营日报 | ✅ `DailyReportService` | ➖ | ❌ | 🟡 阶段未到（B8/F7） | 日报设计说明 |
| 5 | 日报定时推送 | ✅ 每天 10:00 Asia/Shanghai | ➖ | ❌ 底座也不存在 | 🟡 阶段未到 | 日报设计说明 Q5 |
| 6 | 附件上传 + OCR/解析 | ✅ `AttachmentService` / `AttachmentStore` | ✅ V3 | ❌ 零实现 | 🟡 阶段未到（B8/F7） | 本文件 §4.1 |
| 7 | Chat BI 衡量看板与北极星指标 | ❌ 参考没有 | ✅ | ⚠️ 只有原料 | ⚪ 有意增强 | 本文件 §4.2 |
| 8 | 不符意图 → 读 Session + 记忆再分析 | ❌ 参考只有重生成 | ✅ V2 | ❌ | ⚪ 有意增强 | 本文件 §4.3 |
| 9 | 新词语义层补齐 | ❌ | ✅ V2 | ❌ | ⚪ 有意增强 | 本文件 §4.3 |
| 10 | 无效意图不写记录表 / 失效问题引导提工单 | ❓ 未比 | ✅ | ❌ | ⚪ 有意增强 | 本文件 §4.3 |
| 11 | 简单问题绕过大模型省 Token | ❌ | ✅ | ❌ 每轮必 classify | ⚪ 有意增强 | 本文件 §4.3 |
| 12 | `GET/PATCH/DELETE /api/memories` | ❌ 参考没有 | ➖ | ❌ 文档超纲 | **已裁定：删文档** | 本文件 §5 |
| 13 | 指标 2000+ / Doris / DWD 数仓 | ✅（数仓侧） | ✅ | ❌ | **不做** | 本文件 §6 |

另有 3 项 ❓ 待核实（`DorisQueryService` 查询能力、`LlmIntentAnalysisService` 重试策略、`PromptLoopAnalysisService` 校验规则清单），各自开工前做一轮。

**V2 已有**：记忆子 agent、并行沉淀、跨业务 Plan、指标不存在时查明细宽表生成（`GeneratedMetricPlan`）。
**V3 已有**：前端交互、目录导航、图表 + 建议双栏。
**V4 全部已有**：双知识库单向边界、维护后台、指标口径三级检索与「大模型生成」标记。

### 2.1 简历口径原文（V2/V3/V4）

保留原文备查，功能是否已有以 §2 表格为准。

- **V2**：开发记忆沉淀子 agent，每次对话结束自动压缩且不影响用户沟通，对话和记忆沉淀分开并行；2 个不同业务分类的跨业务问题需建 Plan 拆成 2 次串行提问；指标不存在表中时，兜底从「联系人工」改为查询明细宽表自动分析生成；新建语义层 Agent 对用户意图识别及最终结果进行校验，输出不符合用户意图则继续读取本轮 Session 信息及历史记忆再次分析，包括算法关键词识别；用户提问的新词需在语义层补齐。
- **V3**：优化前端交互（背景色 / 按钮 Icon）；对话部分增加目录导航；提供可视化分析，指标信息在左侧提供折线图/饼图/柱状图，右侧提供建议展示；开发输入框附件上传功能，大模型可结合附件进行 OCR 识别解析用户传输意图。
- **V4**：新建人工知识库（优先访问），防止大模型提炼后形成的知识库污染人工维护知识库，从而形成双知识库；知识库维护后台按目录层建设维护功能；用户咨询指标命中 doris 表时（指标 comment）前端展示指标业务口径，未命中时让大模型按理解生成并带有大模型生成的提示。

---

## 3. 已裁定事项

| 编号 | 裁定 | 日期 |
| --- | --- | --- |
| D1 | **保留我方 REST 路径**，压缩端点用 `/api/admin/knowledge/memories/compress`、日报用 `/api/reports/daily`，均在 `docs/yshopping-parity-audit.md` §5 登记为有意偏离 | 2026-08-21 |
| D2 | **`/api/memories` 三条从文档删除**，回归 1:1 还原，代码零改动 | 2026-08-21 |
| D3 | 本路线图拆成三份独立文档（见 §1） | 2026-08-21 |

---

## 4. 路线图条目（均需先出设计说明再出实施计划）

### 4.1 附件上传与解析（🟡 还原 + 简历 V3，量级最大）

**范围**：参考的 `AttachmentService`、`AttachmentStore`、`POST /api/attachments`、`ChatMessage.vue` 附件区块；简历 V3 的输入框上传与 OCR 解析。

**我方现状**：`frontend/src/components/chat/ChatComposer.vue:66-72` 的回形针按钮是 `disabled`，`title="附件功能将在后续版本提供"`；后端无 `attachment_service.py`、无 `models/attachment.py`、无路由；只有 `AnswerMode.ATTACHMENT` 枚举名与后端计划里的 P1 契约。

**必须先回答**：

1. **存储介质**：`AGENTS.md` §十四 明确附件不得依赖容器临时磁盘。先落 PostgreSQL `bytea` 做 MVP，还是直接上对象存储（引入 SDK 与两个新密钥）？
2. **OCR 路径**：DeepSeek 的 Chat Completions 是否支持我们需要的图片输入？不支持则需第三方 OCR——**新外部依赖 + 新费用科目，须先按 R3 说明并取得同意**。PDF/Excel/CSV 走 PyMuPDF / openpyxl / Polars 无此问题。
3. **同步还是异步解析**：解析大文件会拖长 `POST /api/chat` 首字延迟。参考是同步的；我方有 SSE，可做成上传后异步解析 + `GET /api/attachments/{id}` 轮询（该端点已在 P1 契约里）。
4. **费用归属**：附件解析是否计入 `llm_max_calls_per_request` 与每日预算？按 R3 精神应当计入。
5. **安全边界**：类型白名单、大小上限、zip bomb、超大页数 PDF、CSV 公式注入的处置，逐条落到测试。

**验收**：支持图片/PDF/Excel/CSV，白名单外 415、超限 413；严格按 `merchant_id` 隔离，跨商家读取 403 并写审计（反例测试）；`ATTACHMENT` 模式回答能引用解析结果且 `analysis_sources` 如实包含；解析失败按 R7 显式降级；前端解除 `disabled`，支持点选与拖拽，`ChatMessage.vue` 渲染附件区块。

### 4.2 Chat BI 衡量看板（⚪ 有意增强，参考项目没有）

落地时**必须**在 `docs/yshopping-parity-audit.md` §5 登记为 ⚪，否则下一位 agent 会把它误当还原项。

| 简历里的北极星指标 | 已有原料 | 缺什么 |
| --- | --- | --- |
| 回复采纳率 | `feedback` 表已记采纳/点赞/点踩 | 聚合口径与端点 |
| 回复准确率 | `quality_status` / `quality_attempts` | 「准确」的定义 |
| 平均思考时长 | `agent_node_average_ms`（`backend/app/api/routes/admin.py:31`） | 端到端口径（现为分节点均值） |
| 问题命中率 | `INVALID` 比例、`quality_notes` 的「未命中知识资料」 | 「命中」的定义 |
| 回答失效率 | `degraded` 计数、`processing_status == "FAILED"` | 「失效」的定义 |

**必须先回答**：五个指标各自的精确口径（分子/分母/时间窗/是否按商家切分）；数据出口是新增 `GET /api/admin/ops/chatbi` 还是扩 `ops/status`（后者契约明确禁止返回商家经营数据）；看板落 `/admin/chatbi` 新路由还是并进 `KnowledgeBaseView`；**是否需要单独的 DWD 问答记录表——我方 `answers` 表已经是这份记录，不要为对齐字面新建冗余表**。

口径没定就不要开工，这是 §3.1 指标口径缺口留下的教训。

### 4.3 语义增强四项（⚪，参考项目均无）

每项都需要先补 `docs/specs/` 设计说明。

- **语义层再分析闭环（简历 V2 核心亮点）**：现状 `backend/app/agent/graph.py:425-427` 的重试用**同一份 facts** 重新生成，不重读 Session、不重读记忆、不重跑意图识别。关键约束：`MAX_INTENT_RETRIES=2` 与 `QUALITY_MAX_ATTEMPTS` 独立但共用同一个 `LlmBudget`，当前最坏路径 9 次，**加任何一次调用都要重算预算**；改提示词必配契约测试；需要一条断言「重分析输入确实包含 Session 与记忆内容」的测试。
- **新词语义层补齐**：白名单外的新词做补齐/映射而非直接 `INVALID`。**必须保持 R4**：补齐结果只能落到已验证的 `metric_code` / 维度枚举，不得让模型自由输出列名。
- **简单问题绕过大模型**：命中确定性规则（等于某条预置问题、纯问候语）时不调模型。**验收必须量化**：固定问题集跑前后对比，记录 `llm_usage` 调用次数差写进 `docs/project-progress.md`。
- **两个小口子**：①「无效意图不写记录表」——现状 `backend/app/repositories/conversation.py:163` 对每个请求都建 Answer 行，`INVALID` 照样落库；**不能简单不写**，`client_request_id` 幂等唯一约束依赖这一行，可行做法是保留行但标记为不进统计与记忆，**与 §4.2 的口径耦合，建议合并处理**。②「失效问题引导提工单」——`graph.py:394` 的 `INVALID` 文案加一句引导，纯文案改动。

---

## 5. 文档同步任务

可随时插入，与实施计划无依赖。

- [ ] **执行 D2**：删除 `AGENTS.md` §10.2 的 `GET/PATCH/DELETE /api/memories` 三行与第 805 行说明；删除 `docs/PRD.md:585-587`；删除 `docs/backend-development-plan.md:655-657`、第 668 行说明、`:1653-1655` 的端点表。
- [ ] `docs/yshopping-parity-audit.md` §5 新增 D2 的撤回登记：参考项目商家侧无任何记忆读写入口，记忆唯一露出是管理员目录树的只读 `memory` 根（`WikiAdminService.java:62`），该点我方已还原。
- [ ] `backend/tests/api/test_openapi_chat_contract.py:189` 的断言**保持不变**，补一行注释说明这三条已按 R9 撤回，把它从「未实现路由的临时守卫」正名为「永久契约」。
- [ ] `plans/2026-08-18-answer-loop-parity-and-demo-data-freshness.md`：68 个 checkbox 按实际完成情况回填。
- [ ] `docs/specs/2026-08-11-mvp-exit-evidence-matrix.md`：R9、Vitest、Playwright 数字停在 2026-08-12，按最新门禁结果更新。
- [ ] `plans/2026-08-12-post-f6-execution-roadmap.md`：阶段 0–2.5 状态回填。

---

## 6. 不做的事

**指标体系 2000+ / Doris / DWD 数仓建设**（§2 表格 #13）。

参考项目这部分是数仓侧工程：`DorisQueryService` 打的是 Doris 宽表，指标来自独立的指标平台。我方按 `AGENTS.md` §9.3 明确「只有数据规模证明 PostgreSQL 不够时才评估 Doris」，当前演示数据量级远未触及。

本项目对应的真实能力是：受控指标语义层（`backend/app/analytics/contract.py` 白名单）、SQL 模板化与参数绑定（R4）、商家数据隔离（R5）、指标口径三级检索。**简历该段建议按这些实际做到的能力重写**，不要写 2000+ 指标和 Doris——架构上不成立，一追问就穿。

---

## 7. 前一版的错误记录（防止重犯）

2026-08-21 的第一版单文件计划（`2026-08-21-parity-and-resume-gap-closure.md`，已废弃）经审查发现 7 处问题。记录在此，**新写任何计划前先读这一节**。

| 错误 | 成因 | 真相 |
| --- | --- | --- |
| 声称参考的压缩端点「没有鉴权体系」 | 只看了 Controller，没看 Filter | `WikiAdminAuthFilter.java:36` 明确把 `/api/wiki/compress` 纳入管理员令牌过滤 |
| 把「历史高频问题」实现成「最近问过的问题去重」 | **只读调用点和 Service，没读那段 SQL** | `AnswerRepository.java:220-232` 是 `GROUP BY question ORDER BY COUNT(*) DESC, MAX(create_time) DESC` |
| `_admin_llm` 接不上费用守卫 | 没查 `LlmCostGuard` 构造签名 | `backend/app/llm/guard.py:36-45` 的 `merchant_id: UUID` 是必填 |
| 日报用 `paying_user_count` 对应「下单用户量」 | 看展示名相近就当同一指标 | 我方实现带 `filter(paid_at is not null)`，参考的 `order_user_cnt_1d` 口径更宽 |
| 日报用 `float` 存金额 | 没查 PRD 的数据规则 | `docs/PRD.md:726`「金额使用 Decimal，不使用浮点数」 |
| 日报响应缺 `answer_id` | 没查前端计划 | `docs/frontend-development-plan.md:897` 要求返回 `answer_id` 以复用反馈接口 |
| 计划称可复用 `app/jobs/seed_demo_rolling.py` 与 `railway.cron.json` | **抄了描述另一分支状态的交接文档** | 这些文件在本分支不存在；它们属于从未合并的 `feature/answer-loop-demo-refresh` |
| 用了不存在的测试夹具 `merchant_client` / `anonymous_client` | 凭印象写夹具名 | `backend/tests/conftest.py:119` 只有 `client` |

**两条根因，都是拿二手来源当一手事实**：

1. **凭调用点反推被调用方的语义**——要读实现，尤其是 SQL；
2. **照抄描述其他分支状态的文档**——交接单里的「已齐」只对它自己那个分支成立，用之前先 `ls`。

写计划时凡是出现「参考项目是…」「我方已有…」，都必须有一条当场跑过的 Read/Grep 作为依据。
