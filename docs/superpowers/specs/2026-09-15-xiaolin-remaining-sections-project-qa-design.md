# 小林 Coding 剩余两个专题项目化问答设计

## 目标

完成小林 Coding 大模型面试专栏中剩余的“大模型工程”和“LangChain 框架”两个专题，将文章知识转换为 Borough 商家 AI 助手的项目面试问答。

最终新增两份文档：

- `interview/xiaolin-llm-engineering-project-qa.md`
- `interview/xiaolin-langchain-project-qa.md`

## 已确认的内容范围

### 大模型工程

专题共 23 篇，全部阅读后只保留 13 篇与当前应用工程强相关的文章，整理为 18 道题。

保留主题：

1. LLM 与传统 NLP；
2. Tokenizer 与 token 成本；
3. 解码策略；
4. Temperature、Top-P、Top-K；
5. KV Cache 与 Prompt Caching；
6. Prompt 工程；
7. CoT；
8. 幻觉；
9. MoE 与 DeepSeek 成本；
10. 模型部署框架与 API/自托管取舍；
11. LLM 评测；
12. 模型选型；
13. 长上下文与 Lost in the Middle。

排除主题：Transformer 结构细节、MHA/MQA/GQA/Flash Attention、位置编码、预训练、Scaling Law、微调、LoRA、Post-Training、DPO/PPO、量化。这些知识并非不重要，而是 Borough 当前通过云端 API 使用 DeepSeek，不训练或托管基础模型，与项目面试叙事关联较弱。

### LangChain 框架

专题共 12 篇，全部与当前框架选型或架构边界相关，全部保留并扩展为 15 道项目化问题。

覆盖主题：

1. Agent 框架选型；
2. Chain、Runnable、LCEL 的设计思想；
3. LangChain 分层架构；
4. 构建 Agent 的步骤；
5. Tool 注册与可信上下文；
6. 短期记忆；
7. 长期记忆；
8. 记忆隔离、纠错和过期；
9. LangChain 与 LlamaIndex；
10. LangChain4j 与 Python 重构选择；
11. LangChain 与 LangGraph；
12. Borough 已使用和未使用的 LangGraph 能力；
13. 框架版本治理；
14. Deep Research 是否适合本项目；
15. 未来何时增加 LangChain/LlamaIndex 或更复杂编排。

## 方案比较

### 方案 A：每篇文章对应一道题

大模型工程会达到 23 题，超过用户要求的 20 题上限；LangChain 只有 12 题，部分项目关键边界无法展开。不采用。

### 方案 B：完整阅读、按项目相关性重组（采用）

大模型工程筛成 18 题，LangChain 重组为 15 题。每题从文章知识出发，但答案以当前代码事实为核心。这与已完成的 Agent、RAG、工具调用文档保持一致。

### 方案 C：合并成一份综合文档

文件数量更少，但模型工程和框架选型的复习路径混在一起，后续维护、引用和面试检索不便。不采用。

## 每题固定结构

每道题必须包含以下六部分：

1. `**来源文章：**`
2. `**项目状态：**`
3. `### 详细解答`
4. `### 项目证据`
5. `### 设计取舍与缺口`
6. `### 可能追问`

文末分别增加能力现状矩阵和面试回答总纲。

## 必须保持真实的项目边界

### 大模型工程

- 当前云端 LLM 只有 DeepSeek OpenAI 兼容 Chat Completions Adapter，默认 `deepseek-v4-flash`。
- 当前没有自行部署模型，不使用 vLLM、SGLang、TGI、llama.cpp、量化或自建 KV Cache。
- 当前客户端没有发送 `temperature`、`top_p` 或 `top_k`，使用供应商默认采样参数。
- 结构化意图调用请求 JSON 输出，并在配置允许时关闭 thinking。
- 当前没有显式实现 Prompt Caching，也没有记录缓存命中 token；不能把供应商可能存在的缓存能力说成项目实现。
- 当前按真实响应 usage 记录输入、输出和总 token，并有单请求、每日预算与用途归集。
- Prompt 分为意图、回答、Reviewer、记忆和本地化等系统/用户消息；已有契约测试，但没有完整的 Prompt 版本注册、自动离线评测与灰度平台。
- 已有 Fake LLM 回归、确定性校验、Reviewer、用户反馈和部分真实模型验收；不能把它说成完整自动评测闭环。
- 长上下文采用按节点最小化上下文，而非全量历史；完整连续追问语义利用仍有限。

### LangChain

- 当前 Python 依赖直接使用 `langgraph>=0.2,<1`，没有安装或使用 `langchain`、LlamaIndex、CrewAI。
- 图使用显式 `AgentState`、Node 和 Edge，并直接 `compile()`，没有配置 Checkpointer。
- 当前一轮 `AgentState` 是临时状态；会话、消息和回答由业务 Repository 持久化，但完整历史不会自动注入每次模型调用。
- 长期记忆已按 `(merchant_id, category)` 从成功回答异步提取、压缩和召回；团队知识优先于商家记忆。
- 当前没有 LangChain Tool 注册或原生 Function Calling，查询由结构化意图与固定图路由到安全 Service。
- 旧 Java 项目只是只读行为参考；当前 Python + TypeScript 重构不使用 LangChain4j。
- 当前 LangGraph 已使用状态、条件分支和可见步骤，但尚未使用 Checkpoint、Interrupt、人工审批、持久化恢复或通用并行节点。
- Deep Research 不适合日常指标查询；只有开放、多来源、可拆分且报告价值覆盖成本的研究任务才值得引入。

## 证据来源

优先引用以下项目文件：

- `AGENTS.md`
- `backend/pyproject.toml`
- `backend/app/llm/client.py`
- `backend/app/llm/deepseek.py`
- `backend/app/llm/guard.py`
- `backend/app/core/config.py`
- `backend/app/agent/state.py`
- `backend/app/agent/graph.py`
- `backend/app/intent/prompts.py`
- `backend/app/prompts/answer.py`
- `backend/app/prompts/reviewer.py`
- `backend/app/prompts/memory.py`
- `backend/app/services/quality_loop.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/memory_agent.py`
- `backend/app/services/memory_service.py`
- `backend/app/services/safe_query.py`
- `backend/app/repositories/conversation.py`
- `backend/app/repositories/memory.py`
- `backend/app/repositories/llm_budget.py`
- 对应的 unit、integration 和 API tests
- `docs/PRD.md` 与 `docs/project-progress.md`

## 验收标准

### 大模型工程文档

- 恰好 18 道题，不超过 20。
- 六个固定栏目各出现 18 次。
- 小林文章链接去重后恰好 13 个。
- 不引用被排除的 10 篇文章。

### LangChain 文档

- 恰好 15 道题，不超过 20。
- 六个固定栏目各出现 15 次。
- 小林文章链接去重后恰好 12 个。
- 明确“只直接使用 LangGraph、未使用 LangChain”的真实状态。

### 共同验收

- 所有项目相对链接都存在。
- 不包含 TODO、TBD、示例链接、真实密钥或完整 Prompt 内容。
- 不调用真实 LLM，不产生模型费用。
- 不修改 `yshopping-merchant-ai 4/`。
- 不执行 Git commit 或发布操作。

