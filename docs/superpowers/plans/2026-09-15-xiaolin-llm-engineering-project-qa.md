# 小林 Coding「大模型工程」项目化问答 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出一份包含 18 道详细答案、只保留 Borough 强相关知识的大模型工程面试问答。

**Architecture:** 将 23 篇文章完整阅读后的 13 篇强相关内容映射为“原理、当前实现、证据、取舍、追问”。文档严格区分云端模型能力、供应商可能提供的能力和 Borough 自己实现的能力。

**Tech Stack:** Markdown、PowerShell 静态校验

## Global Constraints

- 输出文件固定为 `interview/xiaolin-llm-engineering-project-qa.md`。
- 恰好 18 道题，每题包含六个固定栏目。
- 使用 13 个去重后的小林文章链接，排除设计规格列出的 10 篇弱相关文章。
- 不把供应商缓存、自托管推理、量化或采样参数说成项目已实现。
- 不调用真实 LLM，不修改参考项目，不提交 Git。

---

### Task 1: 来源与项目事实映射

**Files:**

- Read: `docs/superpowers/specs/2026-09-15-xiaolin-remaining-sections-project-qa-design.md`
- Read: `backend/app/llm/client.py`
- Read: `backend/app/llm/deepseek.py`
- Read: `backend/app/llm/guard.py`
- Read: `backend/app/core/config.py`
- Read: `backend/app/prompts/`
- Read: `docs/PRD.md`
- Read: `docs/project-progress.md`

- [x] 复核 13 篇来源与 18 道题的映射。
- [x] 复核采样参数、缓存、模型选择、token usage、Prompt 和评测的当前状态。
- [x] 记录所有可引用的本地证据路径。

### Task 2: 编写大模型工程问答

**Files:**

- Create: `interview/xiaolin-llm-engineering-project-qa.md`

- [x] 编写 LLM、Tokenizer、解码与采样相关 4 题。
- [x] 编写 KV Cache、Prompt Caching 与成本相关 2 题。
- [x] 编写 Prompt、CoT 与结构化 thinking 相关 4 题。
- [x] 编写幻觉与证据约束相关 2 题。
- [x] 编写 MoE、部署、评测、选型和长上下文相关 6 题。
- [x] 添加能力现状矩阵与面试回答总纲。

### Task 3: 静态验收

**Files:**

- Verify: `interview/xiaolin-llm-engineering-project-qa.md`

- [x] 校验 18 道题及六个固定栏目。
- [x] 校验 13 个强相关来源链接且排除列表未混入。
- [x] 校验全部项目相对链接存在。
- [x] 校验无占位符、密钥形态字符串和尾随空格。
