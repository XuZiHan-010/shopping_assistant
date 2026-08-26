## Why

Borough 商家助手是对外部署的服务，但当前**没有任何一条路径能零成本拒绝一个问题**。
`IntentService.recognize`（`backend/app/intent/service.py:69`）无条件调用 LLM，因此
「CNN 和 RNN 的区别是什么」这类与经营完全无关的提问，仍会真实消耗 1~2 次 DeepSeek 调用；
问候语「你好」同样如此。恶意用户只要持续提问，就能稳定烧掉 token 预算。

现有防线挡不住这件事：

- 频率限流（`SlidingWindowRateLimiter`，默认 10 次/分钟）只限速率，不限内容，恶意提问在
  限额内照样全部进模型；
- 每日 token 熔断（`llm_daily_budget_tokens`，默认 500,000）是**全局**的
  （`backend/app/core/config.py:79` 注释已写明「不分商家、不分访客」），一个恶意商家刷爆额度，
  **全平台商家一起停服**——这是可用性单点，不是防护。

与此同时，加权打分逻辑其实已经存在（`_relevance_score`，标题/路径/正文三档加权），
但它跑在 `classify_intent` 与 `understand_intent` **两次 LLM 调用之后**，且关键词由 LLM 抽取，
分数排完序即丢弃。也就是说：判断「这个问题跟我们的业务有没有关系」所需的全部素材都已就绪，
只是被放在了错误的位置。

本变更把这个判断前移到 LLM 之前，让明显无关的问题以零 LLM 成本被拒绝。

不采用关键词黑名单：无关提问无法穷举，新型无关问题永远在名单之外。判据改为
**问题与知识库的加权匹配分**——知识库覆盖什么，闸门就认什么，两侧都不需要人工枚举。

## What Changes

- **新增零 LLM 前置闸门节点** `prefilter_question`，插入在 `retrieve_knowledge_index` 与
  `classify_intent` 之间。`GRAPH_NODES` 由 11 个节点变为 12 个，SSE 处理轨迹新增对应
  `ThinkingStep`。
- **新增确定性切词**：对原始问题做零依赖 n-gram 切分（中文 2~4 字滑窗，英文单词与数字整体保留），
  产出候选词，不依赖 LLM。
- **复用并暴露打分能力**：`_relevance_score` 由内部函数提升为可复用接口，对
  知识库索引、`metric_definitions` 展示名与本商家历史记忆打分，取最高分。
- **低分短路**：最高分低于阈值时不调用任何 LLM，直接返回 `AnswerMode.INVALID`，
  附引导文案与推荐问题，引导用户重新提问。
- **问候语放行**：命中问候语模式的短问题绕过打分直接放行，保持「日常打招呼由模型自然回答」的
  既有体验。
- **仅首轮生效**：会话已存在被放行过的历史轮次时跳过闸门，避免「那上个月呢？」这类
  无业务词的合法追问被误拒。
- **新增配置项**：闸门开关与分数阈值，可通过环境变量调整，便于线上按误拒情况调参。
- **可观测**：被拒问题的分数、命中情况写入结构化日志（不记录完整问题正文之外的隐私字段），
  供运营发现误拒并补充知识库。

**无 API 契约变更。** 被拒响应完全复用现有 `INVALID` 模式的既有字段，不新增任何
`ChatResponse` 字段，`docs/backend-development-plan.md` §8 契约不变。

## Capabilities

### New Capabilities

- `chat/question-prefilter`: 在任何 LLM 调用之前，以确定性算法判定问题是否属于本平台
  经营问答范围；范围外的问题零 LLM 成本拒绝并引导重问，范围内与判定不确定的问题原样交由
  既有 LangGraph 意图链路处理。

### Modified Capabilities

（无。`openspec/specs/` 当前为空，本变更为首个 change，不修改既有 capability 的需求。）

## Impact

**受影响代码**

| 文件 | 改动 |
| --- | --- |
| `backend/app/agent/prefilter.py` | 新建：切词、打分聚合与放行判定 |
| `backend/app/agent/graph.py` | 新增 `_prefilter_question` 节点、`GRAPH_NODES`、`_STEP_LABELS`、短路分支 |
| `backend/app/agent/state.py` | `AgentState` 新增闸门判定结果字段 |
| `backend/app/knowledge/retrieval.py` | `_relevance_score` 提升为可复用接口；新增按原始问题打分的入口 |
| `backend/app/core/config.py` | 新增闸门开关与阈值配置项 |
| `backend/tests/` | 新增闸门单测与图集成测试 |

**不受影响**

- API 契约（`ChatRequest` / `ChatResponse` / SSE 事件类型）不变，无需重新导出 `docs/api.md`，
  前端 `generated.ts` 与 Adapter 均无需改动；
- 数据库无迁移；
- 无新增运行时依赖（n-gram 切分为纯标准库实现，不引入 jieba）。

**安全与规则符合性**

- **R4**：闸门运行在任何 SQL 生成之前，不接触查询层，不产生表名、列名或 SQL 片段；
  它只做「放行 / 拒绝」的布尔判定，不产出查询意图。
- **R5**：打分若纳入商家历史记忆，`merchant_id` 必须取自已验证的 `MerchantContext`，
  不得采信请求体传入的商家编号；知识库索引与 `metric_definitions` 为全局团队知识，不含商家数据。
- **R7**：闸门拒答是**设计内的正常行为，不是降级**。被拒响应须为
  `degraded=false`、`degraded_reason=null`、`quality_status=NOT_RUN`、
  `analysis_sources=["NONE"]`，与现有 `INVALID` 模式一致。
  **不得**把拒答标记成 `degraded=true`——那会让用户与运营把正常的范围外拒绝误读为系统故障。
  闸门自身依赖的知识库不可用时（索引为空），须 fail open 放行交给 LLM，而非把所有问题拒绝。

**已知残留风险（本次接受，不在范围内）**

- 会话首轮通过后闸门即跳过，恶意用户可先问一句合法业务问题「拿通行证」，在同一会话内继续提问。
  兜底仍是既有的频率限流与每日预算熔断。收紧代价是合法追问的误拒，本次选择保体验。
- 每日预算仍是全局而非每商家，「一人刷爆、全平台停服」的可用性单点未解决。
- 限流器为进程内 `dict`，多实例部署时实际配额为 `10 × 实例数`。

后两项属于基础设施层，与闸门的语义判定无耦合，应作为独立 change 处理。
