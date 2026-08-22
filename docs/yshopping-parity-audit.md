# 参考项目还原度审计（R9，持续更新的第一轮全局审计）

> 首次生成：2026-08-09；最近核对：2026-08-12
> 依据：`AGENTS.md` R9「参考项目是需求基准，冲突时改我们的文档」
> 审计对象：`yshopping-merchant-ai 4/yshopping-merchant-ai`（只读）对照 `backend/` + `frontend/`
> 本文件只登记差异，不做修改决策；处置优先级由用户拍板后写入各阶段计划。

---

## 1. 判定标准

每条差异标注三类之一：

| 标记 | 含义 |
| --- | --- |
| 🔴 **真实缺口** | 对应阶段已经收口，但参考项目里存在的行为我们没有实现 |
| 🟡 **阶段未到** | 参考项目有，我们的计划里也有，只是排在尚未开工的阶段 |
| ⚪ **有意偏离** | 我们与参考项目不同且判断为改进或等价替代，需登记理由 |
| ❓ **待核实** | 本轮未逐行读完，需要专门一轮才能下结论 |

阶段基线：后端 B0–B7、前端 F0–F6 的代码与本地门禁已经在
`feature/integrate-b7-f4` 收口；该分支已推送到 `origin`，但尚未合入 `main`。
Railway 控制台部署与线上验收、B8/B9、F7–F9 尚未完成。R9 阶段 B 是 B7/F6 之后的还原度整改，
不应被误记成既有阶段尚未收口。

---

## 2. 结论摘要

本轮逐个对照了参考项目的 22 个 service、3 个 graph 类、7 个前端组件与 2 个主应用。

- 🔴 真实缺口 **6 项**，全部集中在 B3 意图契约、B4 指标口径和 F2/F3 会话渲染；
- 🟡 阶段未到 **4 项**，与既有计划一致，无需处置；
- ⚪ 有意偏离 **3 项**，其中 2 项是我们优于参考项目的增强；
- ❓ 待核实 **5 项**，都是 300 行以上的服务，需要单独一轮逐行对照。

**最重的一项不是指标口径，而是 §3.3 的跨业务查询计划**：参考项目支持「从一笔订单跳到它的退款/商品」这类跨业务域追问，我们的 `QueryIntent` 里连承载它的字段都没有。

---

## 3. 🔴 真实缺口

### 3.1 指标口径契约把 13 个字段压缩成 7 个

**参考**：`service/MetricDefinitionService.java`、`model/MetricDefinitionPayload.java`、`components/MetricDefinitionPanel.vue`
**我们**：`backend/app/metrics/catalog.py`、`backend/app/schemas/metric.py`、`frontend/src/components/insights/MetricDefinitionPanel.vue`

缺失字段：`sqlMeaning`（**库里 `metric_definitions.sql_definition` 已有真实值，只是没出口到 API**）、
`dimensions`、`reportUrl`、`databaseName`、`tableName`、`generated`、`notice`。
另有一处语义降级：`source` 在参考项目是命中层级枚举，我们退化成了自由文本。

**状态：已修复。** 正式目录、受控字段注释和模型候选均返回双口径、维度、来源库表、来源枚举、生成标记与链接；链接经后端与前端双重 HTTP/HTTPS 校验，历史 JSONB 回放只补安全默认值。

### 3.2 指标口径三级检索缺中间一级

**参考**：`MetricDefinitionService.resolve()` 依次尝试 指标平台元数据 → Doris 字段 `COLUMN_COMMENT` → LLM 生成。
**我们**：`catalog.py` 已按 正式目录 → 受控字段注释 → LLM 候选三级解析；字段注释键、表名与 B4 白名单同源校验，前两级均不调用 LLM。

第二级的价值不是兜底，而是**它产出的 SQL 口径由后端确定性拼装、不经过模型**。少了这一级，
目录未命中时会直接掉到 LLM，把本可以确定性回答的口径交给模型编，与 PRD §10「不把生成口径
标记为正式口径」的意图相悖。PRD §10 已补上三级来源表。

### 3.3 跨业务查询计划

**状态：✅ 已修复（R9 Task 11，2026-08-12）。** `QueryIntent.cross_business_plan` 只允许
`ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS` 和受字符集、长度约束的
`sub_order_no`。嵌套计划非法时，前置校验器清除计划、白名单层添加固定说明，基础意图保持有效；
计划缺失正常走普通查询。执行层始终先以已验证 `merchant_id` 解析 `orders.order_no`，再按固定 ORM
关联读取订单项、退款、商品。无法在当前商家范围解析订单时，不区分“不存在”和“属于其他商家”，而是回退
普通商家明细并显示说明，从而不形成跨商家订单号探测通道。关联结果及 CSV 导出均重放同一受控计划。

**参考**：`QuestionIntent.crossBusinessPlan` / `planType` / `extractedSubOrderId`，
由 `SemanticLayerService` 的跨业务校验方法校验，白名单三种计划：
`ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS`。

**我们**：已在 `backend/app/intent/models.py`、`app/services/safe_query.py` 和
`app/repositories/analytics.py` 完成受控计划、商家范围解析、固定关联结果与降级说明；
`ExportService` 会以保存的计划安全重放 CSV。单元与 PostgreSQL 集成测试覆盖三种计划、非法对象、
跨商家订单、普通查询降级及导出重放。

### 3.4 「纯明细只出表格」的行为缺失

**状态：✅ 已修复（R9 Task 10，2026-08-12）。** `QueryIntent.analysis_requested` 仅作为内部
结构化意图字段；`DETAIL && !analysis_requested` 不调用回答 / Reviewer 生成路径，强制 `answer == ""`、
建议为空，同时保留既有安全查询、表格、截断和导出。`ChatResponse`、前端 Adapter 与 `ChatMessage` 均校验或
渲染该形态；Answer payload 与正文为空的 `ASSISTANT` 会话消息均正常保存，以支持历史详情重放；前端不渲染空正文卡片，但仍显示表格及其元数据。
回归入口：`backend/tests/unit/schemas/test_chat.py`、`backend/tests/unit/agent/test_graph_query_data.py`、
`backend/tests/unit/services/test_chat_service.py`、`frontend/src/api/adapters/chat.spec.ts`、
`frontend/src/components/chat/ChatMessage.spec.ts`。

**参考**：`QuestionIntent.tableOnlyDetail` / `analysisRequested`，
`SemanticLayerService.inspectInput()` 对 `DETAIL` 分流：
用户没要求分析时置 `tableOnlyDetail=true`，`outputMatchesIntent()` 进一步**强制此时 `answer` 必须为空**，
`repairAnswer()` 把非空正文清成空串。

**我们**：已按上述语义还原；「给我看最近 20 笔订单」只显示表格，「分析最近 20 笔订单」才生成正文与建议。

### 3.5 LLM 生成指标（按维度分组的临时指标）缺失

**参考**：`QuestionIntent.generatedDetailMetric` 及 6 个配套字段，
`SemanticLayerService.validateGeneratedMetric()` 只放行 `spu_id` / `address_city_name` 两个分组列
（或带值的城市筛选），否则整条意图打成 `INVALID`。
`MetricDefinitionService.metricSourceTable()` 据此把口径来源表从画像表切到明细表。

**我们**：已实现 `GeneratedMetricPlan`。模型仅可给出展示名称、单位和受限的分组/筛选形状；后端按已验证的交易或退款类别选择固定 SQLAlchemy 聚合模板，所有商家范围和参数均由后端注入。计划形状非法时整条意图固定为 `INVALID` / `UNKNOWN`，不会降级为普通指标查询。

### 3.6 思考步骤在完成态和历史态回放

**状态：✅ 已修复（R9 Task 8，2026-08-12）。** 运行中仍只显示当前步骤；完成态则按接收顺序
完整列出步骤。`GET /api/conversations/{id}` 已为助手消息返回脱敏 `answer_payload`，包含
`answer_id`、`answer_mode`、`thinking_steps`、质量状态/备注、当前反馈状态和表格元数据。

该载荷明确不含 `data_rows`、导出 URL 或签名字符串；历史明细只展示列数、总行数和截断信息，
引导用户重新提问取得最新数据。前端仅在同时收到回答 ID 与服务端反馈状态时开放历史反馈操作，
不会用本地默认值覆盖既有反馈。回归覆盖位于 `backend/tests/api/test_conversations.py`、
`frontend/src/components/chat/ChatMessage.spec.ts` 和 `frontend/src/stores/chat.spec.ts`。

### 3.7 两阶段意图提示词丢失了输出契约

**状态：✅ 已修复（2026-08-17）。** 本条是第 6 节「❓ 待核实」中 `LlmIntentAnalysisService`
一项完成逐条对照后的结论，已从待核实升级为真实缺口并修复。

**参考项目**：`LlmIntentAnalysisService` 用**同一个提示词**服务两个阶段
（`recognize()` 与 `understand()` 都走 `analyze()` → `buildPrompt()`），差别只在注入的
`baseIntent`（首轮为空，二轮是上一阶段结果且标注「仅供复核」）与 wiki（索引层 vs 业务域正文）。
该提示词完整声明了输出契约：逐个列出 `intentType` / `category` / `answerMode` 的可选值
（`buildPrompt` 第 191–193 行）、给出含全部字段的 JSON 示例（第 207–234 行）、附 6 条编号约束
（第 236–247 行）；系统提示词写明「必须只输出 JSON 对象，不要输出 Markdown」。

**我们（修复前）**：移植时把它拆成 `CLASSIFY_SYSTEM` + `UNDERSTAND_SYSTEM` 两个独立提示词，
契约整套丢失。`classify` 只剩一句「输出 answer_mode、category、intent_keywords JSON」，
`understand` 只剩「输出完整 QueryIntent JSON」。所有自动化测试用 `FakeLlmClient` 返回预写好的
合法 JSON，因此这个缺口在测试里完全不可见。

**线上后果（2026-08-17 首次真实 `deepseek-v4-flash` 调用实测）**：

- `classify` 返回 `answer_mode="trend_query"`、`category="退款退货域"`；`_answer_mode` /
  `_category` 遇非法值**静默回落**成 `CHAT` / `UNKNOWN`，不抛异常。而 `llm_analyzed=False`
  时 `understand` 直接短路，第二阶段根本不执行；
- `understand` 返回 `{"intent":…,"business_domain":…,"metrics":[…],"filters":[…]}`，
  `QueryIntent` 的 `extra="forbid"` 判出 5 条校验错误，三次重试全废；
- 模型不知道当天日期，问「最近 7 天」返回 2025-03-14~2025-03-20。`validate_intent` 只钳制
  上界与跨度、不纠正合法但错误的历史区间，查询落在无数据时段，表现为「查不到」而非报错。

净效果：每次提问都真实计费（`llm_usage` 全部记 `SUCCEEDED`，DeepSeek 确实正常响应），
用户却只得到兜底文案「已完成结构化理解。」。

**修复**：按参考项目的形式补齐两个提示词——枚举取值表、完整 JSON 示例、系统提示词禁 Markdown，
并把业务当天日期注入 `understand`。字段名仍用我方 `QueryIntent` 的 snake_case：那是内部 LLM
契约，与 `docs/backend-development-plan.md` §8 管辖的对外 API 契约无关。

回归覆盖：`backend/tests/unit/intent/test_prompts.py`（8 条，期望值全部从 `QueryIntent`
字段定义与枚举推导，并把提示词里的 JSON 示例抠出来真正校验，防止示例与 schema 脱节）。
真实模型验收：METRIC / DETAIL / RULE 三类问题两阶段全部通过，日期区间正确。

**遗留**：指标口径 catalog 的提示词（`app/metrics/catalog.py`）只声明了三个字段名、未列枚举，
未做真实模型验收；`knowledge_documents` 线上为 0 行，规则类问题没有知识依据。

### 3.8 「猜你想问」未按商家历史高频问题排序

**状态：✅ 已于 2026-08-21 修复。** 参考项目的 `topCategoryQuestions` 按问题出现次数降序、
同频次按最近回答时间降序；我方 `AnswerRepository.top_category_questions()` 现将聚合、分类过滤、
成功状态过滤和上限全部下推到 PostgreSQL，并同时约束 Answer 和 Message 的 `merchant_id`。
图节点在历史结果非空时仅替换 `suggestions`，静态 `suggestion_alternates` 保留；历史库未注入、
无结果或读取异常时均安全回落，不影响主回答。

---

## 4. 🟡 阶段未到（与计划一致，无需处置）

| 参考项目 | 我们的归属阶段 |
| --- | --- |
| `AttachmentService` / `AttachmentStore` / `ChatMessage.vue` 附件区块 | B8 / F7 |
| `DailyReportService` / `DailyReportCard.vue` | 已于 2026-08-21 完成；附件仍留在 B8 / F7 |
| `MemoryConsolidationService`（商家记忆固化） | B8 |

`ChatMessage.vue` 的 `quality-audit` 质检块与 `message-actions` 反馈操作已在 F5 实现：四种质量状态、校验次数、备注和全部来源均如实展示；采纳、点赞、点踩已接入 B6 反馈端点，并覆盖失败保留、同值重试与并发中止。R9 Task 8 已将质量状态、备注、`answer_id` 和已有反馈状态随脱敏历史载荷返回，因此历史消息同样展示可信质量轨迹和反馈状态；由于详情契约不保存 `analysis_sources`，历史消息不会编造来源标签。

---

## 5. ⚪ 有意偏离（需登记理由）

### 5.1 我们有稳定的 `metric_code`，参考项目没有

参考项目用中文指标名做匹配键（`metrics_name` 大小写不敏感比对）。我们引入英文 `metric_code`
作为唯一内部键，中文名降级为展示字段。**这是修正参考项目的缺陷，不还原**——理由已写在
PRD §10 Metric Catalog 与 §6.2。

### 5.2 我们有 `metric_status`（ACTIVE / DEPRECATED / UNVERIFIED）

参考项目只有 `generated` 布尔。我们额外维护目录状态，且口径端点可查已废弃指标。保留。

### 5.3 推荐问题合并进 `RecommendationPanel`

参考项目有独立的 `SuggestionList.vue`（34 行）。我们把「猜你想问」与经营建议合并在
`components/insights/RecommendationPanel.vue` 内。视觉分区一致，组件边界不同。判定为等价替代。

### 5.4 数字守卫升级为事实校验

参考项目的本地校验不检查回答数字。我方保留确定性守卫，并由后端派生完整时间序列的合计、最新、峰值与变化率摘要供模型引用；这是为了优先阻断可确定识别的编造数字。

### 5.5 演示数据采用稳定目录与增量滚动

参考项目只提供固定三天数据且不刷新。我方把商品目录和业务日事实拆分，同一业务日可重复生成，并为专用演示数据库提供受显式写权限与商家集合校验保护的滚动任务；避免相对时间查询过期。

### 5.6 结构化步骤关闭 thinking

参考实现基于非推理模型。我方对分类、理解、指标口径和 Reviewer 使用结构化 JSON 调用并关闭 thinking，回答生成保留默认推理，以减少结构化步骤的无效 token。

### 5.7 空知识索引下的基础业务域路由

参考实现依赖其运行时 Wiki 提供分类语境。我方在分类提示词中保留交易、退款、工单和平台规则的最小业务域映射，且只在知识索引为空或检索异常时作为基础路由。它不提供规则正文、指标口径或查询字段；这些内容仍只能来自已导入的知识库和后端白名单。2026-08-19 已导入 23 篇知识文档，因此该映射不替代知识检索。

### 5.8 记忆存储介质：文件系统 → PostgreSQL

依据 `AGENTS.md` §8.7，商家记忆存入 `merchant_memories`，不依赖 Railway 临时文件系统。
参考实现的 `ensureNoSymbolicLinks` 没有数据库等价物，故不实现；其余知识路径校验保留给知识库维护后台。

### 5.9 记忆文件名 `isolatedPathSegment()` → `(merchant_id, category)` 唯一约束

数据库没有路径穿越语义，以唯一约束表达同一商家同一分类的全量覆盖；商家范围由查询条件和外键共同约束。

### 5.10 建业务域写占位文档而非空目录

数据库中不存在空目录。创建业务域时，四个固定板块各写一篇 `is_complete=False` 的占位说明，
使目录树可显示且检索层能如实提示资料未完整；这与参考文件系统中的空目录表现等价。

### 5.11 不实现 `SYMLINK_NOT_ALLOWED`

数据库中不存在符号链接，因此无对应攻击面；其余 13 个知识库路径/写入错误码均已实现并有测试。

### 5.12 手动记忆压缩路径偏离

参考项目使用 `POST /api/wiki/compress`。我方有意使用
`POST /api/admin/knowledge/memories/compress`：这是管理员对知识/记忆资源的跨商家写入，
复用现有 `X-Admin-Token` 鉴权并保持 Borough 命名。行为等价，包括按商家和分类读取历史、
优先保留人工 Markdown、覆盖该分类记忆、独立审计先于记忆提交，以及模型不可用时显式返回降级状态。

### 5.13 撤回商家自助记忆 API

参考项目的商家侧没有任何记忆读写入口；记忆仅以管理员知识目录树中的只读 `memory` 根露出
（`WikiAdminService.java:62`）。因此我方撤回原先规划的 `GET`、`PATCH`、`DELETE /api/memories`，
由 OpenAPI 契约测试永久禁止重新暴露这些路径。2026-08-21 用户裁定。

### 5.14 日报路径与响应形状偏离

参考项目使用 `GET /api/daily-report`，我方保留已定义的
`GET /api/reports/daily`；这是 Borough 公共 API 的命名统一选择。参考响应指标使用名称到值的 Map，我方使用带稳定 `metric_code`、展示名称、单位和值的数组，以避免中文指标名作为契约键。

本轮日报不引入定时推送：只在商家请求时对业务时区昨日执行一次幂等物化，避免在未定义推送通道、失败重试和定时任务监控前伪装成完整的定时日报能力。建议也只使用已实际查询的退款、订单与工单信号，不虚构商品排查分支。

---

## 6. ❓ 待核实（需单独一轮逐行对照）

| 参考项目 | 行数 | 我方对应 | 未核实原因 |
| --- | --- | --- | --- |
| `DorisQueryService` | 1050 | `repositories/analytics.py` + `services/safe_query.py` | 数据源不同（Doris vs PostgreSQL），需按「查询能力」而非按代码逐条比 |
| ~~`LlmIntentAnalysisService`~~ | 603 | `app/intent/` | **提示词部分已于 2026-08-17 完成对照，结论见 §3.7（真实缺口，已修复）。** 重试策略仍未逐条比对 |
| `PromptLoopAnalysisService` | 354 | `services/answer_service.py` + `services/review_service.py` | 已确认 `loopStatus`/`loopAttempts`/`loopNotes` 三元组在我方有对应（`quality_status`/`quality_attempts`/`quality_notes`），但校验规则清单未逐条比 |

`AnswerComposeService`(323) / `VisualizationService`(103) / `CsvExportService`(91) /
`FeedbackService`(66) 已确认存在对应实现，字段级差异未逐条比对。

---

## 7. 处置建议

按「用户可感知程度 × 修复成本」排序：

1. **§3.6 思考过程渲染** — 数据已经在 store 里，纯前端改动，成本最低、可见性最高。
2. **§3.1 + §3.2 指标口径** — 文档已改齐，实现链路明确（迁移 → Seed → 三个 Pydantic 模型 → codegen → 面板）。
3. **§3.3 跨业务查询计划** — 需要先补 PRD 条款（当前 PRD 完全没写），是四项里唯一需要新增产品需求的。
4. **§3.5 生成指标** — 已于 2026-08-13 实施：受控计划、交易/退款固定聚合、精确截断、签名 CSV 重放及图表字段映射均已覆盖；全链路 E2E 与最终一致性验收仍由后续 Task 13–14 统一执行。
5. **§6 待核实项** — 建议在各自阶段开工前各做一轮，而不是现在一次性做完。

---

## 8. 本轮未覆盖

- 视觉还原度（`yshopping-prototype` 对照）不在本次审计范围，属于 F1 的人工比对项；
- 参考项目的测试用例未逐条对照；
- `runtime/llm-wiki/` 知识库内容与我方 Seed 知识的覆盖度未比对。

---

## 9. Task 6 参考能力审计（2026-08-12）

本节只记录已读取的参考行为，作为 R9 契约设计输入；参考目录未作任何修改。阶段 A 合并前的
冲突统计为 32 个文本冲突、6 个 add/add 冲突，现已是历史整合事实，不影响本轮能力结论。

| 能力 | 参考证据（均已只读核对） | 输入、校验、输出与失败语义 | 我方状态 |
| --- | --- | --- | --- |
| 双知识库与记忆沉淀 | `WikiMemoryService`、`MemoryConsolidationService`、`MerchantQaLangGraph` | 人工库命中即返回且记忆不参与；未命中才取该商家记忆；记忆强制带 `本轮自动沉淀` 标记；沉淀异步且失败只记日志 | ✅ 已实现，来源经 `analysis_sources` 的 `MEMORY` 对用户可见 |
| 纯明细 | `QuestionIntent`、`LlmIntentAnalysisService`、`SemanticLayerService`、`MerchantQaLangGraph` | 模型仅声明是否要求分析；`DETAIL` 且未要求分析时设 table-only；`repairAnswer()` 清空正文，`outputMatchesIntent()` 强制正文为空。 | ✅ `analysis_requested` 内部字段 + 响应空正文不变量、表格/导出保留、历史 Answer payload 可重放均已实现；空正文助手消息不会渲染为空白卡片。 |
| 跨业务计划 | `QuestionIntent`、`SemanticLayerService`、`DorisQueryService` | 仅 `ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS`；以商家范围和子订单号串行查订单、退款、商品；计划参数非法时移除该计划并记录说明，基础意图继续执行。 | ✅ 已实现受控计划、固定 ORM 路由、商家范围解析、可见降级说明与 CSV 重放；不存在与跨商家订单统一回退，避免存在性探测。 |
| 临时分组指标 | `QuestionIntent`、`LlmIntentAnalysisService`、`SemanticLayerService`、`DorisQueryService`、`MetricDefinitionService`、`VisualizationService`，以及 `DorisQueryServiceTest`、`LlmIntentAnalysisServiceTest`、`MetricDefinitionServiceTest`、`VisualizationServiceTest` | 白名单仅 `spu_id`、`address_city_name`；按交易/退款类别选择固定聚合；城市筛选可替代分组；金额由分转元；非法维度整体 `INVALID`；截断时生成 CSV 与提示；图表只取查询结果已有字段。 | ✅ 已实现受控计划、类别驱动固定 SQLAlchemy 模板、精确截断、签名 CSV 重放与安全图表字段映射；2026-08-13 已由真实 PostgreSQL 浏览器场景验证截断下载、图表和待核验提示；不接受自由公式、自由列名或 `measure` 枚举。 |
| 会话上下文 | `ConversationContextStore`、`ConversationContextStoreTest`、`MerchantQaLangGraph` | 内存中按 `(merchant_id, session_id)` 隔离，TTL 30 分钟；复制意图、查询包、数据行、计划步骤和导出字段；只缓存有效且有数据的轮次；上文分析复用数据但不重新查库。 | ⚪ 我方持久会话优于内存 TTL；但历史详情必须脱敏返回执行载荷，不能返回完整明细行或过期签名 URL。 |
| Reviewer 循环 | `PromptLoopAnalysisService`、`PromptLoopAnalysisServiceTest`、`MerchantQaLangGraph` | 本地校验与独立 reviewer 均通过才 PASS；最多 3 次总尝试后确定性 FALLBACK；loop notes 记录每轮退回原因；纯明细不允许被 loop 生成正文。 | ✅ 我方已有质量状态/次数/备注，R9 Task 8 已随脱敏历史助手载荷回放。 |
| CSV 导出 | `QueryBundle`、`CsvExportService`、`DorisQueryService` | 截断时保存文件名、URL、notice；文件名净化、UTF-8 BOM、列顺序稳定；参考实现未实现公式注入和签名过期。 | ✅ 我方签名、过期、公式防护更强；生成指标下载会重放已签名的受控计划，拒绝被篡改的计划、类别或列集合。 |
| 图表 | `VisualizationService`、`VisualizationServiceTest` | 仅 METRIC 且有行时启用；趋势用 `pt/value`，分组用白名单维度；金额优先金额列，单一筛选值禁用饼图。 | ✅ 安全图表原则一致；生成指标仅从固定结果列选择金额字段，字段映射已有测试。 |
| 知识库维护后台 | `WikiAdminService`、`WikiAdminController`、`KnowledgeBaseApp.vue` | 三根目录、业务域固定四板块、路径校验、ETag 乐观锁、管理员令牌独立于商家 Token，记忆仅可读。 | ✅ B9/F8 已实现；数据库路径策略保留参考的 13 个可适用错误码，业务域用不完整占位文档表达空目录。 |

`SemanticLayerService`、`CsvExportService`、`QueryBundle` 与 `MerchantQaLangGraph` 在参考测试目录没有同名单测；
已如实记录为“源代码行为已核对”，未把不存在的测试虚构为证据。其余表列测试只证明已覆盖的样例，
不替代后续 Python/TypeScript 的回归测试。
