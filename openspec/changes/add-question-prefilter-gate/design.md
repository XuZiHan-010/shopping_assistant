## Context

动机见 `proposal.md` — Why；行为契约见 `specs/chat/question-prefilter/spec.md`。

约束本设计的既有事实：

- 图在 `backend/app/agent/graph.py:178-181` 是一条**纯线性链**，用
  `pairwise(GRAPH_NODES)` 逐对连边，没有任何条件分支；
- `_relevance_score`（`retrieval.py:197`）已实现标题 3 / 路径 2 / 正文 1 的加权命中，
  但只被 `_narrow_by_keywords` 用作排序键，分数本身不外传；
- 打分所需的词由 LLM 在 `classify_intent` 抽出（`InitialIntent.intent_keywords`），
  这是它无法前移到 LLM 之前的**唯一**原因；
- `KnowledgeRetrieval` 构造时即持有已验证的 `merchant_id`（`retrieval.py:106`），
  记忆检索天然满足 R5，闸门复用它即可，无需自行处理商家身份；
- `suggestions_for`（`services/suggested_questions.py`）是**服务端预置常量**，
  零 LLM、零数据库依赖——这决定了拒答分支仍可安全地产出推荐问题。

## Goals / Non-Goals

**Goals**

- 明显范围外的提问以 0 次 LLM 调用被拒绝；
- 判定逻辑对知识库内容变化自适应，不需要人工维护无关词清单；
- 误拒可被观测、可被调参、可被一键停用，无需回滚部署。

**Non-Goals**

- 不追求判定准确率的上限。本设计只求**高精度地识别"明显无关"**，
  一切模糊情况一律放行——闸门的价值在于挡掉零成本可挡的部分，不在于替代 LLM 分类；
- 不引入向量检索或 embedding。语料只有 23 篇文档，关键词加权已足够，
  引入向量会带来模型依赖，与"零 LLM"的目标自相矛盾；
- 不解决每商家配额与跨实例限流（见 proposal.md — 已知残留风险）。

## Decisions

### D1：闸门作为独立节点 + LangGraph 条件边，而非在各节点内加守卫

`GRAPH_NODES` 由 11 个变为 12 个，新增 `prefilter_question`，位置在
`retrieve_knowledge_index` 之后、`classify_intent` 之前。

线性链保持用 `pairwise` 构建，**唯独** `prefilter_question` 的出边改为条件边：

```
prefilter_question --放行--> classify_intent
prefilter_question --拒绝--> suggest_questions
```

拒绝分支跳过 `classify_intent`、`understand_intent`、`validate_intent`、
`retrieve_knowledge_detail`、`query_data`、`compose_answer`、`quality_loop` 七个节点，
即跳过了**全部**会调用 LLM 的节点，但仍经过 `suggest_questions`（提供引导素材）
与 `persist_answer`（落库，使被拒问答同样出现在会话记录中，供运营复盘）。

**备选方案：在每个中间节点开头加 `if state["prefilter_rejected"]: return` 守卫。** 否决，因为
七个节点各写一遍守卫既易漏又难测；更关键的是，被跳过的节点仍会向 SSE 推送
`ThinkingStep`，用户会看到"查询经营数据""校验并复核回答质量"等根本没发生的阶段——
这违反 R7"不得把兜底包装成真实处理"的精神。条件边下 SSE 轨迹为
`识别商家与会话上下文 → 读取业务知识索引 → 判定问题范围 → 生成推荐问题 → 保存本轮回答`，
每一步都真实发生过。

### D2：判定只累计标题与路径命中，正文命中不计入

这是本设计最关键的一条。

`_relevance_score` 原本三档全算，但把它原样用于闸门会失效：知识库正文很长，
任意 2 字中文 bigram 几乎必然在某处出现。「CNN 和 RNN 的区别是什么」切出的
「区别」「什么」大概率能在某篇文档正文里找到子串，正文档因此不具区分度，
只会把噪声抬高到与真实业务提问同一量级。

真正有区分度的是**标题与路径**——它们是人工命名的业务语义标签，
「退货量」命中「退款退货域」文档的标题，「区别」命中不了任何标题。

因此闸门的判定分定义为：

```
判定分 = Σ 候选词在语料标题(权重 3)或路径(权重 2)上的最高命中权重
```

正文权重保持存在于 `_relevance_score` 中不动（`retrieve_knowledge_detail` 的排序仍需要它），
闸门调用时通过参数关闭正文档。

**备选方案：用覆盖率（命中词数 / 候选词总数）归一化。** 否决，因为 n-gram 候选数随问题
长度增长，长的合法业务提问会被大量无意义候选稀释覆盖率，反而更易误拒。

### D3：零依赖 n-gram 切词 + 极小停用词表

中文按 2~4 字滑窗切出候选词，英文单词与连续数字整体保留。不引入 jieba：
我们的匹配本来就是子串包含（`_matches_keywords` 即 `keyword in haystack`），
分词精度带来的收益有限，而新增依赖会增加镜像体积与冷启动时间。

叠加一份**极小的通用停用词表**（的、是、什么、怎么、为什么、请问、一下、可以 等）。

需要说明它与被否决的"无关词黑名单"的区别：停用词表是**语言层的封闭集合**——
现代汉语的功能词是有限且稳定的，不随用户提问内容增长；而无关词黑名单试图枚举
**内容层的开放集合**（CNN、RNN、写诗、翻译……），永远不可能穷举。前者可维护，后者不可维护。
本设计只接受前者。

### D4：语料范围与 fail open

判定语料三项，取最高分：

| 语料 | 参与字段 | 商家隔离 |
| --- | --- | --- |
| 知识文档 | `title`、`source_path` | 全局团队知识，无商家数据 |
| 指标目录 | `display_name`、`metric_code` | 全局 |
| 商家历史记忆 | `content` 首行摘要 | 取 `KnowledgeRetrieval` 构造时的已验证 `merchant_id` |

三处 fail open（任一发生即放行，绝不因自身故障拒绝用户）：

1. 三项语料全部为空 → 放行；
2. 语料读取抛异常 → 记日志并放行；
3. 配置开关关闭 → 放行。

### D5：阈值默认 3，通过环境变量调整

判定分 `< 阈值` 才拒绝。默认 3 = "至少一个候选词命中某篇文档的标题"。

新增两个配置项，沿用无前缀命名：

```
QUESTION_PREFILTER_ENABLED      默认 true
QUESTION_PREFILTER_MIN_SCORE    默认 3
```

阈值调低 → 更容易放行（更保守）；调高 → 更容易拒绝（更激进）。
线上先按默认值观察拒答日志，确认无误拒后再考虑收紧。

### D6：首轮判定靠会话已有轮次数

`AgentState` 已有 `session_id`。闸门判定前检查该会话是否已存在助手消息：
存在则直接放行，不打分（对应 spec 的"会话内追问必须放行"）。

判据选"已存在助手消息"而非"已存在用户消息"，是因为当前轮的用户消息可能已先行落库，
用它判断会导致首轮自己就被认成追问，闸门形同虚设。

### D7：拒答复用现有 INVALID 契约，不新增字段

拒答响应：`answer_mode=INVALID`、`degraded=false`、`degraded_reason=null`、
`quality_status=NOT_RUN`、`quality_attempts=0`、`analysis_sources=["NONE"]`。

`analysis_sources=["NONE"]` 与 `AGENTS.md` §10.4「`CHAT` 和 `INVALID` 返回 `["NONE"]`」一致。
`degraded` 保持 `false` 是**刻意**的：拒答是设计内行为，标成降级会污染
`/api/admin/ops/status` 的降级计数，让运营把正常拒绝误读为系统故障。

## Risks / Trade-offs

- **知识库覆盖窄导致误拒** → 三重缓解：默认阈值保守（仅需一个标题命中）；
  每次拒答记录分数与阈值，运营可从日志反查误拒并补文档；
  `QUESTION_PREFILTER_ENABLED=false` 可即时停用，改环境变量即可，无需回滚部署。

- **首轮通过后同会话不再判定，可被"拿通行证"绕过** → 已在 proposal 中登记为接受的残留风险。
  兜底是既有的频率限流（10 次/分钟）与每日预算熔断。收紧的代价是合法追问误拒，
  本次明确选择保体验。

- **停用词表仍是一份需要人工维护的清单** → 它是语言层封闭集（见 D3），
  增长有限；且它只影响判定分高低，不单独决定拒绝，命中停用词只是不加分，不扣分。

- **n-gram 候选数随问题长度线性增长** → 当前 23 篇文档 × 数十候选 × 子串匹配为微秒级，
  可忽略。知识库增长到数千篇时需重新评估，届时应改为倒排索引或向量检索。
  在设计中记录此阈值，避免规模变化后无人察觉。

- **`pairwise` 线性建图被打破，后续增删节点更易出错** → 建图处补充测试，
  断言拒绝分支实际跳过的节点集合，使误连边在测试中立刻暴露。

## Migration Plan

1. 默认启用（`QUESTION_PREFILTER_ENABLED=true`），阈值取默认 3；
2. 上线后观察拒答日志一段时间，统计拒答率与人工抽查误拒；
3. 回滚手段是改环境变量为 `false`，不需要回滚镜像；
4. 无数据库迁移，无 API 契约变更，前端无需同步发布。
