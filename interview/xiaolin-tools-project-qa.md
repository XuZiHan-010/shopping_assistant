# Borough 商家 AI 助手：LLM 工具调用面试问答

本文基于小林 Coding「LLM 工具调用」专题整理，但不按文章逐篇复述，而是把知识映射到 Borough 商家 AI 助手的真实实现、设计取舍和后续演进。

## 阅读与筛选范围

- 专题共 18 篇文章，已全部阅读并完成相关性判断。
- 最终保留 16 篇与本项目强相关的文章，覆盖 Function Calling、MCP、Skill、A2A、传输协议、LLM 网关、工具路由和可靠性。
- 未纳入最终问答的两篇是「Function Calling 模型怎么训练」和「WebRTC 与 WebSocket」。前者偏模型训练，本项目是应用层 Agent；后者主要面向实时音视频，而当前产品是文本分析助手，纳入会稀释面试重点。
- 文中的“当前已实现”“尚未实现”和“建议引入”严格区分；未来方案不能当作现状回答。

---

## 1. 什么是 Function Calling？模型、应用和工具分别负责什么？

**来源文章：** [Function Calling 是什么](https://xiaolinnote.com/ai/tools/1_function_calling.html)

**项目状态：** 当前 Borough 没有使用模型厂商的原生 Function Calling 协议，但采用了相似的职责分离：模型生成受控意图，应用负责校验和执行，工具结果再进入回答流程。

### 详细解答

Function Calling 不是让模型直接运行函数。应用先向模型提供工具名称、用途和参数 Schema；模型根据问题决定是否调用，并返回工具名及参数；真正的函数由应用执行，执行结果再作为上下文交给模型生成最终回答。因此，模型负责“提出调用建议”，宿主应用负责“授权、校验、执行和审计”。

这条边界对经营数据 Agent 尤其重要。商家问“最近七天退款金额最高的商品是什么”，模型可以表达查询意图，但不能获得数据库连接，更不能自行拼 SQL。后端必须从已验证身份取得 `merchant_id`，校验日期、指标、维度、排序和行数，再用参数绑定的模板查询。

Borough 目前走的是非原生版本：DeepSeek 返回 JSON 文本，`IntentService` 解析为 `QueryIntent`，随后固定图节点调用安全查询服务。它具备“模型提议、后端执行”的核心思想，却没有发送 `tools`、接收 `tool_calls` 或回传 `role=tool` 消息，所以面试时不能直接说“我们已经用了 Function Calling”。

### 项目证据

- [`LlmCallOptions`](../backend/app/llm/client.py) 只定义 JSON 输出和 thinking 开关，没有工具 Schema 或 `tool_choice`。
- [`DeepSeekLlmClient`](../backend/app/llm/deepseek.py) 发送 `messages`、`response_format`、`max_tokens` 等字段，不发送 `tools`。
- [`QueryIntent`](../backend/app/intent/models.py) 定义模型可表达的结构化意图；[`SafeQueryService`](../backend/app/services/safe_query.py) 执行真正查询。

### 设计取舍与缺口

当前方案依赖少、行为稳定，适合工具数量有限且安全要求高的 MVP；缺点是协议不标准，新增工具需要同时修改 Prompt、意图模型和图路由，也无法直接利用模型原生的多工具调用能力。未来只有在工具规模和交互复杂度明显上升时，才值得迁移到原生 Function Calling。

### 可能追问

如果模型返回了一个不存在的工具名，或者给退款查询多传了 `merchant_id`，你会在哪一层拒绝，拒绝后是否重试模型？

---

## 2. Borough 当前算不算用了 Function Calling？为什么？

**来源文章：** [Function Calling 是什么](https://xiaolinnote.com/ai/tools/1_function_calling.html)、[大模型如何学会调用工具](https://xiaolinnote.com/ai/tools/2_llm_tool_learning.html)

**项目状态：** 不算原生 Function Calling。当前是结构化输出驱动的应用内编排。

### 详细解答

判断标准要看协议链路，而不能只看“模型是否决定了下一步”。原生 Function Calling 至少包含：请求中声明工具 Schema；模型以专门字段返回工具调用；应用执行后以工具消息回传；模型基于结果继续推理。Borough 当前请求只要求 `json_object`，然后从普通 assistant 内容中 `json.loads`，没有上述工具消息闭环。

不过，项目已经实现了 Function Calling 最关键的安全原则。模型输出不是 SQL 或可执行代码，而是 `QueryIntent`；Pydantic 用 `extra="forbid"` 拒绝未知字段；白名单限制类别、指标、维度和过滤条件；后端决定调用查询、知识检索还是规则回答。这可以描述为“Function Calling 风格的受控工具编排”，但不能省略“非原生”。

面试中的准确回答是：“当前没有采用厂商原生 Function Calling，我们选择 JSON Schema 风格的结构化意图加固定图路由。这样便于在 MVP 阶段把安全边界掌握在后端；工具扩展后会评估迁移到标准 `tools/tool_calls` 协议。”

### 项目证据

- [`STRUCTURED_CALL_OPTIONS`](../backend/app/llm/client.py) 使用 JSON 输出并关闭结构化调用的 thinking。
- [`IntentService`](../backend/app/intent/service.py) 手工解析 JSON 并用 Pydantic 校验。
- [`AgentGraph`](../backend/app/agent/graph.py) 通过固定节点和条件边连接业务服务，而不是执行模型返回的任意函数名。

### 设计取舍与缺口

优点是可预测、易测试、不会因模型随意选择工具而扩大权限；代价是工具协议与供应商生态不兼容，难以支持模型连续调用、并行调用和动态工具发现。

### 可能追问

如果改为原生 Function Calling，现有 `QueryIntent`、Pydantic 校验和安全查询层哪些可以保留，哪些需要重构？

---

## 3. Borough 是怎样让模型“选择工具”，同时避免模型随意执行操作的？

**来源文章：** [大模型如何学会调用工具](https://xiaolinnote.com/ai/tools/2_llm_tool_learning.html)

**项目状态：** 当前让模型选择的是业务意图和回答模式，不是任意函数；真正的调用集合和路由由后端固定。

### 详细解答

项目采用两阶段意图识别。第一阶段判断问题类别和回答模式，第二阶段在确有必要时补全日期、指标、维度、过滤和跨域计划。输出必须落入 `QueryIntent` 的枚举和字段约束。随后 LangGraph 根据状态进入知识检索、数据查询、答案组织和 Reviewer 等固定节点。

因此模型的权限类似“填写一张受控工单”：它可以说明要查询哪个受支持指标、时间范围和分组方式，却不能指定 Python 函数、数据库表、任意列或 SQL。后端仍会注入可信的商家范围、限制预览行数，并使用参数化查询。

前置 `prefilter` 还会先用零 LLM 的确定性规则拦截明显范围外问题。这样既节省费用，也避免把所有输入都交给模型决定。工具选择不是单点依赖模型，而是规则、Schema、图路由和服务端授权共同完成。

### 项目证据

- [`intent/models.py`](../backend/app/intent/models.py) 使用枚举、受控查询计划和 `extra="forbid"`。
- [`intent/whitelist.py`](../backend/app/intent/whitelist.py) 定义可接受的业务能力范围。
- [`agent/prefilter.py`](../backend/app/agent/prefilter.py) 实现零 LLM 前置判断；[`agent/graph.py`](../backend/app/agent/graph.py) 定义固定路由。

### 设计取舍与缺口

这种路由适合当前有限业务域，安全性高于让模型直接挑选大量函数。缺口是意图模型会逐渐膨胀；当工具达到几十个、不同角色看到不同工具时，需要引入工具注册表、权限过滤和语义路由，而不是把所有描述塞进一个 Prompt。

### 可能追问

为什么不让模型直接返回 `query_orders`、`query_refunds` 这样的函数名？固定意图模型会不会反而降低扩展性？

---

## 4. 为什么工具参数必须做 Schema 校验？Borough 做了哪些防护？

**来源文章：** [Function Calling 是什么](https://xiaolinnote.com/ai/tools/1_function_calling.html)、[如何提升工具调用可靠性](https://xiaolinnote.com/ai/tools/18_tool_reliability.html)

**项目状态：** 已实现多层校验：Pydantic 结构校验、业务白名单、可信身份注入、查询模板和结果限制。

### 详细解答

模型输出即使是 JSON，也仍是不可信输入。合法 JSON 不代表业务合法：日期可能反转、指标可能不存在、过滤字段可能越权、行数可能过大，也可能夹带服务端不应接受的 `merchant_id`。因此 Schema 校验只是第一层，后面还需要语义校验、权限校验和执行层约束。

Borough 用 Pydantic 拒绝未知字段和非法枚举；查询服务只接受白名单中的业务维度与指标；商家身份从认证后的 `MerchantContext` 获取，而不是相信模型或前端；SQL 由后端模板生成，所有值参数绑定，并限制日期范围、商家范围和最大行数。即使意图层被 Prompt Injection 影响，执行层也不能越过这些硬边界。

失败处理同样重要。结构化输出无效时，意图服务只进行有限次数修复；预算耗尽、上游不可用或校验仍失败时，回答必须显示降级状态，不能用规则结果伪装成模型结论。

### 项目证据

- [`intent/models.py`](../backend/app/intent/models.py) 定义受控字段和禁止额外字段。
- [`services/safe_query.py`](../backend/app/services/safe_query.py) 承担白名单、范围和安全执行。
- [`tests/integration/services/test_safe_query_security.py`](../backend/tests/integration/services/test_safe_query_security.py) 验证安全查询边界。
- [`core/security.py`](../backend/app/core/security.py) 解析可信商家身份。

### 设计取舍与缺口

多层校验增加了一些样板代码，却把“模型犯错”变成可预期的业务错误。当前缺口主要在未来写工具：一旦增加修改优惠券、触发补偿等副作用操作，还需增加风险分级、确认令牌、幂等键和操作审计。

### 可能追问

Pydantic 校验通过后为什么仍不能直接执行？能否举一个“结构合法但越权”的参数示例？

---

## 5. Borough 未来是否应该切换到原生 Function Calling？

**来源文章：** [Function Calling 和 MCP 应该怎么用](https://xiaolinnote.com/ai/tools/7_fc_vs_mcp_usage.html)

**项目状态：** 目前没有切换必要；达到多工具、多轮调用或多供应商兼容阈值后再迁移更合理。

### 详细解答

当前业务路径稳定，模型只需生成有限的结构化意图，固定图比开放式 ReAct 循环更容易控制延迟、费用和数据权限。如果现在改成原生 Function Calling，主要获得的是协议标准化，却会同时引入工具选择不稳定、循环次数控制、工具消息持久化和供应商兼容测试，收益未必覆盖复杂度。

适合迁移的信号包括：工具数量增长到难以用单一意图模型维护；一个问题确实需要模型连续决定多个工具；出现可并行的数据源；需要在多个 LLM 提供商之间共享工具定义；或者工具本身要被其他 Agent 复用。迁移时仍不能删除现有安全层，而应把 `QueryIntent` 模型转成工具参数 Schema，把 `SafeQueryService` 保留为执行器。

建议采用分阶段方案：先选一个只读、低风险工具做原生调用试点；限制单轮最大工具次数和总 token；记录工具名、参数摘要、耗时和结果状态；用现有问答集对比成功率、延迟和成本，再决定是否扩大范围。

### 项目证据

- [`agent/graph.py`](../backend/app/agent/graph.py) 显示当前是可审计的固定工作流。
- [`llm/guard.py`](../backend/app/llm/guard.py) 已具备按用途记录和约束模型费用的基础，可扩展到工具循环预算。
- [`tests/unit/intent/test_service.py`](../backend/tests/unit/intent/test_service.py) 已覆盖结构化意图行为，可作为迁移回归基线。

### 设计取舍与缺口

结论不是“Function Calling 不好”，而是架构复杂度应与真实需求匹配。最需要补的是可量化的迁移门槛和工具调用评测集，而不是先替换协议。

### 可能追问

你会选哪一个现有能力做 Function Calling 试点？成功率、P95 延迟和单问成本的验收阈值如何制定？

---

## 6. MCP 解决什么问题？Borough 现在需要 MCP 吗？

**来源文章：** [MCP 是什么](https://xiaolinnote.com/ai/tools/4_what_is_mcp.html)

**项目状态：** 当前产品运行时没有 MCP，现阶段也不是必需；当同一批能力需要被多个 Agent 或客户端复用时才有明显价值。

### 详细解答

MCP 解决的是“AI 应用如何用统一协议连接外部工具与上下文”的集成问题。它规范能力发现、参数描述、调用和资源访问，减少每个宿主为每个数据源各写一套适配器。它不替代模型推理，也不自动解决授权、租户隔离和业务安全。

Borough 当前只有一个主要宿主——FastAPI 后端，业务服务也都在同一代码库内。把内部函数马上包装成 MCP Server，只会增加网络边界、鉴权、部署和故障面，并不会提高现有用户价值。因此目前保留模块化 Service 接口更简单。

如果以后知识库、指标口径和受控经营查询要同时服务商家助手、客服助手、运营 Copilot 和 IDE 内部工具，那么 MCP 的复用价值会出现。第一批应该暴露只读、低风险能力，例如“检索指标定义”和“检索公开团队知识”；不能暴露原始数据库或任意 SQL。

### 项目证据

- [`knowledge/retrieval.py`](../backend/app/knowledge/retrieval.py) 与 [`services/safe_query.py`](../backend/app/services/safe_query.py) 当前作为进程内能力被图节点调用。
- [`api/dependencies.py`](../backend/app/api/dependencies.py) 在单一 FastAPI 宿主中完成身份、LLM 和业务服务装配。
- 仓库没有产品运行时 MCP Client、MCP Server 或 MCP 传输层实现。

### 设计取舍与缺口

暂不引入遵循 YAGNI，避免“为了协议而协议”。未来引入前必须先定义服务身份、商家上下文传播、工具级权限、调用审计、超时和降级，否则 MCP 只会把现有安全问题搬到网络上。

### 可能追问

为什么知识库后台已经有 HTTP API，还可能需要 MCP？普通 REST API 与 MCP 的消费者和能力发现方式有什么不同？

---

## 7. MCP 的 Host、Client、Server、Tools、Resources、Prompts 如何映射到 Borough？

**来源文章：** [MCP 有哪些核心组件](https://xiaolinnote.com/ai/tools/5_mcp_components.html)

**项目状态：** 以下是未来架构映射，不是当前已实现功能。

### 详细解答

如果引入 MCP，Borough Agent 后端会是 Host，负责用户体验、模型编排、权限决策和上下文管理；Host 内的 MCP Client 维护与各 Server 的连接；MCP Server 则包装某个明确能力域，如指标知识、经营只读查询或工单系统。

Tools 适合有明确输入输出的动作，例如 `get_metric_definition`、`query_refund_summary`；Resources 更适合可读取的上下文，例如业务规则文档或指标目录；Prompts 是 Server 提供的可复用提示模板，但最终系统级行为约束仍应由 Host 掌握，不能让第三方 Server 覆盖身份隔离和安全政策。

商家上下文不能作为模型自由填写的工具参数。Host 必须从认证结果获得 `merchant_id`，以不可伪造的服务端上下文或短期凭证传递给 Server。Server 还要二次校验权限，并只返回当前商家的最小必要数据。

### 项目证据

- [`core/security.py`](../backend/app/core/security.py) 是当前可信商家上下文的来源。
- [`knowledge/retrieval.py`](../backend/app/knowledge/retrieval.py) 可对应未来只读知识能力，但目前只是本地模块。
- [`intent/models.py`](../backend/app/intent/models.py) 可作为未来 Tool 输入 Schema 的起点。

### 设计取舍与缺口

这种映射的价值是职责清楚，但拆分过早会增加分布式事务和可观测性成本。是否拆 Server 应按独立复用、权限边界和扩缩容需求决定，而不是按每个 Python 文件拆一个服务。

### 可能追问

指标口径更适合作为 Resource 还是 Tool？如果内容需要按自然语言检索而不是按 URI 精确读取，你会怎样设计？

---

## 8. Function Calling 和 MCP 有什么区别？两者是替代关系吗？

**来源文章：** [MCP 和 Function Calling 的区别](https://xiaolinnote.com/ai/tools/6_mcp_vs_fc.html)

**项目状态：** 当前两者都未原生采用；项目内部的结构化意图更接近 Function Calling 的决策层，业务 Service 更接近未来可被协议包装的执行层。

### 详细解答

Function Calling 主要描述模型与宿主之间如何表达“调用哪个工具、使用什么参数”；MCP 主要描述宿主如何发现和连接外部能力。一个在模型交互层，一个在系统集成层，因此可以组合：模型返回 tool call，Host 再通过 MCP Client 调用远端 Server。

MCP 不会让不支持工具调用的模型自动变得可靠，Function Calling 也不会解决十个外部系统的统一连接、能力发现和生命周期管理。无论采用哪个协议，应用仍要负责权限校验、参数约束、超时、重试、审计和结果裁剪。

对 Borough 来说，短期如果只需要优化模型决策，可以先评估原生 Function Calling；只有能力需要跨应用复用或由外部团队独立提供时，再评估 MCP。两者不应被打包成一次“大改造”。

### 项目证据

- [`llm/deepseek.py`](../backend/app/llm/deepseek.py) 当前没有 Function Calling 请求字段。
- [`agent/graph.py`](../backend/app/agent/graph.py) 当前直接调用进程内服务，没有 MCP Client。
- [`services/safe_query.py`](../backend/app/services/safe_query.py) 是可被两种协议复用的业务安全核心。

### 设计取舍与缺口

把决策协议和连接协议分开评估，可以避免为了使用 MCP 而重写模型层，也避免为了使用 Function Calling 而把所有服务网络化。当前项目更缺工具效果评测和失败观测，而不是协议名称。

### 可能追问

如果 DeepSeek 返回原生 tool call，但实际数据能力由 MCP Server 提供，完整的一轮消息和调用链是什么？

---

## 9. Borough 应该如何选择 Function Calling、MCP 或普通内部函数？

**来源文章：** [Function Calling 和 MCP 应该怎么用](https://xiaolinnote.com/ai/tools/7_fc_vs_mcp_usage.html)

**项目状态：** 当前优先使用普通内部 Service 加固定编排；原生 Function Calling 和 MCP 分别设独立引入条件。

### 详细解答

选择可以看两个轴：谁决定调用，以及能力是否跨宿主复用。调用路径固定、能力仅供一个后端使用时，普通函数最简单；需要模型动态选择多个动作时，引入 Function Calling；同一能力需要被多个 AI 宿主标准化发现和调用时，引入 MCP。

当前查询、知识检索、回答和审核都属于一个明确的经营分析工作流，固定 LangGraph 足够。未来若“查库存后决定查物流，再决定是否创建工单”，模型动态工具调用才有价值；若这些库存、物流、工单能力还要提供给客服 Agent 和运营 Agent，才进一步适合 MCP。

还要叠加风险维度。只读查询可以允许自动执行；高成本查询要先估算；修改数据、发券、赔付等写操作需要显式确认或人工审批。协议选择不能替代动作风险策略。

### 项目证据

- [`agent/graph.py`](../backend/app/agent/graph.py) 展示当前固定流程。
- [`api/dependencies.py`](../backend/app/api/dependencies.py) 展示内部服务装配。
- [`services/safe_query.py`](../backend/app/services/safe_query.py) 展示查询执行前的硬约束。

### 设计取舍与缺口

建议维护一张能力目录，记录消费者数量、是否只读、调用频率、延迟要求和风险等级。只有跨过明确阈值才升级协议，避免把技术潮流当作产品需求。

### 可能追问

同一个“查询退款明细”能力既可做内部函数又可做 MCP Tool，你会用哪些指标证明拆出去是值得的？

---

## 10. 推理模型一定更适合工具调用吗？Borough 如何处理模型兼容性？

**来源文章：** [为什么推理模型不一定适合 MCP](https://xiaolinnote.com/ai/tools/8_reasoning_no_mcp.html)

**项目状态：** 当前使用 DeepSeek OpenAI 兼容聊天接口，结构化意图调用会关闭 thinking；没有假设“推理越长，工具调用越准”。

### 详细解答

工具调用更看重协议遵循、参数准确、停止条件和错误恢复，不等同于通用推理能力。推理模型可能在复杂规划上更强，但也可能增加延迟和 token，或在严格 JSON、工具调用字段和多轮工具消息上存在兼容差异。因此必须针对具体模型、API 版本和任务评测，不能只按模型标签判断。

Borough 对结构化意图使用 `response_format=json_object`，并在配置允许时显式关闭 thinking，目标是减少输出噪声、降低成本并提高 Schema 稳定性。当前默认模型是 `deepseek-v4-flash`；任何切换都应验证结构化成功率、业务答案质量、P95 延迟和单问成本。

如果未来采用原生 Function Calling，应建立模型兼容矩阵：是否支持 tools、强制 tool choice、多工具并行、严格 Schema、流式 tool call、上下文长度和错误码；通过真实业务离线集评测后再上线，而不是只看厂商文档中的“支持”。

### 项目证据

- [`llm/client.py`](../backend/app/llm/client.py) 为结构化调用定义 `thinking="disabled"`。
- [`llm/deepseek.py`](../backend/app/llm/deepseek.py) 根据选项发送 thinking 和 JSON 输出配置。
- [`core/config.py`](../backend/app/core/config.py) 定义模型与单次输出等运行参数。

### 设计取舍与缺口

当前策略偏确定性和费用控制，适合意图解析；复杂回答或 Reviewer 是否关闭 thinking 应分用途评估。项目还缺一份按 `purpose` 分模型的基准报告，不能凭感觉统一选择模型。

### 可能追问

如果关闭 thinking 后 JSON 合法率提高但复杂跨域意图准确率下降，你会怎样分流模型或设计两阶段调用？

---

## 11. Skill 是什么？Borough 现在有没有产品运行时 Skill？

**来源文章：** [Agent Skill 是什么](https://xiaolinnote.com/ai/tools/9_skill.html)

**项目状态：** Borough 产品运行时没有 Skill 加载与执行机制；仓库中的 `.agents/skills` 属于开发代理工作流，不能算产品能力。

### 详细解答

Skill 可以理解为一套可复用的任务说明、资源和脚本，把某类工作的步骤、边界和产出格式封装起来。它比一句 Prompt 更完整，通常还包含参考资料、工具使用说明和验证方式；它也不同于普通函数，因为 Skill 主要提供“怎样完成一类任务”的程序性知识。

当前 Borough 的业务流程固化在 Python Service、LangGraph 节点和 Prompt 文件中，运行时不会根据任务发现或加载 `SKILL.md`。开发环境的技能文件只约束 coding agent 如何修改仓库，对线上商家助手不可见。因此面试时应回答“开发流程使用 Skill，但产品 Agent 尚未实现 Skill 系统”。

如果未来日报、退款诊断或大促复盘的流程频繁变化，且需要运营人员维护步骤，可以将其抽象成版本化 Skill；但鉴权、SQL 安全和费用限制仍应写在代码层，不能仅靠文本说明保证。

### 项目证据

- [`agent/graph.py`](../backend/app/agent/graph.py) 的节点在代码中静态注册。
- [`intent/prompts.py`](../backend/app/intent/prompts.py) 是普通运行时 Prompt，并非 Skill 包。
- [工作区开发指南](../AGENTS.md) 与 `.agents/skills` 服务开发代理，不由线上 FastAPI 加载。

### 设计取舍与缺口

当前不引入运行时 Skill，避免动态脚本、版本兼容和权限边界复杂化。若引入，应先限定为声明式、只读流程，建立版本、签名、审核、灰度和回滚机制，禁止 Skill 绕过安全服务直接访问数据库。

### 可能追问

把“每日经营报告”做成 Skill 与继续写成 `ReportService` 有什么区别？哪些部分必须留在代码中？

---

## 12. Prompt、Skill、Function Calling 和 MCP 在 Borough 中分别属于哪一层？

**来源文章：** [MCP 和 Skill 的区别](https://xiaolinnote.com/ai/tools/10_mcp_vs_skill.html)、[Function Calling、Skill 和 MCP 怎么配合](https://xiaolinnote.com/ai/tools/11_fc_skill_mcp.html)

**项目状态：** 当前已实现 Prompt 和代码工作流；原生 Function Calling、产品运行时 Skill、MCP 均未实现。

### 详细解答

四者解决的问题不同。Prompt 定义一次模型调用的角色、规则和输出要求；Skill 描述完成一类任务的方法与流程；Function Calling 让模型以结构化方式选择动作；MCP 让宿主以统一协议连接外部能力。它们可以叠加，却不能互相替代。

以“分析退款上涨”为例：Prompt 要求模型解释口径并输出结构化意图；未来 Skill 可以规定先核对退款金额、再分商品和原因、最后给两条建议；Function Calling 可以让模型选择 `query_refund_summary`；MCP 可以把这个查询连接到独立数据服务。最终权限、参数和执行仍由后端控制。

当前 Borough 把流程写在 LangGraph，把调用要求写在 Prompt，把能力实现写在 Service。这个分层已经清楚，未来可以逐层替换协议，无需一次性重构全部系统。

### 项目证据

- [`intent/prompts.py`](../backend/app/intent/prompts.py) 定义意图 Prompt。
- [`agent/graph.py`](../backend/app/agent/graph.py) 定义任务步骤。
- [`services/safe_query.py`](../backend/app/services/safe_query.py) 定义受控能力执行。
- [`llm/deepseek.py`](../backend/app/llm/deepseek.py) 证明当前没有原生工具协议。

### 设计取舍与缺口

最重要的原则是安全政策下沉到代码，流程知识可以上移到 Prompt 或 Skill，连接协议按复用需要选择。当前缺少统一的 Prompt/流程版本和评测元数据，后续应先补版本治理，再考虑动态 Skill。

### 可能追问

如果 Skill 中写了“必要时查询订单”，到底由 Skill、模型还是 Host 决定调用？如何防止职责重叠？

---

## 13. A2A 协议解决什么问题？Borough 需要多 Agent 互联吗？

**来源文章：** [A2A 协议是什么](https://xiaolinnote.com/ai/tools/12_a2a_protocol.html)

**项目状态：** 当前没有 A2A。意图识别、回答和 Reviewer 是同一应用内的节点或角色，不是通过协议协作的独立 Agent。

### 详细解答

A2A 面向独立 Agent 之间的能力发现、任务委派、状态跟踪和结果交换。它适合不同团队或系统拥有各自 Agent，任务持续时间较长、需要异步协作的场景。它与 MCP 的区别是：MCP 更偏工具和上下文接入，A2A 更偏自主 Agent 之间的任务协同。

Borough 当前是一条单体可控工作流：同一个请求内完成意图、检索、查询、回答、审核和持久化。Reviewer 虽然可能使用独立模型调用，但没有独立身份、任务队列或协商协议，因此不能称为 A2A。现在加入 A2A 会放大延迟、费用、状态一致性和故障排查难度。

只有在出现真正独立的客服 Agent、供应链 Agent、营销 Agent，并且它们由不同系统维护、需要互相委托长任务时，A2A 才值得评估。即便如此，最初也应通过明确 API 和队列验证协作边界，而不是直接引入协议。

### 项目证据

- [`agent/graph.py`](../backend/app/agent/graph.py) 将所有能力编排在同一状态图中。
- [`agent/state.py`](../backend/app/agent/state.py) 使用同一个 `AgentState` 传递一轮上下文。
- [`services/review_service.py`](../backend/app/services/review_service.py) 是应用内 Reviewer 服务，不是远端 Agent。

### 设计取舍与缺口

当前单工作流更容易保证商家隔离、预算上限和确定性。未来拆 Agent 前，要先解决端到端 trace、跨 Agent 身份传递、总预算、取消传播和最终责任归属。

### 可能追问

如果营销 Agent 委托数据 Agent 分析活动效果，`merchant_id`、预算和任务取消应由谁传播和校验？

---

## 14. 如果 Borough 引入远程 MCP，在 Railway 上应选择什么传输方式？

**来源文章：** [MCP 的传输方式](https://xiaolinnote.com/ai/tools/13_mcp_transport.html)

**项目状态：** 当前没有 MCP 传输层。未来跨 Railway Service 连接时，优先考虑基于 HTTPS 的 Streamable HTTP；本地进程工具才考虑 stdio。

### 详细解答

stdio 适合 Host 在同一机器启动和管理本地 Server，部署简单、攻击面小，但不适合多个云服务共享。远程 MCP 更适合 Streamable HTTP，通过标准 HTTP 基础设施完成鉴权、负载均衡、超时和观测。旧式 HTTP+SSE 兼容方案不应作为新系统默认选择。

在 Railway 中，MCP Server 会是独立私网服务或受保护的公网服务。Host 使用服务凭证连接，请求还要携带可验证的商家范围或由 Server 根据服务端映射恢复权限。传输层必须设置连接超时、单次调用超时、响应大小上限和并发上限，日志只记录参数摘要，不能记录隐私明细。

不建议为了“实时”改用 WebSocket。工具调用通常是请求—响应或有限流式结果，HTTP 更容易与现有 FastAPI、代理和运维体系结合。选择协议应由通信语义决定，而不是由技术新颖度决定。

### 项目证据

- [`backend/railway.json`](../backend/railway.json) 定义当前后端 Railway 部署入口。
- [`core/config.py`](../backend/app/core/config.py) 展示现有外部服务通过配置注入的模式。
- 当前仓库不存在 MCP 传输实现，本题方案均为未来设计。

### 设计取舍与缺口

远程 MCP 带来能力复用，也引入网络故障和凭证管理。真正实施前需做威胁模型，并确定私网、mTLS 或短期令牌方案；不能把前端演示 Token 直接当服务间凭证。

### 可能追问

当 MCP Server 超时但请求可能已经执行成功时，Host 能否直接重试？只读和写工具的策略有什么不同？

---

## 15. SSE 和 WebSocket 有什么差异？Borough 当前为什么使用 SSE，是否真正实时？

**来源文章：** [SSE 和 WebSocket 的区别](https://xiaolinnote.com/ai/tools/14_sse_vs_websocket.html)

**项目状态：** 聊天接口已使用 SSE 响应，但不是 token 流；当前运行中只周期性发送注释心跳，任务完成后才依次发送 `step` 和 `done`。

### 详细解答

SSE 是服务端到客户端的单向文本事件流，天然适合模型输出、进度和通知；WebSocket 是双向长连接，更适合双方持续高频交互。Borough 的一次聊天由客户端用普通 POST 提交，服务端再持续返回结果，因此 SSE 足够，无需承担 WebSocket 的连接状态和双向协议复杂度。

前端不能直接使用只支持 GET 的 `EventSource`，因为聊天需要 POST 请求体、鉴权头和明确的错误契约，所以项目使用 `fetch + ReadableStream` 解析 `text/event-stream`。协议只定义 `step`、`done` 和 `error` 三类业务事件，并用注释心跳维持连接。

必须如实说明当前实现的实时性限制：后端把完整 `service.submit()` 放进后台任务，等待期间每 15 秒发一次心跳；任务结束后才遍历 `execution.steps`。因此页面能避免代理空闲断连，但看不到节点完成即刻推送，也没有逐 token 输出。若要真正实时，需要让图执行产生异步事件，并在节点完成时写入流，同时处理取消、异常和最终持久化一致性。

### 项目证据

- [`api/routes/chat.py`](../backend/app/api/routes/chat.py) 中 `_sse_body` 创建任务、发送心跳，并在任务完成后发送步骤。
- [`frontend/src/api/sse.ts`](../frontend/src/api/sse.ts) 使用 `fetch` 流式解析，而非 `EventSource`。
- [`tests/api/test_chat.py`](../backend/tests/api/test_chat.py) 覆盖 SSE 事件契约。

### 设计取舍与缺口

当前设计先保证断连管理和统一响应契约，复杂度较低；用户感知上的“思考进度”仍是完成后回放。若产品验收要求步骤一秒内可见，这是明确待修复项，不应把心跳当作实时步骤。

### 可能追问

把 LangGraph 节点实时推到 SSE 后，如果客户端中途断开，是否应该取消模型和数据库查询？回答持久化如何保持一致？

---

## 16. Borough 是否需要 LLM 网关？当前的费用闸门算网关吗？

**来源文章：** [LLM Gateway 是什么](https://xiaolinnote.com/ai/tools/16_llm_gateway.html)

**项目状态：** 没有独立 LLM 网关。`LlmCostGuard` 是应用内统一费用与使用量闸门，具备部分网关能力，但不负责多供应商路由、统一协议代理或跨服务治理。

### 详细解答

LLM 网关通常位于业务应用和多个模型供应商之间，集中处理鉴权、模型路由、限流、重试、降级、缓存、审计、成本归集和可观测性。它在多应用、多模型、多团队场景中能减少重复逻辑，但也会成为新的关键依赖和潜在单点。

Borough 目前只有一个后端和一个约定云端供应商 DeepSeek。应用内 `LlmCostGuard` 已在每次模型调用前做日预算原子预留，调用后按真实 usage 对账，并按商家和调用用途落库；`DeepSeekLlmClient` 统一错误分类和超时。这足以支撑当前规模，但准确名称是“内部 LLM 调用层/费用闸门”，不是独立网关。

当出现两个以上供应商、多个后端服务、按场景动态选模、跨服务统一密钥轮换或集中熔断时，再引入网关更合理。即使引入，商家级业务预算和降级展示仍应由应用负责，因为网关通常不了解一次经营问答的业务语义。

### 项目证据

- [`llm/guard.py`](../backend/app/llm/guard.py) 实现日预算预留、对账和 usage 记录。
- [`repositories/llm_budget.py`](../backend/app/repositories/llm_budget.py) 提供数据库原子预算操作。
- [`llm/deepseek.py`](../backend/app/llm/deepseek.py) 是唯一真实云端模型适配器。
- [`api/dependencies.py`](../backend/app/api/dependencies.py) 将受保护的客户端注入不同模型用途。

### 设计取舍与缺口

现阶段不新增网关可降低部署和排障成本。当前需要优先补齐的是费用仪表盘、异常率告警和分用途趋势，而不是增加代理层。将来选网关时必须验证商家标签是否端到端保留，以及网关故障时的降级策略。

### 可能追问

如果引入 LiteLLM 或自建网关，应用内 `LlmCostGuard` 是否删除？供应商账单、网关统计和业务 `llm_usage` 不一致时以谁为准？

---

## 17. 工具很多时如何做 Tool Routing？Borough 当前方案能扩展到多少工具？

**来源文章：** [Tool Routing 怎么做](https://xiaolinnote.com/ai/tools/17_tool_routing.html)

**项目状态：** 当前是业务意图分类加固定路由，没有动态工具注册表、工具描述检索或按权限生成工具集合。

### 详细解答

把几十甚至上百个工具的完整 Schema 全塞给模型，会增加输入 token、提高误选概率，也可能把用户无权使用的能力暴露出来。常见路由方式包括规则预筛、类别分类、语义检索、分层路由和基于角色/风险的权限过滤，然后只向模型暴露少量候选工具。

Borough 已有一个适合小规模工具集的雏形：零 LLM prefilter 先判断是否在业务范围内，两阶段意图识别把问题分到数据、知识等模式，LangGraph 再进入固定节点。当前能力有限，这比通用工具路由器更稳定且便宜；但它没有统一 Tool Registry，也不能运行时新增工具。

未来可为每个工具登记名称、业务域、输入 Schema、读写属性、成本、超时和所需权限。路由顺序应为：认证并取得商家上下文；规则排除越权与高风险工具；用分类或向量召回候选；模型从小集合选择；服务端再次校验并执行。路由质量要分别统计召回率、选择准确率和执行成功率。

### 项目证据

- [`agent/prefilter.py`](../backend/app/agent/prefilter.py) 实现规则预筛。
- [`intent/service.py`](../backend/app/intent/service.py) 实现两阶段意图识别。
- [`agent/graph.py`](../backend/app/agent/graph.py) 采用静态节点和条件边。
- [`core/security.py`](../backend/app/core/security.py) 提供路由前必须具备的可信权限上下文。

### 设计取舍与缺口

目前没有必要为少量固定能力构建向量化工具检索。更现实的下一步是先建立代码级工具目录和指标，再在工具数量、Schema token 或误路由率达到阈值后引入语义路由。

### 可能追问

工具路由召回 Top-K 中没有正确工具时，模型应该自由选择全量工具、回答无法处理，还是回退到人工？为什么？

---

## 18. 如何保证工具调用可靠？失败、重试、幂等和转人工边界怎么设计？

**来源文章：** [如何提升工具调用可靠性](https://xiaolinnote.com/ai/tools/18_tool_reliability.html)

**项目状态：** 已实现结构化输出有限重试、上游错误分类、费用上限、会话请求幂等和可见降级；尚未实现通用工具重试策略、写工具幂等与人工接管流程。

### 详细解答

可靠性应分层处理。模型层关注是否选择正确能力、参数是否通过 Schema；执行层关注超时、限流、网络错误和业务错误；工作流层关注最大调用次数、总预算、取消和回退；产品层关注用户是否看到真实状态以及何时转人工。不能用一个无差别重试装饰器覆盖所有失败。

当前意图 JSON 无效时会做有限修复，持续失败则显式降级；DeepSeek 客户端区分鉴权、限流、HTTP、超时、网络和响应格式错误；`LlmCostGuard` 防止单请求和每日费用失控；聊天使用 `client_request_id` 与请求摘要处理并发和重放，成功请求可返回已保存结果。这些机制主要保护模型调用和整轮问答。

重试必须看副作用。结构化解析失败可重试模型；只读查询遇到瞬时网络错误可退避重试；创建工单、发券或赔付不能盲目重试，必须使用工具级幂等键，并在超时后先查执行状态。参数越权、业务规则拒绝和预算耗尽都不是可重试错误。

当前没有真正的人工接管。建议定义三类边界：自动成功——工具和 Reviewer 均通过；可见降级——部分来源不可用但仍能给有标注的有限答案；转人工——身份/权限冲突、连续工具失败、涉及高风险写操作、关键数据互相矛盾或用户明确要求人工。转人工记录应包含脱敏上下文、失败节点、已尝试动作和关联 trace，不能只返回一句“请联系客服”。

### 项目证据

- [`intent/service.py`](../backend/app/intent/service.py) 实现结构化解析与有限重试。
- [`llm/deepseek.py`](../backend/app/llm/deepseek.py) 分类处理上游失败。
- [`llm/guard.py`](../backend/app/llm/guard.py) 限制并记录费用。
- [`services/chat_service.py`](../backend/app/services/chat_service.py) 处理 `client_request_id` 幂等、并发和失败状态。
- [`api/routes/chat.py`](../backend/app/api/routes/chat.py) 用结构化 `error` 事件结束失败流。

### 设计取舍与缺口

现有保护足以覆盖只读经营分析，但不能直接复制到未来写工具。下一步应建立统一错误分类、每类动作的重试矩阵、工具调用日志、trace 关联、熔断告警和人工工单接口，并用故障注入测试验证。

### 可能追问

模型调用成功、创建工单接口超时、客户端又重发同一聊天请求时，如何保证最多创建一个工单，同时还能向用户返回最终状态？

---

## 项目能力现状矩阵

| 能力 | 当前状态 | 当前实现 | 是否建议现在引入 |
| --- | --- | --- | --- |
| 原生 Function Calling | 未实现 | JSON 结构化意图 + Pydantic | 暂不；工具规模扩大后试点 |
| 动态 Tool Routing | 未实现 | prefilter + 两阶段意图 + 固定图 | 暂不；先建工具目录和指标 |
| MCP | 未实现 | 进程内 Service | 暂不；跨宿主复用后考虑 |
| 产品运行时 Skill | 未实现 | Prompt + Python 工作流 | 暂不；高频可变 SOP 出现后考虑 |
| A2A | 未实现 | 单应用 LangGraph 节点 | 不需要；出现独立 Agent 后再评估 |
| 独立 LLM Gateway | 未实现 | `LlmCostGuard` + DeepSeek Client | 暂不；多供应商、多服务后考虑 |
| SSE | 已实现但非真正实时步骤 | 心跳，任务完成后发送 step/done | 应按产品体验决定是否升级 |
| 工具可靠性基础 | 部分实现 | 校验、有限重试、预算、幂等、可见降级 | 继续补统一错误与人工接管 |

## 面试回答总纲

回答这组问题时，可以始终沿用四句话：

1. **先讲事实：** 当前不是原生 Function Calling/MCP，而是结构化意图和固定工作流。
2. **再讲原因：** 工具数量有限、经营数据安全要求高，确定性和可审计性优先。
3. **再讲已有能力：** Pydantic、白名单、可信商家身份、安全查询、费用闸门、幂等和可见降级已经形成防线。
4. **最后讲演进阈值：** 多工具动态规划引入 Function Calling，跨宿主复用引入 MCP，多应用多模型引入网关，独立 Agent 协作才考虑 A2A。
