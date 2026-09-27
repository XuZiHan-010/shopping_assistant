# 参考项目还原 + 简历口径能力：交付路线图与裁定清单

> **这不是可执行计划。** 本文件只做三件事：锁定范围、给出归类证据、列出待裁定问题。
> 每一项的实际实施必须另建独立的可执行计划（含文件、迁移、契约、测试与验收步骤）后才能开工。
> **勾完本文件不等于功能交付**，完成判据见 §10，那里把「路线图完成」和「能力交付」分开计。

**目标：** 把「参考项目已实现但我方缺失」的能力补齐，并交付「简历口径已声明但参考项目没有」的自研能力。

**依据：** `docs/yshopping-parity-audit.md`、`plans/2026-08-21-gap-roadmap.md` §2 与 §2.1（简历口径 V2/V3/V4 原文）、`docs/PRD.md`、`docs/backend-development-plan.md`、`docs/project-progress.md`。

**修订记录：** 2026-08-22 初稿经审查发现 7 处问题（归类错误、误召回风险、Cron 资源冲突、重开已裁定决策、路线图伪装成交付计划等），已逐条核实为真并改正；核实证据见各节「实测证据」。

---

## 1. 全局约束

- **R1** 面向用户内容中文；**R2** 提交/推送/PR 需用户明确许可；**R3** 真实 LLM 调用前须说明模型、次数与预计费用并获同意，单元测试一律 mock；**R4** 模型不得输出或执行 SQL，补齐结果只能落到已验证的 `metric_code`/维度枚举；**R5** 商家隔离；**R7** 降级必须可见；**R8** `yshopping-merchant-ai 4/` 只读；**R9** 参考项目是需求基准；**R10** 计划写 `plans/`、设计说明写 `docs/specs/`。
- 契约变更顺序：`docs/PRD.md` → `docs/backend-development-plan.md` §8 → 前后端计划与 `AGENTS.md` 索引 → Pydantic Schema → OpenAPI/`docs/api.md` → TypeScript 类型 → 前端渲染 → 测试。
- **权威文档已裁定的事项不得在设计说明里重开**。写任何 `docs/specs/` 之前先检索 PRD 与后端计划是否已有结论；只对**真正未定**的参数提问。（初稿在附件一项上违反过这条，见 §7。）
- 门禁：

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app

cd ../frontend
npm run codegen:check
npm run test -- --run
npm run typecheck
```

- **真实 PostgreSQL 全量 pytest 会清空 `knowledge_documents` 与经营数据表**，依赖种子数据的验证前先重跑 `scripts/import_wiki.py` 与 `scripts/seed_demo_analytics.py`。

---

## 2. 范围裁定

| # | 能力 | 参考项目 | 简历 | 我方现状 | 归类 |
| --- | --- | --- | --- | --- | --- |
| 1 | 无效意图不落记录表 + 引导提工单 | ✅ `shouldPersist == VALID` / `invalid()` | ✅ | ❌ | **A 还原** |
| 2 | 附件上传 + OCR/解析 | ✅ `AttachmentController` / `AttachmentService` | ✅ V3 | ❌ 零实现 | **A 还原**（路线已裁定） |
| 3 | 日报定时推送 | ✅ `DailyReportScheduler`（10:00 Asia/Shanghai） | ➖ | ❌ 端点已交付、推送未做 | **A 还原** |
| 4 | 跨业务域知识检索 | ❓ 须再读参考确认 | ➖ | ❌ 分类锁死 | **待核实后归类** |
| 5 | 知识检索召回质量增强 | ❌ **参考同样命不中** | ➖ | 与参考等价 | **⚪ 增强，非还原** |
| 6 | 语义层校验闭环（读 Session + 记忆再分析） | ❌ 仅无状态重试 | ✅ V2 | ❌ | **B 自研** |
| 7 | 新词语义层补齐 | ❌ | ✅ V2 | ❌ | **B 自研** |
| 8 | 简单问题绕过大模型省 Token | ❌ | ✅ | ❌ | **B 自研** |
| 9 | Chat BI 衡量仪表盘 | ❌ | ✅ | ⚠️ 仅分散字段 | **B 自研** |

**两类流程不同：**

- **A 类**：参考项目已把设计做完。**读它的实现照着还原，不重新设计**；无法还原时才登记偏离到 `docs/yshopping-parity-audit.md` §5。
- **B 类 / ⚪ 增强**：R9 提供不了答案。必须先写 `docs/specs/` 设计说明、列出待裁定问题、取得用户裁定，再出实施计划。**不得自行假设产品决策就开写代码。**

### 2.1 明确不做

- **指标 2000+ / Doris / DWD 数仓建设**（简历有）：`AGENTS.md` §9.3 明确只有数据规模证明 PostgreSQL 不够时才评估 Doris，当前演示数据量级远未触发。`plans/2026-08-21-gap-roadmap.md` §6 已裁定。

---

## 3. 裁定结果（2026-08-22 用户已裁定，正本见 `docs/project-progress.md`「下一步」7/8/8b/16）

| | 裁定 | 关键边界 |
| --- | --- | --- |
| D1 | ✅ 做，作为⚪我方增强 | 确定性相关性评分 + TopN；不引入分词/向量库/额外 LLM；必测同域干扰文档反例 |
| D2 | ❌ 不做通用多域召回 | 仅锁 `PLATFORM_RULE` 全库规则视图；**经核实我方已等价，只需补回归测试** |
| D3 | ✅ 做，选方案（b） | 两期数据由后端查询与计算，模型只表达比较意图；须同步 **4 处**文档承诺 |
| D4 | ✅ 维持 10 次 / 25,000 token | 新语义层复用现有重试槽，不新增必经 LLM 调用 |

以下小节保留裁定时的证据与备选方案，供实施计划引用；**结论以上表为准**。



### D1 · 知识检索召回质量要不要做增强

**实测证据（2026-08-22，零 LLM）：**

- 参考实现 `WikiMemoryService.matchesIntentKeywords`（`WikiMemoryService.java:287-300`）是「整词子串命中 → 去后缀词干子串命中」，**没有分词、没有模糊匹配**；我方 `retrieval.py` 的 `_matches_keywords` 与之**逐条等价**。多个关键词之间是 OR（命中任一即真），不是 AND。
- 因此「商品上架有哪些规则要求」这道题**在参考项目里同样命不中**。这不是还原缺口，我方与参考行为一致。
- 初稿曾提议「复合词二元拆分」，**实测会造成误召回**：在同域三篇文档（商品规则 / 商品定价 / 商品库存）上，"商品上架"拆出的"商品"命中全部三篇，关键词过滤在该域内退化为空过滤。初稿的单文档测试无法发现这一点。

**待裁定**：（a）不做，接受与参考一致的召回率，把 T7 的 RULE 题记为「参考同款限制」；（b）作为⚪增强立项，先出设计说明，方案候选包括**中文分词**（引入分词依赖）、**相关性排序取 TopN**（不再是布尔过滤）、**多域召回**（见 D2），并且**必须包含「同域相关文档 + 同域干扰文档」的反例测试**，证明增强没有把过滤变成空过滤。

**未裁定前不改 `retrieval.py`。**

### D2 · 跨业务域检索

「商品上架有哪些规则要求」横跨 GOODS 与 PLATFORM_RULE。实测：`商品规则.md`（GOODS）含「商品」「上架」不含「规则」；`平台规则详解.md`（PLATFORM_RULE）含「规则」不含「商品」「上架」。真实 T7 运行时分类器判成 PLATFORM_RULE，**因此够不到真正能回答的那篇**。

**开工前必须先读参考项目**确认它对跨域问题的真实处理（`WikiMemoryService.categoryKeywords()` 与调用方只传单一 category 的语义），再决定归 A 还是⚪。任何方案都必须保住既有测试 `test_domain_retrieval_narrows_results_by_intent_keyword` 编码的 R7 边界：关键词与本域毫不相干时如实报未命中，不得把无关文档当依据。

### D3 · 环比/同比：三处文档承诺必须一并处置

**实测证据**：参考项目**没有**环比/同比实现（全仓库无对应逻辑，`QuestionIntent.referencesPriorData` 是「分析上文明细」语义）；简历 V2/V3/V4 原文**也未声明**。但我方文档已经承诺：

- `AGENTS.md:225`：主要能力列「趋势、分类、**同比或环比**分析」；
- `docs/frontend-development-plan.md:765`：要求趋势文字含「环比 +12%」；
- T7 出口判据含一道环比题（2026-08-22 实测两次均降级，根因是查询层无两期对比能力，`_validate()` 正确拦下了模型编造的对比数字）。

**待裁定，三选一，且每一项都要求同步处置上述文档承诺：**

（a）**不做**——必须同步删除/降级 `AGENTS.md:225` 与前端计划:765 的承诺，并调整 T7 判据；不能只改判据留着文档写着能做。
（b）**作为⚪增强立项**——出设计说明，定义 `QueryIntent` 如何表达对比周期、查询层如何一次取两期、`_validate()` 如何放行由两期真实数值算出的百分比（而非放宽成允许任意数字）。
（c）**明确延期**——记为已知延期状态而非交付终态，文档承诺同步标注「未实现」。

### D4 · 语义层三项的预算处置

`MAX_INTENT_RETRIES=2` 与 `QUALITY_MAX_ATTEMPTS` 独立但共用同一个 `LlmBudget`，当前最坏路径 10 次、`MAX_LLM_CALLS_PER_REQUEST=10` 正好卡满。

**上限是安全约束，不随功能自动上涨。** 新增调用时的正确顺序是：① 先尝试重排或合并现有调用以腾出预算；② 确实腾不出时，做费用评估（最坏路径次数、单请求 token、每日预算、最坏日费用）；③ 提交用户裁定；④ 获准后同步更新 `MAX_LLM_CALLS_PER_REQUEST`、`MAX_LLM_TOKENS_PER_REQUEST`、`LLM_DAILY_BUDGET_TOKENS` 与 `docs/deployment.md`。**不得把「提高上限」写成实施步骤的必然动作。**

---

## 4. 排序

```text
可先动（无待裁定前置）：
  §5 无效意图与提工单（A 类还原，须先解幂等冲突）
  §6 日报定时推送（A 类还原，须建独立 Cron Service）
  §7 附件 + OCR（A 类还原，路线已裁定，只需补未定参数）

须先裁定：
  D1/D2 → 知识检索增强
  D3    → 环比处置
  D4    → 语义层三项（§8）
  §9    → Chat BI
```

每一项开工前另建 `plans/2026-08-2X-<name>.md` 可执行计划。

---

## 5. 无效意图不落记录表 + 引导提工单（A 类还原）

**参考实现（已核实）：**

- `graph/MerchantQaLangGraph.java:235`：`state.setShouldPersist(state.getIntent().getIntentType() == IntentType.VALID)` —— 只有 `VALID` 意图才持久化。
- `service/AnswerComposeService.java:63`：`invalid()` 返回「请提工单进行人工咨询」。

**我方现状**：`backend/app/repositories/conversation.py` 对**每个**请求都建 Answer 行。

**核心冲突（实施计划必须先解决）**：我方 `client_request_id` 的幂等唯一约束**依赖 Answer 行**，直接照搬「不落库」会破坏幂等重放。**这是"无法直接照搬"的情形，按 §2 的 A 类规则应设计独立幂等记录并登记偏离到 `docs/yshopping-parity-audit.md` §5**，而不是当作自研随意改设计。可行方向：保留行但加字段标记不进统计与记忆；或另建轻量幂等表承载 `client_request_id`。两者都要有反例测试证明重放语义不变。

**引导文案**属纯文案还原，成本极低，可与上述改动同批。

---

## 6. 日报定时推送（A 类还原）

**参考实现**：`scheduler/DailyReportScheduler.java`，`@Scheduled(cron = "0 0 10 * * *", zone = "Asia/Shanghai")`，只推配置里的单个商家，**推送出口就是打一行日志**。

**资源冲突（初稿漏掉，已核实）**：`backend/railway.cron.json` 现有内容为——

```json
"startCommand": "python -m app.jobs.seed_demo_rolling",
"cronSchedule": "10 16 * * *"
```

即已被演示数据滚动 Seed 占用（`10 16 * * *` UTC = 次日 00:10 Asia/Shanghai）。**Railway 每个 Cron Service 绑定一个 schedule 和一个 start command**，因此日报推送**必须新建独立配置文件**（如 `backend/railway.daily-report-cron.json`）**与独立 Service**，不得覆盖或复用现有 seed Cron。

**实施计划必须写清：**

- **Cron 表达式**：`10:00 Asia/Shanghai` = `0 2 * * *`（UTC）。参考的 `0 0 10 * * *` 是 Spring 六段式带 zone，不能直接抄；
- **推谁**：参考只推单个商家；我方推全部 `is_demo=True AND status='ACTIVE'`，逐个独立事务。这是有意偏离，须登记 §5；
- **复用同一入口**：Cron 与用户 GET 必须调用同一个 `get_or_create_daily_report()`，否则同日两条路径可能产出不同 payload；
- **总超时与数据库连接释放**：任务必须有整体超时，结束时显式释放连接池；
- **部分商家失败后的最终退出码**：定义清楚"3 个商家挂了 1 个"时进程退 0 还是非 0，以及它如何影响告警；
- **重叠执行**：上一次未结束时本次如何处置（跳过 / 等待 / 并行），Railway Cron 不保证不重叠；
- **日志告警由谁消费**：推送出口是结构化日志，须写明谁看、失败如何被发现，否则等于没有推送；
- **不跑迁移**：缺表时失败退出而不是自动修库；
- **不复用 `backend/railway.json`**（带健康检查与 `preDeployCommand`，一次性任务必然失败）。

**遗留控制台动作**：建 Service、配变量、手工触发首次执行——需用户操作。

---

## 7. 附件上传 + OCR（A 类还原，路线已裁定）

**参考实现**：`controller/AttachmentController.java`、`service/AttachmentService.java`。

**以下已由权威文档裁定，设计说明不得重开：**

- **存储介质 = 对象存储**：`docs/PRD.md` §7.2 P1 明列「对象存储」，附件流程明写「保存对象存储」。**不再讨论 `bytea`。**
- **OCR 路线 = 默认本地 OCR**：`docs/backend-development-plan.md` 明确「**默认使用本地 OCR**（如 PaddleOCR 或 Tesseract），**不默认调用收费的多模态模型**」，并规定改用收费模型须先走 R3。**不再讨论是否用 DeepSeek 视觉。**
  - 补充事实：我方约定的唯一云端提供商是 DeepSeek，其 Chat Completions 的 `content` 是文本字符串，**不能假定可直接做视觉 OCR**；参考项目的 `visionOcr` 走的是它自己的 LLM 客户端，与我方的模型约定不同。这进一步支持「本地 OCR」这条既定路线。（我未独立联网核实 DeepSeek 当前是否已支持图片输入；但既定路线是本地 OCR，该结论不依赖这一点。）
- **扫描版 PDF 必须走 OCR**：初稿写「PDF 走 PyMuPDF 无此问题」是错的——扫描版 PDF 没有文本层，PyMuPDF 取不到文字，仍需 OCR。实施计划须区分**文本层 PDF**（PyMuPDF）与**扫描版 PDF**（先渲染再 OCR），并定义如何判定。

**真正未定、需要在设计说明里回答的（后端计划里仍是未勾选项）：**

1. 输入限制：单图最大边长/最大像素/最大文件大小/PDF 最大页数的**具体数值**；
2. 单次 OCR 超时与总超时的**具体数值**；
3. `OcrAdapter` Protocol 的接口形状与 `FakeOcrAdapter` 的注入点（CI 不跑真实 OCR）；
4. 识别结果里手机号/身份证/银行卡的脱敏规则与生效位置（进日志前）；
5. 同步还是异步解析：解析大文件会拉长 SSE 首字延迟，是否走「上传即异步解析 + `GET /api/attachments/{id}` 轮询」；
6. 对象存储的具体服务与两个新密钥的配置方式（R6：只能来自环境变量/Railway Variables）。

**安全边界（逐条落测试）**：类型白名单外 415、超限 413、zip bomb、超大页数 PDF、CSV 公式注入、跨商家读取 403 并写审计（反例测试）。

---

## 8. 语义层三项（B 类自研）

合并 #6/#7/#8 为一份设计说明——三者都改 `MerchantQaGraph` 的意图链路与同一个 `LlmBudget`，拆开会互相打架。

**简历原文（V2）**：「新建语义层 Agent 对用户意图识别分析结构进行校验，输出不符合用户意图则继续读取本轮 Session 信息及历史记忆再次分析；包括算法关键词识别，用户提问的新词都在语义层补齐。」

**我方现状**：`backend/app/agent/graph.py` 的意图重试用同一份 facts 重新生成，不读 Session、不读记忆、不做意图校验。

**设计说明必须回答：**

1. **「不符合用户意图」如何判定**——由谁判、判据是什么。这是地基，判不准则重试无意义；
2. **再分析时喂什么**：Session 的哪些字段、历史记忆取几条、如何避免把记忆里的旧口径当本轮事实；
3. **预算处置**：按 D4 的顺序走，不得默认提高上限；
4. **新词补齐必须守 R4**：只能落到已验证的 `metric_code`/维度枚举，不得让模型自由输出列名或 SQL；
5. **绕过大模型的命中条件**与**量化验收**：固定问题集跑前后对比，记录 `llm_usage` 调用次数差写进进度快照，否则「省 Token」无法证伪；
6. **提示词契约测试**：`FakeLlmClient` 返回预写好的合法 JSON，「提示词有没有告诉模型该输出什么」在自动化测试里不可见。新增/修改任何提示词必须同时加一条从 Pydantic 模型推导期望值的契约测试（范式见 `backend/tests/unit/intent/test_prompts.py`）。

---

## 9. Chat BI 衡量仪表盘（B 类自研）

参考项目全仓库无 `dashboard`/`看板` 实现，**落地时必须在 `docs/yshopping-parity-audit.md` §5 登记为 ⚪ 我方增强**，否则下一位 agent 会误当成还原缺口。

| 简历口径指标 | 已有素材 | 缺什么 |
| --- | --- | --- |
| 回复采纳率 | `feedback` 表已记采纳/点赞/点踩 | 聚合口径与端点 |
| 回复准确率 | `quality_status` / `quality_attempts` | 「准确」的定义 |
| 平均思考时长 | `agent_node_average_ms` | 端到端口径（现为节点均值） |
| 问题命中率 | `INVALID` 比例、`quality_notes` | 「命中」的定义 |
| 回答失效率 | `degraded` 计数、`processing_status == "FAILED"` | 「失效」的定义 |

**设计说明必须回答**：五个指标各自的精确口径（分子/分母/时间窗/是否按商家分组）；出口是新增 `GET /api/admin/ops/chatbi` 还是扩 `ops/status`（**既有契约明确禁止运维端点返回商家经营数据**）；前端走新路由还是并进 `KnowledgeBaseView`；**是否需要单独问答记录表——`answers` 已是这份记录，不要为对齐简历措辞新建冗余表**。

**口径没定不开工**——这是 `docs/yshopping-parity-audit.md` §3.1 指标口径缺口的教训。

---

## 10. 完成判据（两级，不得混淆）

### 10.1 本路线图完成（只代表"想清楚了"，不代表功能可用）

- [ ] D1–D4 四项裁定全部取得用户明确结论，写入 `docs/project-progress.md`；
- [ ] §5/§6/§7 各自的可执行计划已成文于 `plans/`，含文件、迁移、契约、测试与验收步骤；
- [ ] D3 裁定后，`AGENTS.md:225` 与 `docs/frontend-development-plan.md:765` 的环比承诺已按裁定同步删除/降级/标注；
- [ ] Chat BI 已在 `docs/yshopping-parity-audit.md` §5 预登记为我方增强。

### 10.2 能力交付完成（每项独立计，功能真正可用）

- [ ] **无效意图**：`VALID` 之外不进统计与记忆，重放幂等语义有反例测试证明未变，偏离已登记 §5，引导文案已还原；
- [ ] **日报推送**：独立 Cron Service 与独立配置文件已建，同日幂等、单商家失败隔离、超时与退出码行为均有测试，控制台首次触发已由用户完成并验收；
- [ ] **附件 + OCR**：图片/文本层 PDF/扫描版 PDF/Excel/CSV 全通路可用，白名单外 415、超限 413、跨商家 403 并写审计，解析失败按 R7 显式降级，前端解除 `disabled` 且 `ChatMessage.vue` 渲染附件区；
- [ ] 各项均跑通 §1 全量门禁；所有真实模型/OCR 调用按 R3 逐次申报并记录实际次数与费用。
