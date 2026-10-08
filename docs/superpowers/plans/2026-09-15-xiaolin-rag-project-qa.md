# 小林 RAG 专题项目问答：执行计划

> **给 Codex：** 执行本计划时须逐项完成；任务为文档研究，不修改业务代码，不提交 Git。

**目标：** 新增一份中文 Markdown 面试问答，将小林 Coding RAG 专题中与 Borough 商家 AI 助手直接相关的内容，映射为不超过 20 道、可由项目实现证据支撑的题目与详细答案。

**架构：** 先完整浏览 RAG 专题目录的 21 篇文章并筛选强相关主题；再核验 Borough 当前知识检索、知识库管理、商家记忆、国际化和 Agent 编排实现；最后按 Agent 专题已经采用的固定问答结构落盘，并用静态检查验证数量、结构、链接和敏感信息。

**技术栈：** Markdown、PowerShell、`rg`、网页资料、小林 Coding RAG 专题、Borough Python/FastAPI 源码与测试。

**约束：** 全文中文；15–20 题，目标 18 题；每题必须包含来源文章、项目状态、详细解答、项目证据、设计取舍与缺口、可能追问；不能把未实现的向量检索、Embedding、重排、GraphRAG、通用 Query Rewrite 或 RAG 自动评测写成已实现；不调用真实 DeepSeek 或其他 LLM；不修改参考项目；不 commit。

---

### 任务 1：浏览并筛选小林 RAG 专题

**状态：** 已完成

**文件：**
- 参考：`https://xiaolinnote.com/ai/rag/rag_info.html`
- 产出：`interview/xiaolin-rag-project-qa.md`

**步骤：**

1. 打开 RAG 专题目录，逐篇阅读其列出的 21 篇文章的摘要和关键章节。
2. 仅保留能映射到项目知识库、检索、记忆、上下文、幻觉控制、更新、评测、安全或演进路线的主题。
3. 合并重叠主题，形成 18 道以内、互不重复的候选题，并为每题记录对应文章链接。

### 任务 2：核验项目证据与真实边界

**状态：** 已完成

**文件：**
- 检索：`backend/app/knowledge/retrieval.py`
- 检索：`backend/app/knowledge/domains.py`
- 检索：`backend/app/knowledge/path_policy.py`
- 检索：`backend/app/services/knowledge_admin_service.py`
- 检索：`backend/app/services/memory_service.py`
- 检索：`backend/app/agent/graph.py`
- 检索：`backend/app/agent/prompts.py`
- 检索：`backend/tests/unit/knowledge/`

**步骤：**

1. 确认当前检索策略、团队知识与商家记忆的优先级、跨语言回退和知识文档更新机制。
2. 明确记录尚未实现的能力：Embedding、向量数据库、混合召回、重排、GraphRAG、完整 Query Rewrite、文档级引用和自动化 RAG 评测。
3. 对每题收集至少一个可定位的本地源码、测试或项目文档证据，避免用设计意图替代真实实现。

### 任务 3：编写 RAG 面试问答文档

**状态：** 已完成

**文件：**
- 创建：`interview/xiaolin-rag-project-qa.md`
- 参考：`interview/xiaolin-agent-project-qa.md`

**步骤：**

1. 写明目的、阅读范围、状态口径与文章筛选原则。
2. 写 15–20 道题（目标 18），每题采用统一六段结构：来源文章、项目状态、详细解答、项目证据、设计取舍与缺口、可能追问。
3. 对项目未实现能力，以“未实现 / 建议演进”的面试答案回答：解释现阶段不做的原因、触发条件和最小落地路径。
4. 在末尾给出能力现状表和面试回答原则，便于快速复习。

### 任务 4：静态验证与交付

**状态：** 已完成

**文件：**
- 验证：`interview/xiaolin-rag-project-qa.md`

**步骤：**

1. 用 `rg` 统计题目数和六段必备标题数，确认题目数在 15–20 之间。
2. 提取本地 Markdown 链接，确认全部目标文件存在；扫描 TODO、占位词和疑似密钥。
3. 查看工作区状态，确认只增加本次文档与对应设计、计划文件，且没有 Git 提交。
4. 向用户交付新文档路径、题目数量和验证结果，并说明未调用真实 LLM。
