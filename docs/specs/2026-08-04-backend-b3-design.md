# 后端 B3「指标、知识与结构化意图」设计说明

**日期：** 2026-08-04
**阶段：** B3（`docs/backend-development-plan.md` §B3）
**前置：** B0–B2 已交付并完成收口整改

---

## 1. 目标

让助手能够**理解问题属于哪个业务域、要哪个指标、在什么范围内**，并把这份理解表达成一个受严格约束的结构化对象 `QueryIntent`。B3 只负责「理解」，不负责「查数」——真正执行经营查询是 B4。

三件可独立验收的产出：

1. **知识检索**：两层，索引层（业务域未知）与正文层（业务域已知）。
2. **指标目录**：`metric_code` 为唯一键的三级检索，生成口径必须标注待核验。
3. **结构化意图**：两阶段（分类 → 理解）+ 白名单校验，非法输出有限重试后降级。

## 2. 非目标

- **不实现经营数据查询。** B3 结束时 `query_data` 节点仍是占位，经营数据表也还不存在（B4 建）。
- **不实现回答编排与 Reviewer。** `compose_answer` / `review_answer` 属 B5。
- **不发起真实 LLM 调用。** DeepSeek Adapter 写出来但测试不启用；首次真实调用前必须走 AGENTS.md R3 的成本同意。
- **不做商家记忆。** 属 P1/B8，B3 只在检索回退链上留出位置。

## 3. 与参考实现的关系

AGENTS.md R8 定义参考项目为「核对业务行为、接口字段、指标口径、知识库结构、测试用例和视觉样式」的依据，不是逐行复刻的对象——技术栈本来就是 Java → Python。

本设计的原则是：**行为对齐参考实现，实现跟随本项目已定的方案文档。**

### 3.1 行为对齐（照参考实现做）

| 点 | 参考实现的做法 | 出处 |
| --- | --- | --- |
| 检索策略 | 关键词匹配「路径 + 正文」：`containsAny(path + " " + content, categoryKeywords(category))` | `WikiMemoryService.isMaintainedDocument` |
| 域别名归属 | **代码常量**，不是数据库表。`TRADE → {交易, 订单, trade, order, gmv}` 等 10 组 | `WikiMemoryService.categoryKeywords` |
| 索引层的含义 | **不是摘要**，而是路径含 `index` / `rule` / `目录` 的特定文档 | `isMaintainedDocument` 的 `UNKNOWN` 分支 |
| 正文层的输入 | `category` + `intentKeywords`，含中文词尾剥离启发式 | `matchesIntentKeywords` |
| 检索回退顺序 | 团队维护知识命中即返回；为空才读商家记忆 | `loadRelevantWiki` |
| 尺寸上限 | 检索层 24000 字符；进 prompt 前再截到 10000 | `MAX_WIKI_CHARS` 两处不同取值 |
| 三套白名单 | 代码内的不可变集合 | `PROFILE_METRIC_COLUMNS` 等 |
| 白名单二次校验 | 意图层校验过，**查询层仍要再校验一遍** | `queryMetric` 的注释：「指标列会被拼进 SQL 标识符位置」 |
| 两阶段意图 | `recognize` → 二层检索 → `understand` → 语义层 `inspectInput` | `MerchantQaLangGraph.recognizeIntent` |
| 指标三级检索 | 正式指标平台 → 字段注释 → LLM 生成 | `MetricDefinitionService.resolve` |
| 生成口径的处置 | 固定的待核验 Notice，不写入正式指标 | `GENERATED_NOTICE` |
| LLM 不可用 | `chat(system, user, fallback)` 的 `fallback` 入参 + `isConfigured()` 门 | `LlmClient` |

### 3.2 有意偏离（跟随本项目方案文档）

| 点 | 参考实现 | 本项目 | 理由 |
| --- | --- | --- | --- |
| 知识存储 | 文件系统（classpath + runtime 目录） | PostgreSQL | §6.5 明写「运行时可编辑知识保存在 PostgreSQL」；Railway 容器重启不保留写入的文件 |
| 数据源 | Doris | PostgreSQL | 本项目没有 Doris |
| 日期范围上限 | `MAX_QUERY_DAYS = 365` | **180 天** | §6.3：与演示数据天数对齐，避免「允许查询但没有数据」的区间 |
| Agent 编排 | 手写 `GraphNode` 顺序链，7 节点 | LangGraph，13 节点 | §10 已定节点顺序与 `AgentState` 字段 |
| LLM 输出校验 | 仅 `fallback` 兜底 | `fallback` **加上** Pydantic 严格校验 + 有限重试 + 单请求预算 | §B3 明写；参考实现在这一点上较宽松 |

**这些偏离都要写进代码注释**，注明「参考实现如何做、本项目为何不同」，避免后来者把它当成疏漏而「修正」回去。

## 4. 模块边界

| 模块 | 职责 | 对外接口 | 依赖 |
| --- | --- | --- | --- |
| `app/knowledge/domains.py` | 业务域常量：别名、主数据表、商家过滤键、优先级 | `DOMAIN_KEYWORDS`、`DOMAIN_TABLES`、`merchant_filter_key(category)` | 无 |
| `app/knowledge/retrieval.py` | 两层检索 | `load_index()`、`load_domain_documents(category, keywords)` | 域常量、`knowledge_documents` |
| `app/metrics/catalog.py` | 指标口径三级检索 | `resolve(intent) -> MetricDefinitionPayload` | `metric_definitions`、LLM |
| `app/intent/whitelist.py` | 三套白名单与校验 | `validate_intent(intent) -> IntentValidation` | 无 |
| `app/intent/service.py` | 两阶段意图 | `recognize(...)`、`understand(...)` | LLM、知识、指标 |
| `app/llm/client.py` | LLM 协议与预算 | `LlmClient` Protocol、`LlmBudget` | 无 |
| `app/llm/fake.py` | 测试替身 | `FakeLlmClient(behaviour=...)` | 无 |
| `app/llm/deepseek.py` | 真实适配器（测试不启用） | `DeepSeekLlmClient` | httpx |
| `app/agent/graph.py` | LangGraph 骨架与 `AgentState` | `MerchantQaGraph.run(...)` | 以上全部 |
| `scripts/import_wiki.py` | 受控导入旧 Wiki | CLI | `knowledge_documents` |

每个模块都能独立测试：知识检索不需要 LLM，白名单校验不需要数据库，FakeLlm 不需要网络。

## 5. 数据模型

### 5.1 `knowledge_documents` 新增两列

```
source_path   TEXT     NOT NULL   -- 导入时的原始相对路径，检索匹配的依据之一
is_complete   BOOLEAN  NOT NULL DEFAULT TRUE  -- 骨架文档为 false
```

`source_path` 是必需的：参考实现按「路径 + 正文」匹配，路径本身携带业务域和文档类型信息（`业务/交易/业务流程/...`）。丢掉路径就等于丢掉一半匹配依据。

`is_complete` 对应旧 Wiki 里 16 份带「⚠️ 待团队补充」标记的骨架文档。命中骨架时回答必须如实说明资料不完整，这是 R7 的要求。

**不新增 `knowledge_domains` 表**，也**不新增 `summary` 列**。域别名走代码常量（3.1），索引层是特定文档而非摘要（3.1）。

### 5.2 `metric_definitions` 沿用 B1 已建的表

已有 `metric_code`（唯一）、`display_name`、`unit`、`business_definition`、`sql_definition`、`source`、`owner`、`status`。B3 只补 Seed 数据，不改结构。`status = 'UNVERIFIED'` 承载「LLM 生成的候选口径」。

## 6. 知识检索

### 6.1 索引层（`classify_intent` 之前）

业务域未知。只取 `source_path` 含 `index`、`rule` 或 `目录` 的文档，按域优先级拼接，上限 24000 字符。

作用是给模型提供拆词和领域识别所需的词汇——不是给模型答案。

### 6.2 正文层（`validate_intent` 之后）

业务域已知。取该域的文档，再按 `intent_keywords` 过滤。关键词匹配含词尾剥离：

```
去掉结尾的 指标|明细|数据|情况|趋势|数量|金额|次数|量|数
剥离后长度 >= 2 才用于匹配
```

这条启发式直接来自参考实现——「退货量」要能命中写着「退货」的文档。

### 6.3 回退与未命中

团队维护知识命中即返回。为空时进入商家记忆（P1，B3 留空实现并返回空）。两层都为空时**显式返回未命中**，不允许静默返回空字符串让模型自由发挥。

未命中会体现为 `analysis_sources` 不含 `KNOWLEDGE`，并在 `quality_notes` 留一条说明。

## 7. 结构化意图

### 7.1 两阶段

```
recognize(question, history, index_knowledge)
    → answer_mode + category + intent_keywords
load_domain_documents(category, intent_keywords)
    → 正文
understand(question, initial_intent, history, domain_knowledge)
    → QueryIntent 完整字段
validate_intent(intent)
    → 通过 / 有限重试 / INVALID
```

### 7.2 `QueryIntent` 字段

`answer_mode`、`category`、`metric`（`metric_code`）、`dimensions`、`filters`、`date_range`、`sort`、`limit`、`followup_reference`、`needs_attachment`。

### 7.3 校验必须拦住的五件事

每条一个反例测试：

1. 输出 SQL 字符串；
2. 输出中文指标名而非 `metric_code`；
3. 非白名单维度或筛选字段；
4. 日期范围超过 180 天（后端截断而非报错）；
5. `limit` 超过上限（后端覆盖而非报错）。

前三条是拒绝，后两条是**后端覆盖**——参考实现即如此，用户不该因为问了「最近两年」而拿到一个错误。

### 7.4 三套白名单

全部是 `app/intent/whitelist.py` 里的不可变集合：

- **指标白名单**：与 `metric_definitions` 表的 Seed 同源，构建时校验二者一致，防止表里有而白名单没有；
- **维度白名单**；
- **筛选字段白名单**。

**B4 必须在查询层再校验一次。** 参考实现的注释点明了原因：指标列会被拼进 SQL 的标识符位置，那里无法参数化绑定。本设计把这条写成 B4 的硬要求，避免 B4 认为「意图层已经校验过」而省掉。

## 8. 指标目录

三级检索，顺序固定：

1. **正式指标表** `metric_definitions`，按 `metric_code` 精确匹配；
2. **内置字段映射**（对应参考实现的 Doris 字段注释）；
3. **LLM 生成候选口径**。

第三级的产物必须：`generated = true`、`status = 'UNVERIFIED'`、带固定待核验文案、**不写入正式指标表**、`analysis_sources` 含 `FALLBACK` 且 `degraded = true`。

待核验文案沿用参考实现语义，品牌改为 Borough：

> 该指标口径未命中正式指标目录或字段注释，以下内容由大模型根据当前问题生成，仅供参考，请以正式指标口径为准。

前端 F2 已实现的降级提示条会直接展示这条信息，无需前端改动。

## 9. LLM 层

### 9.1 协议

```python
class LlmClient(Protocol):
    def is_configured(self) -> bool: ...
    async def complete(
        self, *, system: str, user: str, fallback: str, budget: LlmBudget
    ) -> LlmResult: ...
```

保留参考实现的两个关键设计：`is_configured()` 让未配置密钥时整条链路仍可运行；`fallback` 是入参而非异常，调用方在写调用时就必须想清楚「模型不可用时这一步返回什么」。

结构化解析在调用方：`parse_or_retry(result, model=QueryIntentDraft)`，Pydantic 严格模式，失败有限重试（上限写进常量），仍失败则降级。

### 9.2 FakeLlmClient

四种行为，由构造参数选择：正常、非法 JSON、超时、空响应。这是 §B3 验收明列的四种。

### 9.3 DeepSeekLlmClient

OpenAI 兼容 `/chat/completions`，`base_url = https://api.deepseek.com`，默认 `model = deepseek-v4-flash`。**所有测试使用 FakeLlmClient**；真实调用前必须取得用户对模型、调用次数和费用的明确同意（R3）。

### 9.4 单请求预算

`LlmBudget` 按单个请求计数 `calls` 与 `tokens`，超限时抛出可识别的预算异常，由图节点转成显式降级（`degraded = true` + `degraded_reason`），并写 `llm_usage` 表。

**降级不是失败**：用户仍拿到回答，只是标注了来源与限制。

## 10. Agent Graph

按 §10 建全部 13 个节点。B3 真正实现的是：`load_context`、`retrieve_knowledge_index`、`classify_intent`、`understand_intent`、`validate_intent`、`retrieve_knowledge_detail`、`suggest_questions`、`persist_answer`。

`query_data`、`compose_answer`、`local_validate`、`review_answer`、`decide_retry` 建成 passthrough 占位，各自留一条 TODO 注明归属阶段（B4/B5）。

这样做的收益：SSE 的 `step` 事件序列从 B3 起就是完整真实的一串，B4/B5 只填肉不重排，前端不用改第二次。

`decide_retry` 的 `MAX_REVIEW_ATTEMPTS = 2` 写进分支条件本身，不写在注释里——避免实现时漏掉而形成无限循环。

**FakeAgent 在本阶段退役**，由图 + FakeLlmClient 接替。`ChatAgentProtocol`（`app/services/chat_service.py`）是现成的接缝，图实现该 Protocol 即可，`ChatService` 不改。

## 11. Wiki 导入

`scripts/import_wiki.py` 从 `yshopping-merchant-ai 4/.../runtime/llm-wiki/` 读取，写入 `knowledge_documents`。参考目录只读，脚本只读不写。

- **导入**：`业务流程/`、`业务名词解释/`、平台规则；
- **排除**：`ddl/` 与 `指标或调用指标平台mcp的skill/`——它们描述旧库表（`yshopping.dwm_trade_order_detail_di` 等），而本项目的经营数据表要到 B4 才设计。导进来会让助手描述一批不存在的表。
- **品牌**：正文里的 `yshopping` 洗成 Borough（AGENTS.md「命名与品牌」）；
- **骨架**：含「⚠️ 待团队补充」的 16 份标 `is_complete = false`；
- **幂等**：按 `source_path` upsert，重复执行不产生重复行。

## 12. 测试策略

单元测试全部使用 FakeLlmClient，不触网、不花钱（R3）。

| 面 | 覆盖 |
| --- | --- |
| 知识检索 | 索引层只取 index/rule/目录 文档且**不加载正文**；正文层按域+关键词过滤；词尾剥离生效；两层都未命中时显式返回未命中；尺寸上限截断 |
| 白名单 | 五条反例各一：SQL 字符串、中文指标名、非白名单维度、超 180 天被截断、超 limit 被覆盖 |
| 指标目录 | 三级顺序；生成口径带 `UNVERIFIED` + 待核验文案且不写入正式表 |
| LLM | FakeLlm 四种行为；非法 JSON 触发有限重试；重试耗尽后降级；预算超限显式降级并写 `llm_usage` |
| 图 | 六类问题正确路由（指标/明细/规则/身份/聊天/无效）；SSE step 序列完整；`decide_retry` 不会无限循环 |
| 隔离 | 团队知识对所有商家一致且不含商家数据，因此 `KnowledgeRepository` 刻意不做 `merchant_id` 过滤——这与 `ConversationRepository` 的隔离要求不同，需在代码注释里写明是有意为之，避免后来者当成漏洞「补上」。商家级记忆是另一张表，B8 建时必须按 `merchant_id` 隔离 |

## 13. 顺带处理的两件契约事

这两件不在 §B3 原始清单里，但都在 B3 的路径上，且已记录在 `docs/project-progress.md` 的推迟项中：

1. **给 `Visualization.type` 与 `allowed_types` 加枚举。** 目前契约是 `string | null` 与 `string[]`，没有枚举。前端不能自行窄化（§5.0 禁止 Adapter 编造约束），只能在契约侧加。加完 `codegen` 自动传导，前端零改动。
2. **导出 `DETAIL` 与 `IDENTITY` 两种模式的 fixture。** 前端 F3 验收要求 Adapter 契约测试覆盖 P0 六种模式，目前只有 4 种（`CHAT`/`INVALID`/`METRIC`/`RULE`），根因是后端没导出这两种。B3 正好要实现这两种模式的路由。

## 14. 风险

- **关键词匹配的召回上限。** 别名表覆盖不到的提法会漏命中。缓解：未命中时显式告知而不是编造，且别名常量可随演示反馈补充。这是有意接受的取舍——换来零依赖、零成本、完全确定性可测。
- **骨架文档的回答质量。** 16 份骨架内容稀薄。缓解：`is_complete = false` 且命中时如实说明。
- **白名单与 Seed 漂移。** 缓解：构建时校验白名单与 `metric_definitions` Seed 一致。
- **LangGraph 是新依赖。** 缓解：图逻辑集中在 `app/agent/graph.py` 一个文件，节点函数本身不依赖框架类型，必要时可退回手写顺序链（参考实现即如此）。
