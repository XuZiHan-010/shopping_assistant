# 小林 LLM 工具调用专题 × Borough 项目问答设计

## 目标

新增 `interview/xiaolin-tools-project-qa.md`，把小林 Coding「LLM 工具调用」专题改写为 Borough 商家 AI 助手的项目面试题。全文使用中文，问题数量为 15–20 道，目标 18 道；每题必须由当前源码、测试或项目文档支撑，并明确标注已实现、部分实现或未实现。

## 方案比较与选择

### 方案 A：18 篇文章逐篇一对一改写

优点是原文覆盖最完整；缺点是 Function Calling 的训练流程和 WebRTC 语音链路与当前产品关联较弱，会稀释项目重点。

### 方案 B：完整阅读、强相关筛选后重新组题（采用）

完整浏览目录的 18 篇文章，排除 Function Calling 训练细节和 WebRTC 两篇弱相关内容。其余 16 篇围绕当前实现重新拆成 18 道题，重点覆盖 Function Calling 边界、结构化意图、MCP/Skill/A2A 选型、SSE、网关、Tool Routing、安全和容错。

### 方案 C：按协议概念写通用百科

优点是理论系统；缺点是容易脱离代码，并把产品没有的 MCP、A2A 或动态工具注册误写成现有能力，不采用。

## 文档结构

输出沿用已确认的 Agent/RAG 问答格式。每题固定包含：

1. 来源文章；
2. 项目状态；
3. 详细解答；
4. 项目证据；
5. 设计取舍与缺口；
6. 可能追问。

末尾增加能力现状速览和面试回答原则。

## 选题范围

1. Function Calling 原理与“模型决策、宿主执行”；
2. Borough 是否使用原生 Function Calling；
3. 当前结构化意图如何承担受控工具选择；
4. 工具 Schema、Pydantic 和服务端二次校验；
5. 是否需要引入原生 Function Calling；
6. MCP 的定位及项目是否需要 MCP；
7. MCP Host、Client、Server、Tools、Resources、Prompts 如何映射项目；
8. MCP 与 Function Calling 的区别；
9. Borough 的 Function Calling/MCP 选型条件；
10. 推理模型工具兼容性与模型选型；
11. Skill 与普通 Prompt 的区别；
12. 产品运行时 Skill、MCP、Function Calling 三层边界；
13. 是否需要 A2A；
14. MCP 传输与 Railway 部署；
15. SSE 与 WebSocket，以及项目当前 SSE 的真实边界；
16. 独立 LLM 网关与项目内部费用守卫；
17. 当前固定 Tool Routing 与未来动态路由；
18. 非法结构、参数错误、超时、失败、幂等与人工接管。

## 项目事实边界

- [DeepSeek 客户端](../../../backend/app/llm/deepseek.py) 只发送 `messages`、JSON 输出和 thinking 选项，没有 `tools`、`tool_choice` 或 `tool_calls` 处理，因此当前没有原生 Function Calling。
- 模型输出 `QueryIntent` JSON；[Pydantic 模型](../../../backend/app/intent/models.py)、白名单和 [SafeQueryService](../../../backend/app/services/safe_query.py) 决定是否以及怎样查询。LLM 不直接执行函数或 SQL。
- [Agent 图](../../../backend/app/agent/graph.py) 使用固定节点和条件边，不存在运行时工具注册表、动态工具发现或通用 ReAct 工具循环。
- 项目没有产品运行时 MCP、A2A 或 Skill 加载器；工作区 `.agents/skills` 属于开发工具环境，不能说成 Borough 产品能力。
- [LlmCostGuard](../../../backend/app/llm/guard.py) 是进程内统一费用防护与用量记录入口，但不是独立的 LiteLLM/Portkey 类网关服务。
- 当前聊天接口使用 SSE `step/done/error` 和心跳，不是 token 流；按现有 [路由实现](../../../backend/app/api/routes/chat.py)，Agent 任务完成后才依次发出保存的 `step` 与 `done`，因此不能声称已经满足真正的实时步骤流。
- DeepSeek 适配器对 401、403、429、其他 HTTP、超时、网络和坏响应分类并返回降级结果；结构化意图解析有有限重试。当前没有对所有上游故障统一自动重试，不能写成完整工具容错平台。

## 验收标准

- 新文档包含 18 道题，且每题六个固定模块完整；
- 最终文章链接只保留项目强相关的 16 篇，但说明已完整浏览专题 18 篇；
- 所有本地证据链接存在；
- 明确区分原生 Function Calling 与当前“结构化 JSON + 固定编排”；
- 明确区分产品运行时和 coding agent 的 Skill；
- 明确披露当前 SSE、网关、MCP、A2A、动态 Tool Routing 的真实缺口；
- 无占位符、真实密钥或秘密值；
- 不调用真实 DeepSeek，不执行会产生 token 费用的测试，不提交 Git。
