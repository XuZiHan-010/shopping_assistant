# OpenAPI 机器产物与项目进度快照实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供前端可直接消费的 OpenAPI JSON，并给跨日 agent 提供当前项目快照。

**Architecture:** OpenAPI 从一次 FastAPI schema 生成中渲染 Markdown 与 JSON 两份产物，并由契约测试防漂移。项目进度只维护 `docs/project-progress.md` 一份当前快照，`AGENTS.md` 负责把它纳入开工和维护流程。

**Tech Stack:** Python 3.12、FastAPI、pytest、Markdown。

## Global Constraints

- 面向用户的内容使用中文。
- 不改变 FastAPI 路由、Pydantic Schema 或公开 API 契约。
- 不调用真实 LLM、OCR 或外部网络服务。
- 不执行 Git commit、push、tag 或 PR 操作；当前目录不是 Git 仓库。

---

### Task 1: 验证并刷新 OpenAPI 双产物

**Files:**
- Verify: `scripts/export_openapi.py`
- Generate: `docs/api.json`
- Generate: `docs/api.md`
- Test: `backend/tests/api/test_openapi_chat_contract.py`

**Interfaces:**
- Consumes: `create_app(export_settings()).openapi()`。
- Produces: 可直接由 `openapi-typescript` 读取的 UTF-8 JSON，以及同源人读 Markdown。

- [x] **Step 1: 运行机器产物契约测试**

Run: `uv run pytest tests/api/test_openapi_chat_contract.py -q`

Expected: 测试验证 `api.json` 可解析且两个产物均与当前 FastAPI schema 一致。

- [x] **Step 2: 重新生成两份 OpenAPI 产物**

Run: `uv run python ../scripts/export_openapi.py`

- [x] **Step 3: 再次运行契约测试**

Run: `uv run pytest tests/api/test_openapi_chat_contract.py -q`

Expected: PASS。

### Task 2: 建立当前项目进度快照

**Files:**
- Create: `docs/project-progress.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: 已完成阶段、最近验证结果、后续开发阶段及已知风险。
- Produces: 新 agent 开工前可读的单份、带日期当前快照。

- [x] **Step 1: 创建当前快照**

写入最后更新日期、B0–B2 状态、OpenAPI JSON 可用性、最近验证、下一步、风险和关键入口；只保留当前事实，不追加历史日志。

- [x] **Step 2: 更新 AGENTS.md 索引与维护规则**

把 `docs/project-progress.md` 写入当前已有文档、目标目录、开工阅读顺序与维护规则；规定每次完成一段可验证工作后更新其日期和当前状态。

- [x] **Step 3: 人工核对交接可读性**

从 `AGENTS.md` 的开工阅读顺序定位并读取快照，确认能在不依赖会话上下文时识别下一步工作。
