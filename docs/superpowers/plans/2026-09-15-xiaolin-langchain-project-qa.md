# 小林 Coding「LangChain 框架」项目化问答 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出一份包含 15 道详细答案、把 LangChain 知识准确映射到 Borough 当前 LangGraph 实现的面试问答。

**Architecture:** 完整保留专题 12 篇来源，但把框架 API 问法改造成项目选型、状态、记忆、工具、安全和演进问题。当前实现与未来可选能力分别陈述。

**Tech Stack:** Markdown、PowerShell 静态校验

## Global Constraints

- 输出文件固定为 `interview/xiaolin-langchain-project-qa.md`。
- 恰好 15 道题，每题包含六个固定栏目。
- 使用专题全部 12 个去重后的小林文章链接。
- 明确项目直接使用 LangGraph，没有安装 LangChain、LlamaIndex 或 LangChain4j。
- 明确当前 `compile()` 没有 Checkpointer，完整会话历史不会自动注入模型。
- 不调用真实 LLM，不修改参考项目，不提交 Git。

---

### Task 1: 框架与记忆事实映射

**Files:**

- Read: `backend/pyproject.toml`
- Read: `backend/app/agent/state.py`
- Read: `backend/app/agent/graph.py`
- Read: `backend/app/services/chat_service.py`
- Read: `backend/app/services/memory_agent.py`
- Read: `backend/app/services/memory_service.py`
- Read: `backend/app/repositories/conversation.py`
- Read: `backend/app/repositories/memory.py`

- [x] 复核依赖、State/Node/Edge、条件分支和编译方式。
- [x] 复核会话持久化与短期语义记忆的区别。
- [x] 复核长期记忆提取、压缩、召回和商家隔离。

### Task 2: 编写 LangChain 框架问答

**Files:**

- Create: `interview/xiaolin-langchain-project-qa.md`

- [x] 编写框架选型、Chain/Runnable 和底层分层相关 3 题。
- [x] 编写 Agent 构建与 Tool 注册相关 2 题。
- [x] 编写短期、长期和记忆治理相关 3 题。
- [x] 编写 LlamaIndex、LangChain4j 与 Python 重构相关 2 题。
- [x] 编写 LangChain/LangGraph、版本、Deep Research 与演进相关 5 题。
- [x] 添加能力现状矩阵与面试回答总纲。

### Task 3: 静态验收

**Files:**

- Verify: `interview/xiaolin-langchain-project-qa.md`

- [x] 校验 15 道题及六个固定栏目。
- [x] 校验 12 个专题来源链接。
- [x] 校验全部项目相对链接存在。
- [x] 校验无占位符、密钥形态字符串和尾随空格。
