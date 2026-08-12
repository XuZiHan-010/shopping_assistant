# 参考项目还原度审计（R9）

> 生成日期：2026-08-09
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

阶段基线：后端 B0–B7 已收口，前端 F0–F5 已在 `feature/integrate-b7-f4` 收口。
B8/B9、F6–F9 尚未开工。

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

**状态：文档已按 R9 改齐（PRD §6.3/§10/§11.3、前后端计划），代码未动。** 详见 `docs/project-progress.md`。

### 3.2 指标口径三级检索缺中间一级

**参考**：`MetricDefinitionService.resolve()` 依次尝试 指标平台元数据 → Doris 字段 `COLUMN_COMMENT` → LLM 生成。
**我们**：`catalog.py` 只有 正式目录 → LLM 两级。

第二级的价值不是兜底，而是**它产出的 SQL 口径由后端确定性拼装、不经过模型**。少了这一级，
目录未命中时会直接掉到 LLM，把本可以确定性回答的口径交给模型编，与 PRD §10「不把生成口径
标记为正式口径」的意图相悖。PRD §10 已补上三级来源表。

### 3.3 跨业务查询计划完全缺失

**参考**：`QuestionIntent.crossBusinessPlan` / `planType` / `extractedSubOrderId`，
由 `SemanticLayerService.validateCrossBusinessPlan()` 校验，白名单三种计划：
`ORDER_TO_REFUND`、`ORDER_TO_GOODS`、`ORDER_REFUND_GOODS`。

**我们**：`backend/app/intent/models.py` 的 `QueryIntent` 共 10 个字段，**没有任何一个能承载它**。
grep `cross_business` / `plan_type` 在 `backend/app` 与 `frontend/src` 下零命中。

这是一条完整的产品能力：用户拿着一个子订单号问「这笔订单退款了吗」「这笔订单买的什么商品」，
参考项目会把它路由成受控的跨表计划，且缺少 `extractedSubOrderId` 时整条计划会被拒绝而不是降级
成模糊查询。我们目前既不支持、PRD 里也没有对应条款——**这属于 PRD 漏写，按 R9 应当补写**。

### 3.4 「纯明细只出表格」的行为缺失

**参考**：`QuestionIntent.tableOnlyDetail` / `analysisRequested`，
`SemanticLayerService.inspectInput()` 对 `DETAIL` 分流：
用户没要求分析时置 `tableOnlyDetail=true`，`outputMatchesIntent()` 进一步**强制此时 `answer` 必须为空**，
`repairAnswer()` 把非空正文清成空串。

**我们**：`DETAIL` 模式恒定输出分析正文。`table_only` / `analysis_requested` 在我方代码零命中。

差异是用户可见的：参考项目里「给我看最近 20 笔订单」只返回表格，我们会额外附一段模型生成的
分析文字。PRD §11.3 目前也没有区分这两种 `DETAIL`。

### 3.5 LLM 生成指标（按维度分组的临时指标）缺失

**参考**：`QuestionIntent.generatedDetailMetric` 及 6 个配套字段，
`SemanticLayerService.validateGeneratedMetric()` 只放行 `spu_id` / `address_city_name` 两个分组列
（或带值的城市筛选），否则整条意图打成 `INVALID`。
`MetricDefinitionService.metricSourceTable()` 据此把口径来源表从画像表切到明细表。

**我们**：完全没有这个概念。指标只能来自 `METRIC_SPECS` 白名单，模型无法请求「按商品分组的临时指标」。

这与我们的 R4 并不冲突——参考项目同样是白名单校验、模型不写 SQL——但确实少了一类问题的支持能力。

### 3.6 思考过程只渲染最后一步

**参考**：`components/ChatMessage.vue` 渲染 `thinking` 区块，逐条列出 `thinking-step`。
**我们**：`frontend/src/stores/chat.ts` 完整累积了 `steps`，但
`components/chat/ChatMessage.vue:20` 只取 `props.message.steps.at(-1)?.label`，
其余步骤累积后从未渲染。

我们的 13 个节点标签（`load_context` … `persist_answer`）比参考项目更细，**数据是全的，只是没展示**。
这是 F2/F3 已收口阶段里的渲染缺口，不是后端问题。

---

## 4. 🟡 阶段未到（与计划一致，无需处置）

| 参考项目 | 我们的归属阶段 |
| --- | --- |
| `AttachmentService` / `AttachmentStore` / `ChatMessage.vue` 附件区块 | B8 / F7 |
| `DailyReportService` / `DailyReportCard.vue` | B8 / F7 |
| `MemoryConsolidationService`（商家记忆固化） | B8 |
| `WikiAdminService` / `WikiAdminController` / `KnowledgeBaseApp.vue` | B9 / F8（我方已有 `KnowledgeBaseView.vue` 骨架，完成度见 ❓5.5） |

`ChatMessage.vue` 的 `quality-audit` 质检块与 `message-actions` 反馈操作已在 F5 实现：四种质量状态、校验次数、备注和全部来源均如实展示；采纳、点赞、点踩已接入 B6 反馈端点，并覆盖失败保留、同值重试与并发中止。当前会话详情仍不返回完整助手回答载荷、`answer_id` 和已有反馈状态，因此历史消息不显示质量轨迹与反馈按钮；该契约边界归阶段 B Task 8 修复，且必须同时补 `answer_id` 与当前反馈状态，避免覆盖已有反馈。

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

---

## 6. ❓ 待核实（需单独一轮逐行对照）

| 参考项目 | 行数 | 我方对应 | 未核实原因 |
| --- | --- | --- | --- |
| `DorisQueryService` | 1050 | `repositories/analytics.py` + `services/safe_query.py` | 数据源不同（Doris vs PostgreSQL），需按「查询能力」而非按代码逐条比 |
| `LlmIntentAnalysisService` | 603 | `app/intent/` | 两阶段意图识别的提示词与重试策略未逐条比对 |
| `WikiMemoryService` | 441 | `app/knowledge/` | 知识检索分层与记忆写入策略未比对 |
| `PromptLoopAnalysisService` | 354 | `services/answer_service.py` + `services/review_service.py` | 已确认 `loopStatus`/`loopAttempts`/`loopNotes` 三元组在我方有对应（`quality_status`/`quality_attempts`/`quality_notes`），但校验规则清单未逐条比 |
| `WikiAdminService` | 498 | F8/B9 未开工 | 阶段未到，但需在开工前先做一次逐条对照 |

`AnswerComposeService`(323) / `VisualizationService`(103) / `CsvExportService`(91) /
`FeedbackService`(66) 已确认存在对应实现，字段级差异未逐条比对。

---

## 7. 处置建议

按「用户可感知程度 × 修复成本」排序：

1. **§3.6 思考过程渲染** — 数据已经在 store 里，纯前端改动，成本最低、可见性最高。
2. **§3.1 + §3.2 指标口径** — 文档已改齐，实现链路明确（迁移 → Seed → 三个 Pydantic 模型 → codegen → 面板）。
3. **§3.4 纯明细只出表格** — 需要先在 PRD §11.3 区分两种 `DETAIL`，再改意图契约与回答组装。
4. **§3.3 跨业务查询计划** — 需要先补 PRD 条款（当前 PRD 完全没写），是四项里唯一需要新增产品需求的。
5. **§3.5 生成指标** — 依赖 §3.3 的意图契约扩展，建议同批做。
6. **§6 待核实项** — 建议在各自阶段开工前各做一轮，而不是现在一次性做完。

---

## 8. 本轮未覆盖

- 视觉还原度（`yshopping-prototype` 对照）不在本次审计范围，属于 F1 的人工比对项；
- 参考项目的测试用例未逐条对照；
- `runtime/llm-wiki/` 知识库内容与我方 Seed 知识的覆盖度未比对。
