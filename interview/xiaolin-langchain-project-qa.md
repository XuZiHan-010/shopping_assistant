# Borough 商家 AI 助手：LangChain 与 LangGraph 面试问答

本文基于小林 Coding“LangChain 框架”专题全部 12 篇文章整理，并结合 Borough 当前 Python 实现重组为 15 道项目面试题。

必须先明确名称边界：Borough 当前直接依赖 `langgraph>=0.2,<1`，没有安装或使用 LangChain、LlamaIndex、CrewAI 或 LangChain4j。文中涉及 LangChain v1、Runnable、LCEL、Checkpointer 和 Store 的内容用于解释框架思想与未来选型，不能冒充当前实现。

---

## 1. 你了解哪些 Agent 框架？Borough 为什么直接选择 LangGraph？

**来源文章：** [AI Agent 开发框架](https://xiaolinnote.com/ai/langchain/agent_frameworks.html)

**项目状态：** 当前只直接使用 LangGraph；模型、Prompt、检索、查询、记忆和持久化接口由项目自己实现。

### 详细解答

LangChain 更偏模型、消息、工具和 Agent 的通用组装；LangGraph 更偏显式状态、节点、条件边、循环和恢复；LlamaIndex 更偏数据接入、索引和上下文增强。框架选型应看项目最难的问题，而不是比较 GitHub 热度。

Borough 的核心难点是：意图识别前后有固定顺序，查询必须经过安全边界，回答要独立复核，失败必须可见降级，而且每一步都要共享类型化状态。这类流程用 `State + Node + Edge` 展开，比通用 Agent 自动循环更容易审计。

项目没有为了“生态完整”同时引入 LangChain 和 LlamaIndex。DeepSeek 适配器、关键词知识检索和业务查询均较小且有强定制需求，直接实现减少抽象层和版本耦合。

### 项目证据

- [后端依赖](../backend/pyproject.toml)
- [LangGraph 主流程](../backend/app/agent/graph.py)
- [类型化状态](../backend/app/agent/state.py)
- [服务装配](../backend/app/api/dependencies.py)

### 设计取舍与缺口

直接使用 LangGraph 保留控制力，但模型供应商切换、标准 Tool、中间件和 Trace 需要自己维护。只有这些重复工作成为主要成本时，才值得补 LangChain。

### 可能追问

如果步骤固定，为什么不完全使用普通 Python 函数？LangGraph 当前具体解决了什么问题？

---

## 2. Chain、Runnable 和 LCEL 是什么？Borough 有没有类似的设计？

**来源文章：** [如何理解 LangChain 中的 Chain](https://xiaolinnote.com/ai/langchain/chain.html)

**项目状态：** 没有使用 LangChain Runnable 或 LCEL；固定 LangGraph 节点和类型化 Service 体现了相似的组件组合思想。

### 详细解答

Chain 是把 Prompt、模型、检索器、解析器和函数按数据流组合成可执行流程。现代 LangChain 以 Runnable 统一 `invoke`、异步、批处理和流式接口，LCEL 用组合表达式构造串行或并行数据流；旧式 `LLMChain` 不应作为新项目主线。

Borough 没有 Runnable 协议。图节点接收 `AgentState` 并返回状态增量，业务 Service 使用明确 Python 接口，图决定执行顺序。调用、重试、降级和观测并未被统一成一个可组合抽象，而是分别由 LLM Client、质量循环、节点计时和 API 层处理。

面试时可以说项目采用了“显式数据流与组件组合”，但不能说使用了 LCEL。是否需要统一 Runnable，要看批处理、流式转换和跨组件配置是否真的反复出现。

### 项目证据

- [AgentState](../backend/app/agent/state.py)
- [图节点注册与连接](../backend/app/agent/graph.py)
- [LLM Client 协议](../backend/app/llm/client.py)
- [质量循环](../backend/app/services/quality_loop.py)

### 设计取舍与缺口

自定义接口贴合业务类型，调试路径直观；缺点是没有 Runnable 的统一批处理、流式和 Trace 生态。当前 SSE 也不是节点原生实时流。

### 可能追问

一个组件实现统一 Runnable 接口后，为什么仍不能自动解决前后步骤类型不匹配？

---

## 3. LangChain 的底层分层是什么？Borough 自己实现了哪些对应层？

**来源文章：** [LangChain 的底层架构](https://xiaolinnote.com/ai/langchain/langchain_architecture.html)

**项目状态：** 没有 LangChain 依赖，但具备自定义模型协议、消息输入、结构化输出、工作流、检索和持久化层。

### 详细解答

LangChain 的核心分层可以看作模型与消息协议、Prompt、结构化输出、Tools、Agent 循环、中间件和 LangGraph 运行时。它的价值是让不同供应商和组件遵守相对统一的接口，再把权限、重试、摘要等横切能力接入执行过程。

Borough 的 `LlmClient` 是模型抽象，DeepSeek/Fake 是实现；Prompt 按任务分文件；Pydantic 模型解析结构化意图与回答；LangGraph 负责节点编排；知识 Repository、经营查询和 Conversation Repository 分别管理上下文与持久化。

尚未对应的是原生 Message 对象体系、标准 Tool、动态 Agent loop、Middleware、Checkpointer 和统一 Trace。这些并不是漏装一个包，而是项目刻意保留的简化边界。

### 项目证据

- [LLM 抽象](../backend/app/llm/client.py)
- [DeepSeek 实现](../backend/app/llm/deepseek.py)
- [Prompt 目录](../backend/app/prompts)
- [结构化 Schema](../backend/app/intent/models.py)
- [会话 Repository](../backend/app/repositories/conversation.py)

### 设计取舍与缺口

当前分层足够支撑一个供应商和有限工具。若供应商、Tool 和横切策略大量增加，自建协议的维护成本会上升，届时 LangChain 核心抽象可能更划算。

### 可能追问

自建 `LlmClient` 与使用 LangChain `ChatModel` 各有什么供应商锁定风险？

---

## 4. 不依赖 LangChain 高层 API，Borough 是怎样构建完整 Agent 的？

**来源文章：** [使用 LangChain 构建 Agent 的核心步骤](https://xiaolinnote.com/ai/langchain/build_agent.html)

**项目状态：** 已完成任务边界、模型适配、状态、固定工具路由、安全、质量和观测的主要闭环。

### 详细解答

构建 Agent 不应从 `create_agent()` 开始，而应先定义任务和成功边界。Borough 限定为商家经营数据、规则和口径问答；范围外输入由 prefilter 拒绝。随后定义 DeepSeek 适配器、结构化意图、安全查询、知识检索、回答与 Reviewer。

`AgentState` 保存一轮执行所需字段，LangGraph 依次执行身份/上下文、知识索引、预筛、意图理解、校验、正文检索、查询、回答、复核和持久化。预算、重试、幂等、商家隔离和降级不交给模型决定。

测试从节点和 Service 的确定性行为开始，真实模型验收独立于 CI 并受费用授权约束。线上通过 `llm_usage`、节点耗时、失败和 Chat BI 指标观察。

### 项目证据

- [Agent 图](../backend/app/agent/graph.py)
- [零 LLM 前置闸门](../backend/app/agent/prefilter.py)
- [安全查询](../backend/app/services/safe_query.py)
- [费用保护](../backend/app/llm/guard.py)
- [聊天应用服务](../backend/app/services/chat_service.py)

### 设计取舍与缺口

当前流程可控，但缺少 Checkpoint、人工中断恢复和真正实时节点事件。它是生产化固定工作流，不是功能完备的通用 Agent 平台。

### 可能追问

你怎样定义这一轮 Agent 成功？模型返回了文字但 Reviewer 失败，算成功还是失败？

---

## 5. LangChain 如何注册工具？Borough 当前的“工具”为什么没有注册给模型？

**来源文章：** [LangChain 工具注册](https://xiaolinnote.com/ai/langchain/tool_registration.html)

**项目状态：** 当前没有 LangChain Tool、`@tool` 或原生 Function Calling；模型输出结构化意图，图调用固定 Service。

### 详细解答

LangChain Tool 注册会提供工具名、描述和输入 Schema，模型负责提出调用，宿主负责执行。可信身份、权限和连接对象应通过运行时 Context 注入，不能暴露成模型可填写参数。异步 I/O 工具应真正异步，并为错误定义可恢复与不可恢复类别。

Borough 没有把 `SafeQueryService`、知识检索或导出注册给模型。意图模型只能表达白名单字段，LangGraph 根据回答模式进入固定节点；`merchant_id` 从认证上下文注入，模型不能选择函数或数据库。

这适合当前少量、高安全要求的能力。未来转原生 Tool 时，可以复用现有 Pydantic Schema 和 Service，但仍要在执行前二次校验，限制单轮调用次数、成本和副作用。

### 项目证据

- [意图模型](../backend/app/intent/models.py)
- [意图白名单](../backend/app/intent/whitelist.py)
- [安全查询 Service](../backend/app/services/safe_query.py)
- [可信身份解析](../backend/app/core/security.py)

### 设计取舍与缺口

固定路由牺牲动态工具组合，换取最小攻击面。工具增多后需要注册表和权限过滤，但不能直接把所有工具 Schema 发给模型。

### 可能追问

如果把 `merchant_id` 从 Tool Schema 隐藏，远程工具最终怎样知道当前商家是谁？

---

## 6. Borough 的短期记忆怎样实现？和 LangChain Checkpointer 有什么区别？

**来源文章：** [LangChain 的短期记忆和长期记忆](https://xiaolinnote.com/ai/langchain/memory.html)

**项目状态：** 部分实现。单轮有 `AgentState`，跨请求有 Conversation/Message/Answer 持久化，但图没有 Checkpointer，也不会把完整历史自动恢复到 State 或 Prompt。

### 详细解答

LangChain v1 的线程级短期记忆通常是 State、稳定 `thread_id` 和 Checkpointer。Checkpoint 保存的不只是聊天文本，还包括执行到哪个节点和中间状态，可用于暂停、故障恢复和人工审批。

Borough 的 `AgentState` 每次 `run()` 重新创建，`graph.compile()` 没有传 Checkpointer。数据库会保存会话、用户消息、助手回答和质量信息，支持历史展示、幂等重放和判断当前会话是否已有回答，但这些记录不会自动恢复成图状态。

因此当前“保存了聊天历史”不等于“模型拥有完整短期记忆”。连续追问只有限度使用会话存在性和商家长期记忆，未实现相关历史选择、会话摘要或中断节点恢复。

### 项目证据

- [AgentState 初始状态](../backend/app/agent/state.py)
- [图编译与运行](../backend/app/agent/graph.py)
- [会话持久化](../backend/app/services/chat_service.py)
- [Conversation Repository](../backend/app/repositories/conversation.py)

### 设计取舍与缺口

无 Checkpointer 减少迁移表、序列化和恢复复杂度，当前请求也较短。缺口是代词追问、跨轮约束和中途恢复能力有限。下一步应先做结构化会话摘要和相关历史注入，再决定是否启用 Checkpointer。

### 可能追问

为什么数据库里已经有 Message 表，仍不能说实现了 LangGraph Checkpoint？

---

## 7. Borough 的长期记忆怎样提取、保存和召回？

**来源文章：** [LangChain 的短期记忆和长期记忆](https://xiaolinnote.com/ai/langchain/memory.html)

**项目状态：** 已实现按商家和业务分类的长期记忆，但使用自定义 PostgreSQL Repository，不是 LangChain Store。

### 详细解答

成功回答后，`MemoryAgent` 在后台读取同一商家、同一分类的近期成功问答与人工内容，调用独立记忆 Prompt 做归纳压缩。每个 `(merchant_id, category)` 维护一份最新内容，通过数据库唯一约束避免重复分叉。

检索时团队知识优先；只有团队知识没有命中，才读取当前商家、当前分类的记忆，并在 `analysis_sources` 和质量备注中明确来源。记忆不能覆盖平台规则，也不能代替实时订单、金额或库存查询。

模型失败时保存带明确标记的确定性 fallback，而不是伪装成成功的模型记忆。记忆任务有独立调用与 token 预算，不应拖垮主回答。

### 项目证据

- [后台记忆 Agent](../backend/app/services/memory_agent.py)
- [记忆压缩服务](../backend/app/services/memory_service.py)
- [记忆 Prompt](../backend/app/prompts/memory.py)
- [记忆 Repository](../backend/app/repositories/memory.py)
- [知识与记忆召回](../backend/app/knowledge/retrieval.py)

### 设计取舍与缺口

分类级摘要比保存全部聊天更省 token、噪声更少，但粒度较粗，可能覆盖细节。当前没有向量语义记忆，也缺少面向商家的查看、更正、删除和过期策略。

### 可能追问

为什么长期记忆只从成功回答提取，而不直接从所有用户原话提取？

---

## 8. 多商家场景下，记忆如何防止串读、污染和过期？

**来源文章：** [LangChain 的短期记忆和长期记忆](https://xiaolinnote.com/ai/langchain/memory.html)

**项目状态：** 已实现商家范围与分类唯一键、团队知识优先和管理员只读记忆树；纠错、过期淘汰与用户自助治理仍不完整。

### 详细解答

LangChain Store 常用 namespace 隔离租户和记忆类型。Borough 的等价边界是 `(merchant_id, category)`：身份来自认证后的 `MerchantContext`，Repository 查询必须显式带商家 ID，模型和前端不能指定别的 namespace。

污染治理依赖写入来源和优先级。只从成功回答提炼，团队知识始终优先，模型失败的 fallback 有标记，旧译文缓存还按 Prompt 版本隔离。实时业务事实永远重新查数据库，不从长期记忆读取。

仍需补充记忆的来源引用、置信度、更新时间展示、过期策略、商家纠错/删除接口和召回评测。仅有数据库隔离并不能保证内容正确。

### 项目证据

- [MerchantMemory 模型](../backend/app/models/knowledge.py)
- [商家范围 Repository](../backend/app/repositories/memory.py)
- [知识后台边界](../backend/app/services/knowledge_admin_service.py)
- [商家身份服务](../backend/app/core/security.py)

### 设计取舍与缺口

当前模型简单且安全边界清晰；缺少时间和来源元数据会让旧经验长期残留。治理能力应先于扩大召回规模。

### 可能追问

同一商家今天纠正了昨天的偏好时，是覆盖、追加还是保留版本？回答如何选择？

---

## 9. LangChain 和 LlamaIndex 有什么区别？Borough 为什么都没有使用？

**来源文章：** [LangChain 与 LlamaIndex](https://xiaolinnote.com/ai/langchain/langchain_vs_llamaindex.html)

**项目状态：** 当前直接使用 LangGraph，加自定义关键词检索和业务 Repository，没有 LangChain 或 LlamaIndex。

### 详细解答

两者功能有交集，但默认重心不同：LangChain 偏模型、Tools、Agent 和集成；LlamaIndex 偏文档接入、解析、切分、索引、检索、重排和 Query Engine。选择应看主要风险在工具编排还是数据上下文。

Borough 当前知识规模较小，采用业务域、路径和关键词加权的 PostgreSQL 检索，不使用 Embedding、向量数据库或复杂文档解析。Agent 路径又需要强安全的固定图。因此自定义检索加 LangGraph 已能覆盖当前需求，同时引入 LlamaIndex 会增加依赖却没有解决已证实瓶颈。

若未来附件和知识库规模扩大，出现复杂切分、多路检索、重排和数据连接器需求，可让 LlamaIndex 负责检索层，再通过明确接口交给 LangGraph；不必重写安全查询或商家权限。

### 项目证据

- [关键词知识检索](../backend/app/knowledge/retrieval.py)
- [知识 Repository](../backend/app/repositories/knowledge.py)
- [LangGraph 编排](../backend/app/agent/graph.py)
- [RAG 项目化问答](./xiaolin-rag-project-qa.md)

### 设计取舍与缺口

当前坚持 YAGNI。引入条件应由单文档变长、召回失败、解析复杂度或连接器维护成本等指标触发，而不是为了简历堆栈。

### 可能追问

如果引入 LlamaIndex，它应该取代当前 LangGraph，还是只替换 `KnowledgeRetrieval`？

---

## 10. LangChain4j 解决什么问题？旧项目是 Java，为什么新 Borough 没选它？

**来源文章：** [LangChain4j 的定位和场景](https://xiaolinnote.com/ai/langchain/langchain4j.html)

**项目状态：** 当前和只读参考项目都没有真正使用 LangChain4j；新架构按既定目标采用 Python、FastAPI 和 LangGraph。

### 详细解答

LangChain4j 不是 Python LangChain 的官方逐项移植，而是符合 Java 习惯的独立 LLM 框架。它用 ChatModel、Tools、AI Services、Chat Memory 和 RAG 抽象连接 Spring Boot、Quarkus 等生态，适合领域服务已经大量沉淀在 Java 的团队。

旧参考项目虽然类名叫 `MerchantQaLangGraph`，但它是自定义 Java 流程类，不代表使用了 Python LangGraph 或 LangChain4j。新 Borough 的目标技术栈已确定为 Python + TypeScript，Python 生态更方便直接使用 LangGraph、Pydantic 和数据处理库。

选择 Python 不等于 LangChain4j 不好，也不等于框架能替代安全责任。若企业现有订单、权限和审计全部在 Spring 中，直接用 LangChain4j 包装 Java 服务可能比新增 Python 服务更合理。

### 项目证据

- [项目技术栈与目录指南](../AGENTS.md)
- [Python 依赖](../backend/pyproject.toml)
- [当前 Python 图](../backend/app/agent/graph.py)
- [参考项目还原差异](../docs/yshopping-parity-audit.md)

### 设计取舍与缺口

当前重构选择服从项目既定目标，也避免双语言运行时。面试时不要虚构“我们对 LangChain4j 做过性能压测”；只能解释基于技术栈和架构目标的选择。

### 可能追问

如果公司的主系统是 Spring Boot，你会坚持 Python Agent 独立服务，还是把能力留在 Java？判断依据是什么？

---

## 11. LangChain 和 LangGraph 的核心区别是什么？Borough 为什么没有使用 `create_agent`？

**来源文章：** [LangChain 与 LangGraph](https://xiaolinnote.com/ai/langchain/langchain_vs_langgraph.html)

**项目状态：** 直接使用低层 LangGraph `StateGraph`，没有 LangChain 高层 Agent API。

### 详细解答

LangChain 提供模型、Prompt、Tool、结构化输出和高层 Agent 组装；现代 LangChain Agent 底层运行在 LangGraph 上。LangGraph 让开发者直接控制 State、Node、Edge、条件路由、循环、持久化和 Interrupt。两者是抽象层级关系，不是简单竞争关系。

`create_agent` 适合标准“模型选择工具—执行—继续”循环。Borough 的流程不是自由工具循环，而是知识索引必须先于分类、正文检索必须晚于分类、经营查询必须经过安全 Service、生成后必须本地校验和独立 Reviewer。显式图更能表达这些硬顺序。

同时，项目只需要一个 DeepSeek Adapter，不依赖 LangChain 丰富集成。直接 LangGraph 降低依赖层级，也使每个节点的业务状态在类型中可见。

### 项目证据

- [状态图构建](../backend/app/agent/graph.py)
- [AgentState](../backend/app/agent/state.py)
- [知识检索顺序设计](../docs/backend-development-plan.md)
- [后端依赖清单](../backend/pyproject.toml)

### 设计取舍与缺口

显式图需要自己实现更多胶水能力。若未来大部分路径变成标准 Tool loop，高层 LangChain Agent 可能更省代码，但强制安全节点仍应保留在外层图中。

### 可能追问

LangChain 也能写条件逻辑，为什么复杂流程仍要下沉 LangGraph？区别只在语法吗？

---

## 12. Borough 已经使用了 LangGraph 的哪些优势？哪些高级能力还没用？

**来源文章：** [LangGraph 的核心优势](https://xiaolinnote.com/ai/langchain/langgraph_advantages.html)

**项目状态：** 已使用显式 State、节点、条件边和异步执行；未使用 Checkpointer、Interrupt、持久化恢复、动态 Send 或通用并行汇合。

### 详细解答

当前图将一轮问题的意图、知识、查询结果、预算、质量和步骤放入 `AgentState`。所有主要阶段注册成节点，prefilter 后使用条件边决定继续分类还是直接推荐问题。节点耗时和安全步骤可被观测。

但 `graph.compile()` 没有 Checkpointer；API 请求中断后不能从某个节点恢复。项目没有 `interrupt()` 暂停等待人工审批，也没有把独立查询分支用 `Send` 动态并行。SSE 在任务执行期间只发心跳，完成后才回放步骤，因此也未发挥图事件流的全部能力。

这些不是必须立即补齐。只读经营问答通常秒级完成，强制持久化每个节点会增加表、序列化和清理成本。只有出现长任务、人工审批、昂贵步骤复用或真实并行收益时才应升级。

### 项目证据

- [图构建和 `compile()`](../backend/app/agent/graph.py)
- [SSE 实现](../backend/app/api/routes/chat.py)
- [节点耗时测试](../backend/tests/unit/agent/test_graph_node_timing.py)
- [图单元测试](../backend/tests/unit/agent/test_graph.py)

### 设计取舍与缺口

当前用了最有价值的显式编排，避免提前承担高级运行时成本。产品若要求真正实时进度和人工接管，Checkpointer、事件流和 Interrupt 会成为相互关联的一组改造。

### 可能追问

如果在执行数据库查询后进程崩溃，启用 Checkpointer 怎样避免重新查询？查询结果适合直接序列化进状态吗？

---

## 13. LangChain 大版本变化给 Borough 什么启示？当前依赖版本安全吗？

**来源文章：** [LangChain 版本演进](https://xiaolinnote.com/ai/langchain/version_evolution.html)

**项目状态：** 未使用 LangChain；LangGraph 约束为 `>=0.2,<1`，避免自动跨入 1.x，但仍需锁文件和升级回归。

### 详细解答

LangChain 的演进主线是拆分稳定核心与第三方集成、用 Runnable/LCEL 统一组件协议、让 Agent 运行时建立在 LangGraph 上，并在 v1 用 `create_agent` 和 Middleware 收敛高层接口。旧 `LLMChain`、AgentExecutor 和 Conversation Memory 教程不能直接套到新项目。

Borough 没有 LangChain 迁移负担，但直接依赖 LangGraph 也会面对状态语义、流式事件、Checkpoint Schema 和编译 API 变化。当前 `<1` 上限避免未经验证的主版本升级，`uv.lock` 固定解析结果，不能因此停止维护。

升级应先阅读 release notes，在独立分支更新依赖，跑图路由、状态合并、异步、SSE、幂等和故障测试，再做一次受控端到端验收。不能只改 import 后认为完成。

### 项目证据

- [依赖范围与锁文件入口](../backend/pyproject.toml)
- [LangGraph 图实现](../backend/app/agent/graph.py)
- [图测试目录](../backend/tests/unit/agent)
- [项目进度与验证记录](../docs/project-progress.md)

### 设计取舍与缺口

版本上限降低意外破坏，但也可能长期停在旧 API。项目需要明确升级节奏和兼容矩阵，而不是无限冻结或自动追最新版。

### 可能追问

为什么有 `uv.lock` 还要在 `pyproject.toml` 写版本范围？两者分别保护什么？

---

## 14. Deep Research 的实现逻辑是什么？Borough 需要把经营分析改成 Deep Research 吗？

**来源文章：** [Deep Research 的逻辑与场景](https://xiaolinnote.com/ai/langchain/deep_research.html)

**项目状态：** 当前没有 Deep Research，也不适合把普通指标和规则查询改成开放式研究 Agent。

### 详细解答

Deep Research 通常先澄清目标并形成 Research Brief，再由 Supervisor 拆分独立子课题，多个 Researcher 并行检索和压缩证据，Supervisor 检查缺口，最后统一写作。价值在动态规划、上下文隔离和证据核验，不是简单“多搜几次”。

Borough 的多数问题有权威数据库、指标口径和固定业务域。把“最近七天 GMV”拆成多个研究 Agent 会增加 token、延迟和口径冲突，却不提高事实准确性。安全查询和固定图才是更合适的方案。

如果未来提供跨平台竞品研究、市场政策影响分析或多来源供应链风险报告，且问题开放、可拆分、价值覆盖成本，才可单独设计 Research 模式。它必须限制并发、搜索轮次、总 token、来源类型和停止条件，并要求高风险结论人工复核。

### 项目证据

- [固定业务意图](../backend/app/intent/models.py)
- [受控经营查询](../backend/app/services/safe_query.py)
- [每日经营报告](../backend/app/services/report_service.py)
- [当前费用闸门](../backend/app/llm/guard.py)

### 设计取舍与缺口

当前拒绝过度架构化。Deep Research 若未来出现，应作为独立产品模式，而不是悄悄扩展现有聊天的调用次数和费用上限。

### 可能追问

“分析退款上涨原因”什么时候是固定数据分析，什么时候会升级为 Deep Research？

---

## 15. Borough 未来什么情况下应增加 LangChain、LlamaIndex 或更完整的 LangGraph 能力？

**来源文章：** [AI Agent 开发框架](https://xiaolinnote.com/ai/langchain/agent_frameworks.html)、[LangGraph 的核心优势](https://xiaolinnote.com/ai/langchain/langgraph_advantages.html)、[LangChain 版本演进](https://xiaolinnote.com/ai/langchain/version_evolution.html)

**项目状态：** 当前架构足够，扩展应由可测量问题驱动，而不是一次性补齐框架全家桶。

### 详细解答

如果模型供应商、标准 Tools 和中间件大量增加，重复适配、重试和消息转换成为主要成本，可评估 LangChain；如果复杂文档解析、向量/关键词多路检索、重排和连接器成为瓶颈，可评估 LlamaIndex；如果任务跨分钟或小时、需要人工审批、失败续跑和真正并行，可补 LangGraph Checkpointer、Interrupt 与事件流。

每次只解决一个独立痛点。例如先为长任务增加 Checkpoint，不必同时替换知识检索；先用 LlamaIndex 包装一个检索接口，不必把 Agent 全部迁入它的 Workflow。身份、商家隔离、安全 SQL、预算和审计继续留在业务核心层。

引入前用现有业务集做 PoC，对比代码复杂度、正确率、P95、token、故障恢复和观测完整度。框架支持某项功能不等于已经满足生产要求。

### 项目证据

- [当前服务边界](../backend/app/api/dependencies.py)
- [当前图编排](../backend/app/agent/graph.py)
- [知识检索](../backend/app/knowledge/retrieval.py)
- [项目开发计划](../docs/backend-development-plan.md)

### 设计取舍与缺口

渐进式引入避免大爆炸迁移，也让回滚清楚。缺口是尚未为这些架构阈值建立长期指标看板和正式 ADR。

### 可能追问

如果工具数量从 8 个涨到 50 个，但流程仍然固定，你会先引入 LangChain、Tool Router，还是只建立注册表？为什么？

---

## 项目能力现状矩阵

| 能力 | 当前状态 | 当前实现或边界 |
| --- | --- | --- |
| LangChain | 未使用 | 无 `langchain` 依赖 |
| LangGraph | 已使用 | `StateGraph`、类型化 State、节点和条件边 |
| LlamaIndex | 未使用 | 自定义 PostgreSQL 关键词检索 |
| LangChain4j | 未使用 | 参考项目也只是自定义 Java 图类 |
| Runnable / LCEL | 未使用 | 自定义 Service 接口和图节点 |
| 原生 Tool 注册 | 未使用 | 结构化意图 + 固定 Service 路由 |
| 单轮状态 | 已实现 | 每次请求创建新的 `AgentState` |
| 会话历史持久化 | 已实现 | Conversation、Message、Answer |
| Checkpointer | 未实现 | `graph.compile()` 未配置持久化器 |
| 完整短期语义记忆 | 部分实现 | 不会自动选择并注入完整历史 |
| 商家长期记忆 | 已实现 | `(merchant_id, category)` 摘要、压缩与召回 |
| Interrupt / 人工审批 | 未实现 | 当前只有可见降级，没有暂停接管 |
| 真正节点实时流 | 未实现 | SSE 运行中发心跳，完成后回放步骤 |
| Deep Research | 未实现且当前不需要 | 普通经营查询使用固定工作流 |

## 面试回答总纲

1. 不要说“项目用了 LangChain”；准确说法是直接使用 LangGraph，其他组件自建。
2. 选 LangGraph 是因为流程存在强顺序、安全查询、质量循环和显式状态，而不是因为它更流行。
3. 保存会话历史不等于完整短期记忆；当前没有 Checkpointer，也没有把全部历史注入模型。
4. 长期记忆已按商家和分类实现，但团队知识优先，实时事实仍查数据库。
5. 框架演进坚持按问题引入：集成复杂才加 LangChain，检索复杂才加 LlamaIndex，长任务与人工审批才补完整 LangGraph 能力。

