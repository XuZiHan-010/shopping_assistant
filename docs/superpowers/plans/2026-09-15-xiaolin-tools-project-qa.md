# 小林 Coding「LLM 工具调用」项目化问答 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阅读并筛选小林 Coding「LLM 工具调用」专题文章，产出一份只保留 Borough 商家 AI 助手强相关内容、包含 18 道详细面试问答的 Markdown 文档。

**Architecture:** 采用“文章知识 → 当前实现证据 → 设计判断 → 面试追问”的映射方式。最终问答不把结构化 JSON 意图误称为原生 Function Calling，不把内部 `LlmCostGuard` 误称为独立 LLM 网关，也不把开发期 Codex Skill 误称为产品运行时 Skill。所有项目事实均用仓库内相对链接支撑。

**Tech Stack:** Markdown、PowerShell、Python 静态校验脚本（只读验证）

## Global Constraints

- 面向用户与文档内容使用中文。
- 参考目录 `yshopping-merchant-ai 4/` 只读，本任务不修改它。
- 不调用真实 LLM，不产生 token 费用。
- 不执行 `git commit`、`git push`、`git tag` 或 PR 操作。
- 最终文档固定为 18 道题，不超过 20 道。
- 每题必须包含：来源文章、项目状态、详细解答、项目证据、设计取舍与缺口、可能追问。
- 最终引用 16 篇强相关文章；排除 Function Calling 模型训练和 WebRTC 语音传输两篇弱相关文章。

---

## Task 1: 固化文章来源与筛选结果

**Files:**

- Read: `docs/superpowers/specs/2026-09-15-xiaolin-tools-project-qa-design.md`
- Create: `interview/xiaolin-tools-project-qa.md`

- [x] 复核工具调用专题 18 篇文章均已访问。
- [x] 将 16 篇强相关文章映射到 18 道问题。
- [x] 明确排除 `/3_fc_training.html` 与 `/15_webrtc_vs_ws.html`，并在文档范围说明中解释原因。

## Task 2: 建立项目证据与真实能力边界

**Files:**

- Read: `backend/app/llm/client.py`
- Read: `backend/app/llm/deepseek.py`
- Read: `backend/app/llm/guard.py`
- Read: `backend/app/api/dependencies.py`
- Read: `backend/app/intent/models.py`
- Read: `backend/app/intent/service.py`
- Read: `backend/app/agent/graph.py`
- Read: `backend/app/services/safe_query.py`
- Read: `backend/app/api/routes/chat.py`
- Read: `backend/app/services/chat_service.py`

- [x] 确认当前没有原生 `tools` / `tool_choice` / `tool_calls` 协议。
- [x] 确认当前采用 JSON 输出、Pydantic 校验、固定图编排和后端安全查询。
- [x] 确认 MCP、A2A、产品运行时 Skill、WebSocket、WebRTC 均未接入。
- [x] 确认 `LlmCostGuard` 是应用内费用闸门，而非独立网关。
- [x] 准确记录 SSE 当前是心跳加任务结束后批量步骤，而非 token 或实时节点流。

## Task 3: 编写 18 道详细项目化问答

**Files:**

- Create: `interview/xiaolin-tools-project-qa.md`

- [x] 编写 Function Calling 原理、现状、结构化意图与校验相关 5 题。
- [x] 编写 MCP 定位、组件映射、与 Function Calling 选择相关 4 题。
- [x] 编写推理模型、Skill、A2A 与传输协议相关 6 题。
- [x] 编写 LLM 网关、工具路由、可靠性与人工兜底相关 3 题。
- [x] 在文末增加能力现状矩阵和面试回答总纲。

## Task 4: 静态验收

**Files:**

- Verify: `interview/xiaolin-tools-project-qa.md`

- [x] 校验题目数恰好为 18。
- [x] 校验六个固定字段各出现 18 次。
- [x] 校验强相关小林文章 URL 去重后为 16 个，且不包含两篇排除文章。
- [x] 校验所有本地 Markdown 链接目标均存在。
- [x] 搜索 TODO、占位符、密钥形态字符串和不准确的“已实现”表述。
- [x] 检查工作区只新增预期文档，且不提交 Git。
