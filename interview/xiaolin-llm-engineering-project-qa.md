# Borough 商家 AI 助手：大模型工程面试问答

本文基于小林 Coding“大模型工程”专题的 23 篇文章整理。全部文章均已阅读，但最终只保留与 Borough 商家 AI 助手应用工程直接相关的 13 篇，重组为 18 道项目面试题。

这里的项目事实以当前仓库为准：Borough 通过 DeepSeek OpenAI 兼容 Chat Completions API 使用 `deepseek-v4-flash`，不训练或自托管基础模型。供应商内部可能采用的推理优化，不能算作本项目已经设计和实现的能力。

## 阅读与筛选范围

- 保留：LLM、Tokenizer、解码与采样、KV Cache 与 Prompt Caching、Prompt、CoT、幻觉、MoE、部署、评测、选型和长上下文。
- 排除：Transformer 结构细节、MHA/MQA/GQA/Flash Attention、位置编码、预训练、Scaling Law、微调、LoRA、Post-Training、DPO/PPO、量化。
- 排除不代表这些知识不重要，而是当前岗位叙事应优先回答“我们怎样正确、安全、经济地使用云端 LLM”。

---

## 1. LLM 的本质是什么？它在 Borough 中承担什么职责，又不承担什么职责？

**来源文章：** [什么是大语言模型](https://xiaolinnote.com/ai/llm/what_is_llm.html)

**项目状态：** 已接入生成式 LLM，但把它限制在语言理解、结构化意图、回答组织、质量复核、记忆整理和本地化等非确定性任务中。

### 详细解答

LLM 的基本能力来自根据上下文预测后续 token。它能用统一的文本接口完成分类、抽取、总结和生成，但输出本质是概率生成，不是数据库查询结果，也不是业务规则执行结果。因此 Borough 不让模型成为经营数据的事实源。

模型可以把“最近七天退款金额最高的商品”转换为受控 `QueryIntent`，也可以根据后端事实包组织解释；真正的商家身份、日期边界、指标口径、SQL 模板和数据查询都由确定性代码负责。回答模型只能使用事实包中的数字，Reviewer 再独立检查候选答案。

这体现了应用层分工：让 LLM 处理自然语言中的模糊性，让代码处理权限、事实和约束。模型失效时，项目返回明确标记的受控摘要，而不是声称完成了真实模型分析。

### 项目证据

- [结构化意图模型](../backend/app/intent/models.py)
- [安全查询服务](../backend/app/services/safe_query.py)
- [回答 Prompt](../backend/app/prompts/answer.py)
- [质量循环](../backend/app/services/quality_loop.py)

### 设计取舍与缺口

这种边界牺牲了一部分自由规划能力，换来可审计、可测试和商家隔离。当前主要缺口是完整连续追问语义没有进入统一上下文装配，而不是“模型权限不够大”。

### 可能追问

为什么不让模型直接读取数据库 Schema 并生成 SQL？如果结构化意图错了，后端还有哪些防线？

---

## 2. Tokenizer 为什么会影响 Borough 的成本、预算和上下文设计？

**来源文章：** [什么是大模型项目的分词器](https://xiaolinnote.com/ai/llm/tokenizer.html)

**项目状态：** 已按上游返回的 token usage 结算费用，但请求前预算预留采用保守估算，没有集成 DeepSeek 精确 Tokenizer。

### 详细解答

模型接收的是 token ID，而不是字符。中文、英文、JSON、表格和代码的字符到 token 比例不同，所以不能用“字数”直接等价 token。Tokenizer 同时影响计费、最大上下文、截断位置和生成上限。

Borough 调用前不知道上游最终 usage，因此 `LlmCostGuard` 先依据系统 Prompt、用户 Prompt 和最大输出做保守预留；调用后读取 DeepSeek 返回的 `prompt_tokens`、`completion_tokens` 和 `total_tokens` 对账。这样能防止并发请求先把日额度透支，又能把多预留部分释放回去。

如果供应商没有返回完整 usage，系统会保留估算值并标记 usage 未知，不能伪造精确成本。日常运维应以 `llm_usage` 的真实/估算状态、模型和用途汇总，而不是用字符数乘固定比例。

### 项目证据

- [LLM 费用闸门](../backend/app/llm/guard.py)
- [DeepSeek usage 解析](../backend/app/llm/deepseek.py)
- [用量与日预算模型](../backend/app/models/operations.py)
- [预算 Repository](../backend/app/repositories/llm_budget.py)

### 设计取舍与缺口

保守估算不依赖供应商 Tokenizer，接入简单但可能导致额度暂时预留过多。若以后需要更精确的请求前准入，应引入与当前模型版本一致的官方 Tokenizer，并保留安全余量；模型升级时必须重新校准。

### 可能追问

为什么只在调用后记 token 不够？两个并发请求怎样在调用前保证不会共同突破每日预算？

---

## 3. 贪心、Beam Search 和采样有什么区别？Borough 的任务更偏向哪类生成？

**来源文章：** [大模型解码策略](https://xiaolinnote.com/ai/llm/decoding_strategies.html)

**项目状态：** 使用供应商聊天 API，不直接控制底层解码算法；业务目标偏低随机性的受控生成。

### 详细解答

贪心解码每一步选择概率最高的 token，稳定但容易陷入局部最优和重复；Beam Search 同时保留若干候选序列，更适合有明确整体概率目标的短文本任务；采样按概率分布选 token，语言更自然、多样，但结果波动更大。

Borough 的意图 JSON、Reviewer verdict 和记忆摘要更看重协议遵循与稳定性，而不是创意。回答组织可以保留有限自然语言变化，但数字、来源、建议数量和字段必须符合契约。因此业务上更接近“确定性约束下的生成”，并通过 JSON Schema 风格 Prompt、Pydantic、本地校验和 Reviewer 控制随机性造成的错误。

当前 DeepSeek Adapter 不暴露解码策略开关。面试中应说明我们控制的是应用层输出空间与验证，而不是声称服务端采用了贪心或某个 Beam 宽度。

### 项目证据

- [LLM 调用选项](../backend/app/llm/client.py)
- [DeepSeek 请求负载](../backend/app/llm/deepseek.py)
- [意图解析与有限重试](../backend/app/intent/service.py)
- [Reviewer 服务](../backend/app/services/review_service.py)

### 设计取舍与缺口

应用层约束跨模型通用，但无法完全替代适当的采样配置。若供应商接口稳定支持采样参数，应按调用用途分别评测，不能给所有节点统一一个“最佳参数”。

### 可能追问

为什么客服或经营建议也不应把 Temperature 永远设为 0？完全确定是否等于事实正确？

---

## 4. Temperature、Top-P、Top-K 分别控制什么？当前项目怎么设置？

**来源文章：** [Temperature、Top-P、Top-K](https://xiaolinnote.com/ai/llm/temperature_top_p_top_k.html)

**项目状态：** 当前代码没有发送这三个参数，使用 DeepSeek API 对当前模型的默认值。

### 详细解答

Temperature 调整整个概率分布的尖锐程度；Top-K 只保留概率最高的固定 K 个候选；Top-P 保留累计概率达到阈值的动态候选集合。三者都影响多样性和稳定性，但同时叠加会让行为难以解释。

当前 Adapter 的请求包含模型、system/user 消息、`stream=false`、`max_tokens`，结构化调用还可能包含 thinking 和 `response_format`，没有 `temperature`、`top_p`、`top_k`。所以准确答案不是“我们设成 0”，而是“我们暂时依赖供应商默认采样，并用输出契约和校验保证稳定”。

如果后续开放，应按用途配置：意图、Reviewer、本地化偏稳定；经营建议可稍有多样性。每次只调整一个主要采样变量，用固定评测集比较结构合法率、事实错误率、建议重复率、延迟和 token。

### 项目证据

- [DeepSeek Client](../backend/app/llm/deepseek.py)
- [运行配置](../backend/app/core/config.py)
- [结构化调用选项](../backend/app/llm/client.py)

### 设计取舍与缺口

依赖默认值减少配置面，但供应商默认值变化会带来不可见行为漂移。下一步可显式固定支持的参数，并把其值连同模型、Prompt 版本写入离线验收记录。

### 可能追问

如果将 Temperature 降低后 JSON 合法率提高，但经营建议高度重复，你会怎样按用途拆配置？

---

## 5. KV Cache 和 Prompt Caching 有什么区别？Borough 用了哪一种？

**来源文章：** [KV Cache 与 Prompt Caching](https://xiaolinnote.com/ai/llm/kv_cache_prompt_caching.html)

**项目状态：** 项目没有自建 KV Cache，也没有显式实现或观测 Prompt Caching。

### 详细解答

KV Cache 是一次自回归生成内部的推理优化：缓存已经处理过 token 的 Key/Value，后续生成不必重复计算前缀。它通常由模型推理引擎负责。Prompt Caching 则把相同前缀的计算结果跨请求复用，能降低重复系统 Prompt、工具 Schema 或稳定上下文的成本与延迟。

Borough 调用云端 DeepSeek API，不控制推理引擎，因此即使供应商内部使用 KV Cache，也不能说“项目采用了 KV Cache”。当前请求和用量记录也没有缓存标识、cached token 或命中率，代码没有缓存键、TTL 和前缀版本治理，所以 Prompt Caching 也不能算已实现。

项目现有的机器翻译缓存是业务结果缓存，缓存的是译文，不是模型前缀 KV。三者必须区分，否则会误判节省来源和失效策略。

### 项目证据

- [DeepSeek Adapter](../backend/app/llm/deepseek.py)
- [LLM usage 模型](../backend/app/models/operations.py)
- [机器翻译结果缓存模型](../backend/app/models/localization.py)
- [项目能力边界说明](../AGENTS.md)

### 设计取舍与缺口

当前不自建推理缓存符合云端 API 架构。真正的缺口是缺少供应商缓存命中可观测性，因此无法证明缓存节省了多少输入 token。

### 可能追问

机器翻译缓存、语义缓存、Prompt Caching 和 KV Cache 分别缓存什么？哪个可能返回过时业务答案？

---

## 6. Borough 是否应该为了省钱引入 Prompt Caching？

**来源文章：** [KV Cache 与 Prompt Caching](https://xiaolinnote.com/ai/llm/kv_cache_prompt_caching.html)

**项目状态：** 可以评估，但需要先证明稳定前缀足够长、重复率足够高，并确认 DeepSeek 当前模型和接口的支持方式。

### 详细解答

Prompt Caching 最适合大量请求共享长且完全一致的前缀。Borough 的系统 Prompt、输出契约和部分业务索引可能重复，但知识正文、事实包、语言、问题和商家记忆变化较多，实际可缓存比例不能凭感觉判断。

正确步骤是先统计每种 `purpose` 的输入 token、公共前缀长度、版本变化率和调用量，再查当前供应商的缓存规则与价格。若引入，应把稳定系统指令放前面，商家数据和问题放后面；Prompt 版本变化自然产生新键，不能复用旧安全规则的缓存。

验收指标应包括缓存命中率、缓存输入 token、每问成本、P50/P95 首 token 延迟、答案一致性和错误率。若供应商不返回缓存 usage，就很难形成可验证的财务结论，此时优先做上下文裁剪通常更直接。

### 项目证据

- [按用途计量的费用闸门](../backend/app/llm/guard.py)
- [运维状态接口](../backend/app/api/routes/admin.py)
- [不同用途的 Prompt 目录](../backend/app/prompts)
- [知识检索上下文限制](../backend/app/knowledge/retrieval.py)

### 设计取舍与缺口

缓存不是“打开就省钱”。它增加前缀稳定性约束、版本管理和供应商依赖。当前应先补精确观测和基线，再决定是否引入。

### 可能追问

为什么把动态商家数据放在 Prompt 前部会降低缓存命中？Prompt 改一个空格是否可能失效？

---

## 7. Borough 写了哪些 Prompt？它们都是 System Prompt 吗？

**来源文章：** [Prompt 工程实践](https://xiaolinnote.com/ai/llm/prompt_engineering.html)

**项目状态：** 已实现多套任务专用 Prompt；既有 system 消息，也有包含问题、知识或事实包的 user 消息。

### 详细解答

项目没有使用一条万能 Prompt。意图识别分分类和结构化理解；回答生成有独立 system 指令与事实包；Reviewer 使用另一套角色与审核契约；记忆整理、本地化也各自有系统规则和用户数据。

System Prompt 放稳定角色、禁止事项和输出契约，例如回答只能使用事实包、不得虚构数字。User Prompt 放本次问题、检索知识、候选答案或待翻译内容。身份和权限不会写进 Prompt 让模型决定，而是由后端可信上下文执行。

用户问题、附件和知识文档都应视为不可信数据。即使其中写着“忽略系统规则”，也不能改变 SQL 白名单、商家隔离或费用限制。

### 项目证据

- [意图 Prompt](../backend/app/intent/prompts.py)
- [回答 Prompt](../backend/app/prompts/answer.py)
- [Reviewer Prompt](../backend/app/prompts/reviewer.py)
- [记忆 Prompt](../backend/app/prompts/memory.py)
- [本地化 Prompt](../backend/app/prompts/localization.py)

### 设计取舍与缺口

任务拆分降低单个 Prompt 复杂度，也便于按节点测试。当前尚未形成统一 Prompt 注册表和所有 Prompt 的显式版本号，变更影响仍需更多工具支持。

### 可能追问

为什么 `merchant_id` 不应该由 System Prompt 告诉模型后再让模型传给查询工具？

---

## 8. Borough 的 Prompt 是如何设计和组装上下文的？

**来源文章：** [Prompt 工程实践](https://xiaolinnote.com/ai/llm/prompt_engineering.html)

**项目状态：** 已采用角色、任务、约束、输入和输出格式等要素，并按节点只提供完成该任务所需上下文。

### 详细解答

好的 Prompt 不是堆形容词，而是明确角色、任务、输入、约束和输出。Borough 的结构化理解 Prompt 会列出字段、允许值、业务日期和修复提示；回答 Prompt 明确只能使用后端事实包；Reviewer Prompt 定义通过条件和问题列表格式。

上下文按节点最小化：分类器看到问题和业务索引；理解器看到当前业务域与契约；回答器看到受控事实包；Reviewer 看到事实包和候选答案；记忆整理只看到同商家、同分类的成功回答。这样减少 token，也缩小提示词注入和跨商家泄露面。

项目不会把完整数据库行、全部知识库和全部历史统一塞给模型。检索与查询先在代码层压缩成相关材料，关键数字仍由后端验证。

### 项目证据

- [意图 Prompt 构造](../backend/app/intent/prompts.py)
- [答案事实包与生成](../backend/app/services/answer_service.py)
- [图节点上下文流](../backend/app/agent/graph.py)
- [AgentState](../backend/app/agent/state.py)

### 设计取舍与缺口

节点最小上下文比超长统一 Prompt 更稳定。缺口是没有统一 Context Builder 和分区 token 预算，连续追问的关键历史也未被系统化选择注入。

### 可能追问

如果意图识别需要知识索引，而回答又需要事实包，为什么不能一次模型调用全部完成？

---

## 9. Borough 如何测试、迭代和评估 Prompt？

**来源文章：** [Prompt 工程实践](https://xiaolinnote.com/ai/llm/prompt_engineering.html)、[大模型能力评测指标](https://xiaolinnote.com/ai/llm/evaluation_metrics.html)

**项目状态：** 已有 Prompt 契约测试、Fake LLM 回归、Reviewer、用户反馈和多次定向真实模型验收；尚无全自动 Prompt 实验平台。

### 详细解答

迭代顺序是先固定业务样本与成功标准，再改 Prompt，最后比较结果。单元测试检查字段枚举、JSON 示例、安全约束和双语要求；Fake LLM 检查图路由和降级契约；真实模型离线验收检查自然语言理解和结构化成功率，但必须单独获得费用授权。

项目历史上真实模型曾返回自造字段，导致 Pydantic 连续拒绝。补齐字段形状和枚举示例后，结构化输出通过且 token 明显下降。这说明 Prompt 测试不能只看“能否返回文字”，而要看格式合法率、意图准确率、调用次数、token 和延迟。

线上反馈提供采纳、点赞、点踩，Chat BI 分开展示用户满意度和 Reviewer 一次通过率，避免把系统自评冒充真实准确率。完整闭环仍需要 Prompt 版本、数据集版本、模型参数和实验结果统一关联。

### 项目证据

- [结构化 Prompt 测试](../backend/tests/unit/prompts/test_structured_prompts.py)
- [意图 Prompt 测试](../backend/tests/unit/intent/test_prompts.py)
- [真实模型验收记录](../docs/project-progress.md)
- [产品评测口径](../docs/PRD.md)

### 设计取舍与缺口

CI 全部 mock LLM 能避免不稳定和费用，却不能证明真实模型理解能力。当前还需建立版本化黄金集、盲测对比、回归阈值和灰度回滚流程。

### 可能追问

为什么 Fake LLM 路由 100% 不能证明真实模型意图准确率达到 90%？

---

## 10. CoT 是什么？Borough 的 `thinking_steps` 是模型 CoT 吗？

**来源文章：** [什么是 CoT](https://xiaolinnote.com/ai/llm/cot.html)

**项目状态：** `thinking_steps` 不是模型隐藏推理链，而是后端生成的安全流程轨迹。

### 详细解答

CoT 通过中间推理步骤帮助模型处理多步问题，但完整推理文本会增加 token 和延迟，还可能包含不稳定猜测、敏感上下文或不可依赖的事后解释。产品不应把模型私有推理原样展示给用户。

Borough 的 `thinking_steps` 来自固定 LangGraph 节点标签，如识别、检索、查询和复核。它告诉用户系统执行了哪些阶段，却不包含完整 Prompt、SQL、数据行或模型内部思维。回答依据通过 `analysis_sources`、质量状态和说明字段表达。

这种“可审计流程摘要”比展示自由 CoT 更可靠，因为节点是否执行可以由代码证明。它也便于中英文显示和安全审查。

### 项目证据

- [步骤标签与节点追加](../backend/app/agent/graph.py)
- [聊天响应 Schema](../backend/app/schemas/chat.py)
- [SSE 事件路由](../backend/app/api/routes/chat.py)

### 设计取舍与缺口

当前步骤在任务完成后批量发送，不是实时节点流。后续可改善事件时机，但仍应只展示安全阶段摘要，不暴露隐藏 CoT。

### 可能追问

如果不展示模型推理链，用户怎样判断回答是否可信？流程轨迹、证据引用和事实校验分别解决什么问题？

---

## 11. 为什么结构化意图调用会关闭 thinking？复杂问题会不会因此变差？

**来源文章：** [什么是 CoT](https://xiaolinnote.com/ai/llm/cot.html)、[Temperature、Top-P、Top-K](https://xiaolinnote.com/ai/llm/temperature_top_p_top_k.html)

**项目状态：** 结构化调用默认请求 JSON 输出并关闭 thinking；普通回答和 Reviewer 不套用这一选项。

### 详细解答

意图阶段目标是短、合法、可解析的 JSON。显式推理可能消耗输出额度，甚至让模型在 JSON 前后生成额外文本。项目因此为结构化调用设置 `json_output=True`、`thinking="disabled"`，提高协议稳定性并控制成本。

这不是认为推理永远无用。复杂跨域问题通过两阶段意图识别解决：先分类，再补全结构化计划；真正数据关联仍由安全查询服务完成。若评测显示关闭 thinking 明显降低复杂意图准确率，可以仅对特定问题升级模型或允许受控推理，但输出仍必须通过同一 Schema。

选择必须依据分类准确率、JSON 合法率、token 和延迟的对照实验，而不是把“思考更多”自动等同于“更正确”。

### 项目证据

- [结构化调用配置](../backend/app/llm/client.py)
- [DeepSeek thinking 请求逻辑](../backend/app/llm/deepseek.py)
- [两阶段意图服务](../backend/app/intent/service.py)

### 设计取舍与缺口

当前是全局结构化策略，尚未按意图复杂度动态选择。引入分流前要防止路由本身再增加一次昂贵模型调用。

### 可能追问

如果复杂意图需要 reasoning，但 reasoning token 不返回正文导致 `max_tokens` 耗尽，你会怎样设置预算和降级？

---

## 12. LLM 为什么会幻觉？Borough 最容易出现哪些幻觉？

**来源文章：** [大模型幻觉及缓解](https://xiaolinnote.com/ai/llm/hallucination.html)

**项目状态：** 无法消除幻觉，但已识别并约束查询幻觉、数字幻觉、知识幻觉、完成状态幻觉和建议依据不足。

### 详细解答

LLM 的目标是生成高概率文本，不是检索真实记录。训练数据错误、知识过期、上下文不足、问题诱导和过度迎合都会使流畅答案与事实不一致。

在 Borough 中，风险包括：虚构不存在的指标；声称查询了其实未查询的数据；把知识文档中的示例数字当真实经营数据；错误相加非可加指标；未执行工具却声称完成；把其他商家的信息带入回答。

这些风险不能只靠 Prompt。项目将知识、数据库事实和商家记忆标记为不同来源，查询失败和知识未命中会显式降级，回答只能使用事实包数字，Reviewer 检查支持关系，商家范围由服务端强制注入。

### 项目证据

- [答案事实与数字校验](../backend/app/services/answer_service.py)
- [Reviewer Prompt](../backend/app/prompts/reviewer.py)
- [安全查询](../backend/app/services/safe_query.py)
- [知识与记忆检索优先级](../backend/app/knowledge/retrieval.py)

### 设计取舍与缺口

当前防线显著降低事实型幻觉，但 Reviewer 也是模型，不能作为绝对真理。还缺更系统的引用级 grounding 评测和任务完成状态审计。

### 可能追问

Reviewer 和回答模型都使用同一类模型时，为什么 Reviewer 仍有价值？怎样避免两者犯同一个错误？

---

## 13. Borough 如何系统性缓解幻觉，而不是只写一句“不要胡说”？

**来源文章：** [大模型幻觉及缓解](https://xiaolinnote.com/ai/llm/hallucination.html)

**项目状态：** 已形成“检索与查询、结构化约束、本地验证、独立复核、可见降级、反馈”的多层防线。

### 详细解答

第一层是给模型正确上下文：知识检索提供规则与口径，安全查询提供当前商家真实数据。第二层是缩小输出空间：意图必须通过 Pydantic 和白名单，回答必须符合 `AnswerDraft`。

第三层是确定性验证：数字只能来自事实包，非可加指标不能随意求和，日期、图表和建议数量受代码检查。第四层是 Reviewer 独立复核并允许有限重试。第五层是产品透明度：模型、数据库或知识失败时，通过 `degraded`、`degraded_reason`、`analysis_sources` 和 `quality_notes` 告诉用户。

最后利用采纳、点赞和点踩发现系统性问题。用户反馈不能直接训练模型或自动改 Prompt，而应先脱敏、归因和人工复核，避免恶意反馈污染。

### 项目证据

- [意图白名单](../backend/app/intent/whitelist.py)
- [统一质量循环](../backend/app/services/quality_loop.py)
- [反馈服务](../backend/app/services/feedback_service.py)
- [降级响应契约](../backend/app/schemas/chat.py)

### 设计取舍与缺口

多层防护增加调用次数，尤其 Reviewer 会增加成本和延迟。项目通过有限重试和总预算控制上限，但仍需量化 Reviewer 的边际收益。

### 可能追问

如果关闭 Reviewer 后成本下降 25%，但用户点踩率只上升 1%，你会如何决定是否保留？

---

## 14. MoE 为什么可能降低推理成本？这能解释 Borough 选择 DeepSeek 吗？

**来源文章：** [MoE 混合专家模型](https://xiaolinnote.com/ai/llm/moe.html)

**项目状态：** 项目消费云端模型 API，不控制专家路由；不能仅凭 DeepSeek 品牌推断当前 `deepseek-v4-flash` 的内部架构。

### 详细解答

MoE 为每个 token 只激活部分专家网络，使总参数容量可以很大，而单次计算使用的激活参数较少。它能提高单位计算的模型容量，但会带来路由均衡、专家通信、显存放置和部署复杂度。

了解 MoE 有助于解释为什么某些 DeepSeek V3 等模型能够以较低推理成本提供较强能力，但 Borough 的选型不能建立在未经确认的内部结构上。当前模型的架构、价格和缓存政策应以供应商当前官方说明为准。

项目真正可控的是 API 单价、结构化成功率、回答质量、延迟、可用性和合规。底层是否 MoE 是成本成因之一，不是应用选型结论本身。

### 项目证据

- [模型配置](../backend/app/core/config.py)
- [DeepSeek Adapter](../backend/app/llm/deepseek.py)
- [模型选型产品决策](../docs/PRD.md)

### 设计取舍与缺口

使用托管 API 把 MoE 部署复杂度交给供应商。代价是内部架构、容量和路由不可控，因此要用应用层评测和可切换 Adapter 管理供应商风险。

### 可能追问

MoE 的总参数和激活参数有什么区别？为什么“激活参数少”不等于显存只需要放激活专家？

---

## 15. Borough 为什么调用云端 API，而不是用 vLLM、SGLang、TGI 或 llama.cpp 自托管？

**来源文章：** [大模型部署框架选型](https://xiaolinnote.com/ai/llm/deployment_frameworks.html)

**项目状态：** 当前只在 Railway 部署业务应用，通过 HTTPS 调用 DeepSeek；没有自托管推理服务。

### 详细解答

vLLM 强调高吞吐和 PagedAttention；SGLang 对复杂生成程序和共享前缀优化更深入；TGI 与 Hugging Face 生态结合；llama.cpp 适合本地 CPU、边缘和量化模型。它们解决的是模型权重加载、批处理、显存和推理调度，不是普通 FastAPI 业务部署。

Borough 当前请求量和团队规模不足以证明自托管更便宜。云端 API 省去 GPU 采购、容量规划、模型升级、推理框架运维和故障值守，使团队集中在经营数据、安全和产品闭环。

只有当调用量稳定到自托管 TCO 更低、数据不能出域、需要供应商没有的模型或必须控制推理细节时，才应 PoC。比较必须包含 GPU 利用率、峰值冗余、工程人力、可用性和升级成本，而非只比较每百万 token 标价。

### 项目证据

- [后端 Railway 配置](../backend/railway.json)
- [固定 DeepSeek 地址与模型](../backend/app/core/config.py)
- [部署文档](../docs/deployment.md)
- [Python 依赖](../backend/pyproject.toml)

### 设计取舍与缺口

托管 API 适合当前阶段，但形成供应商依赖。项目已有适配器接口，尚缺经过评测的第二供应商或自托管备用实现。

### 可能追问

如何计算 API 与自托管的盈亏平衡点？为什么不能假设 GPU 24 小时满载？

---

## 16. Borough 的 LLM 评测指标应该怎样设计？

**来源文章：** [大模型能力评测指标](https://xiaolinnote.com/ai/llm/evaluation_metrics.html)

**项目状态：** 已定义部分业务指标和验收阈值，但完整的版本化离线与线上评测闭环仍未完成。

### 详细解答

通用 Benchmark 只能说明基础能力，不能代表商家经营问答。项目应按链路分层评测：意图层看分类准确率、字段 F1 和 JSON 合法率；检索层看 Recall@K、排序和来源正确性；查询层看口径与权限；生成层看事实一致、数字正确、建议可执行性；系统层看成功率、P95 延迟、token 和降级率。

真实模型意图准确率与 Fake 路由回归必须分开。Fake 只能验证代码和夹具，真实模型才验证自然语言理解。线上“用户准确率”实际是点赞满意度，Reviewer 一次通过率是系统自评，两者不能合并成一个准确率。

黄金集应覆盖九类业务、指标/明细/规则/身份、日期边界、跨业务、无数据、知识缺失、注入攻击和多语言。每次模型或 Prompt 变更记录版本、样本、均值和尾部失败，并设回归门槛。

### 项目证据

- [PRD 评测定义](../docs/PRD.md)
- [项目真实模型验收记录](../docs/project-progress.md)
- [Chat BI 汇总服务](../backend/app/services/chatbi_service.py)
- [Agent 单元测试](../backend/tests/unit/agent/test_graph.py)

### 设计取舍与缺口

分层指标便于定位，但最终仍要有端到端任务成功率。当前需要把散落的验收记录沉淀为可重复运行的数据集和报告，而不是只增加测试数量。

### 可能追问

为什么 LLM-as-Judge 的分数不能直接称为准确率？如何校准 Judge 与人工标注的一致性？

---

## 17. Borough 为什么选择 `deepseek-v4-flash`？怎样判断是否升级或换模型？

**来源文章：** [大模型选型](https://xiaolinnote.com/ai/llm/model_selection.html)

**项目状态：** 当前唯一云端供应商为 DeepSeek，默认 `deepseek-v4-flash`；`deepseek-v4-pro` 仅是经过费用和真实验收后的可配置升级项。

### 详细解答

模型选型不能只看排行榜，应从合规与可用性、能力、延迟、成本和接口兼容性综合判断。Borough 需要中文经营语义、稳定 JSON、事实包回答、Reviewer、多轮有限重试和可接受的线上延迟。

Flash 版本优先服务 MVP 的成本与响应速度。是否升级 Pro 应用同一业务集比较意图准确率、JSON 合法率、Reviewer 通过率、端到端成功率、P95、平均输入/输出 token 和每问价格。若质量提升只集中在极少数复杂问题，可做确定性复杂度分流，而不是全量升级。

切换模型还要复核 thinking、JSON 输出、上下文、token 统计、错误码和 Prompt 效果。配置可切换不代表零迁移成本。

### 项目证据

- [模型与供应商约束](../AGENTS.md)
- [Settings 模型默认值](../backend/app/core/config.py)
- [模型 Adapter](../backend/app/llm/deepseek.py)
- [定向验收记录](../docs/project-progress.md)

### 设计取舍与缺口

单模型策略简单可控，但缺少供应商故障切换和按用途选模。现阶段应先完成全业务真实验收，再决定是否引入多模型路由。

### 可能追问

如果 Pro 准确率提高 3%，单问成本翻倍、P95 增加 60%，哪些业务值得分流过去？

---

## 18. 上下文窗口越大越好吗？Borough 如何避免 Lost in the Middle？

**来源文章：** [长上下文与 Lost in the Middle](https://xiaolinnote.com/ai/llm/23_long_context_lost_middle.html)

**项目状态：** 已按节点最小化上下文并限制知识文本长度，但没有统一 token 预算器，也没有完整连续追问上下文选择。

### 详细解答

最大上下文窗口只表示“装得下”，不保证模型能同等利用所有位置。Lost in the Middle 指关键信息位于长上下文中部时更容易被忽略。上下文越长还会增加输入费用、首 token 延迟和无关信息干扰。

Borough 不把所有材料一次塞入：先用知识索引分类，再按业务域和关键词取正文；回答模型只接收整理后的事实包；Reviewer 只看候选答案与同一事实；完整历史不会自动加入。重要规则放在 system 消息，关键事实按结构化字段组织，而非埋在长文中。

当前知识限制主要按字符，单轮预算由 LLM 调用层控制，还没有为 system、历史、知识、数据和输出分别分配 token。未来应使用目标 Tokenizer 计数、按优先级裁剪，并用“针在中间”与真实长会话集测试有效上下文。

### 项目证据

- [知识检索与长度限制](../backend/app/knowledge/retrieval.py)
- [节点状态与上下文](../backend/app/agent/state.py)
- [图执行流程](../backend/app/agent/graph.py)
- [每请求 token 预算](../backend/app/core/config.py)

### 设计取舍与缺口

最小上下文节省费用并减少注入面，但连续追问能力有限。改进方向应是结构化会话摘要和相关历史选择，而不是把全部 Message 拼回 Prompt。

### 可能追问

如何设计一个业务版 Lost in the Middle 测试，证明关键退款口径放在不同位置时模型仍能正确使用？

---

## 项目能力现状矩阵

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| 云端 LLM | 已实现 | DeepSeek Chat Completions，默认 `deepseek-v4-flash` |
| 精确请求前 Tokenizer | 未实现 | 调用前保守估算，调用后按 usage 对账 |
| 采样参数配置 | 未实现 | 未发送 Temperature、Top-P、Top-K |
| 自建 KV Cache | 未实现 | 云端推理内部能力不算项目实现 |
| Prompt Caching | 未实现 | 没有缓存键、命中率或 cached token 观测 |
| 业务结果缓存 | 部分实现 | 机器翻译有版本化缓存，不等同于 Prompt Cache |
| 多任务 Prompt | 已实现 | 意图、回答、Reviewer、记忆、本地化分开 |
| Prompt 契约测试 | 已实现 | CI mock LLM，不产生真实费用 |
| 自动 Prompt 实验平台 | 未实现 | 缺统一版本、数据集、灰度和回滚 |
| 幻觉防护 | 部分实现 | 事实包、校验、Reviewer、降级与反馈 |
| 自托管推理 | 未实现 | Railway 只部署业务服务，模型使用云端 API |
| 业务评测闭环 | 部分实现 | 有测试、反馈与真实验收，尚未完全自动化 |

## 面试回答总纲

1. 先说明项目是云端 LLM 应用，不训练、不量化、不自托管基础模型。
2. 再说明模型只处理非确定性语言任务，身份、SQL、口径和权限由代码掌握。
3. 成本靠上下文最小化、调用/输出上限、日预算、真实 usage 对账和按用途统计控制，不能虚构缓存收益。
4. 质量靠结构化契约、确定性校验、Reviewer、可见降级和业务反馈闭环。
5. 所有模型、Prompt、采样或缓存优化都必须经过同一业务评测集验证后再上线。

