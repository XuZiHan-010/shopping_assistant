# 小林 Agent 专题 × Borough 项目问答 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阅读小林 AI Agent 专题中与 Borough 强相关的文章，生成一份不超过 20 题、每题含详细答案和双重证据的中文面试问答文档。

**Architecture:** 采用“文章来源 → 通用知识点 → Borough 实现证据 → 项目化问答”的单向研究链路。`interview/xiaolin-agent-project-qa.md` 是唯一交付物，网页来源支撑通用原理，本地源码、测试和项目文档支撑项目事实。

**Tech Stack:** Markdown、公开网页、小林面试笔记、Borough Python/FastAPI/LangGraph 源码与 pytest 测试。

## Global Constraints

- 本轮只处理 Agent 专题，最终保留 15～20 题且绝不超过 20 题。
- 只保留可映射到 Borough 的文章；允许把框架问题转换为 Borough 等价设计问题。
- 每题必须包含来源文章、问题、详细解答、项目状态、代码证据、设计取舍与缺口、可能追问。
- 明确区分“已实现 / 部分实现 / 未实现”，不得用规划冒充实现。
- 不大段转载原文，不泄露密钥、完整 Prompt 或生产敏感数据。
- 不调用真实 DeepSeek，不产生项目 LLM 费用。
- 按用户要求不执行 Git commit。

---

### Task 1: 建立 Agent 文章候选清单

**Files:**
- Read: `https://xiaolinnote.com/ai/`
- Target: `interview/xiaolin-agent-project-qa.md`

**Interfaces:**
- Consumes: Agent 专题 24 篇文章目录。
- Produces: 15～20 个与 Borough 强相关的候选主题及其原始 URL。

- [x] **Step 1: 打开 Agent 专题首页和每篇候选文章**

逐篇读取文章正文；至少覆盖 Agent/Workflow、范式选型、任务拆分、记忆、规划、Reflection、上下文、多轮状态、评测、死循环、Trace、任务幻觉和数据库安全。

- [x] **Step 2: 按强相关性筛选**

只保留能够映射到 Borough 已有实现、明确缺口或真实架构取舍的文章；合并内容高度重叠的文章，记录每道候选题的主要来源 URL。

- [x] **Step 3: 验证候选题数量**

Run: `rg -n '^## [0-9]+\.' interview/xiaolin-agent-project-qa.md`

Expected: 最终写作完成时匹配数量为 15～20；Task 1 阶段先确保候选主题不超过 20。

### Task 2: 建立 Borough 项目证据映射

**Files:**
- Read: `backend/app/agent/graph.py`
- Read: `backend/app/agent/state.py`
- Read: `backend/app/agent/prefilter.py`
- Read: `backend/app/intent/`
- Read: `backend/app/services/quality_loop.py`
- Read: `backend/app/services/memory_service.py`
- Read: `backend/app/services/memory_agent.py`
- Read: `backend/app/repositories/conversation.py`
- Read: `backend/app/repositories/llm_budget.py`
- Read: `backend/app/services/safe_query.py`
- Read: `backend/app/repositories/analytics.py`
- Read: `backend/tests/`
- Read: `docs/project-progress.md`
- Read: `docs/yshopping-parity-audit.md`

**Interfaces:**
- Consumes: Task 1 的候选知识点。
- Produces: 每个候选问题对应的源码、测试、现状和缺口证据。

- [x] **Step 1: 为每个问题定位主实现入口**

每题至少定位一个实际源码文件；如果项目未实现该能力，定位最接近的现有边界和明确记录缺口的文档。

- [x] **Step 2: 为关键行为定位测试证据**

优先引用锁定外部行为的单元、集成或 API 测试，不使用只描述未来计划的文件证明“已实现”。

- [x] **Step 3: 校正实现状态**

通过源码调用点确认状态；例如 QualityLoop 的 `PASSED/DEGRADED`、LlmCostGuard 的原子预算、Conversation Repository 的幂等恢复、MemoryService 的商家隔离均以运行代码为准。

### Task 3: 编写项目化详细问答

**Files:**
- Create: `interview/xiaolin-agent-project-qa.md`

**Interfaces:**
- Consumes: Task 1 的网页知识和 Task 2 的项目证据。
- Produces: 15～20 道完整中文问答。

- [x] **Step 1: 写文档导言和阅读说明**

说明内容是针对 Borough 的面试准备，不是原文转载；说明“项目状态”标签和网页/本地证据的不同职责。

- [x] **Step 2: 按统一模板写每道题**

每题使用以下固定结构：

```markdown
## N. 针对 Borough 的问题

**来源文章：** [文章标题](原始 URL)

**项目状态：** 已实现 / 部分实现 / 未实现

### 详细解答

先给面试现场可直接口述的结论，再解释原理、Borough 数据流、失败边界和取舍。

### 项目证据

- [源码或测试](相对路径)

### 设计取舍与缺口

说明现状为何合理，以及达到什么条件才需要演进。

### 可能追问

- 追问：……
  - 答题要点：……
```

- [x] **Step 3: 合并重复主题**

Agent/Workflow/设计范式不得拆成多个只有定义差异的弱问题；短期/长期记忆可以引用多篇文章形成一道完整项目题。

### Task 4: 完整性与事实核验

**Files:**
- Verify: `interview/xiaolin-agent-project-qa.md`

**Interfaces:**
- Consumes: Task 3 的完整文档。
- Produces: 可交付的最终 Markdown。

- [x] **Step 1: 检查题数和章节结构**

Run: `rg -c '^## [0-9]+\.' interview/xiaolin-agent-project-qa.md`

Expected: 输出一个 15～20 的整数。

- [x] **Step 2: 检查每题必备字段**

Run: `rg -c '^\*\*来源文章：\*\*|^\*\*项目状态：\*\*|^### 详细解答|^### 项目证据|^### 设计取舍与缺口|^### 可能追问' interview/xiaolin-agent-project-qa.md`

Expected: 六类字段的总匹配数等于题目数乘以 6。

- [x] **Step 3: 检查占位符和敏感内容**

Run: `rg -n 'T[B]D|T[O]DO|待[补]|你的DeepSeekKey|sk-[A-Za-z0-9]' interview/xiaolin-agent-project-qa.md`

Expected: 无输出。

- [x] **Step 4: 检查本地链接与网页链接**

逐一确认相对路径存在；重新打开所有小林文章 URL，确认标题和正文与引用知识点一致。

- [x] **Step 5: 最终自审**

确认没有把规划写成已实现，没有把 Reviewer 等同于人工审核，没有把 DeepSeek 服务端 Context Cache 写成项目自建 KV Cache，并确认所有答案可以脱离原文独立理解。
