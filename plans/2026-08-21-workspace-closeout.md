# 工作区收尾实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。步骤用 `- [ ]` 跟踪，完成一个勾一个。

**目标：** 把当前未提交的工作区拆成自洽提交，验证并落历史的改动与明确移交的改动互不混杂；结束时允许保留已列明的移交文件、计划文档和本轮范围外文件，不虚称整个工作树干净。

**架构：** 不新增能力。只做一件事——把工作区里**已经带测试且自洽**的那部分落进历史，把**尚无消费者、尚无测试**的那部分原样留给它的功能计划。

**技术栈：** Python 3.12 / SQLAlchemy 2 Async / pytest。

**Spec:** `docs/project-progress.md`（2026-08-21 的 R9 对照结论）+ `docs/yshopping-parity-audit.md`

**依赖：** 无。这是所有后续计划的前置。

---

## 1. 全局约束

- **R1** 中文；**R2** 提交需用户明确许可（每次会话重新确认）；**R3** 测试必须 mock LLM，禁止真实模型调用；**R5** 商家隔离；**R8** 参考目录只读。
- 门禁：

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

- 跑全量集成测试前确认没有其他 agent 在同一 PostgreSQL 测试容器上写数据。

---

## 2. 工作区现状盘点与归属

2026-08-21 复核时，`git status --short` 是 6 个已改文件 + 9 个未跟踪文件。下表逐个确定本计划范围内代码与文档的归属；未跟踪的 2026-08-18 / 19 旧计划、本轮三份计划与日报 spec 不纳入本计划提交，也不删除：

| 文件 | 内容 | 归属 | 理由 |
| --- | --- | --- | --- |
| `backend/app/repositories/answer.py` | 新增 `recent_answers_for_category` | **本计划 Task 1** | 有两份断言输入内容的测试覆盖 |
| `backend/app/services/memory_agent.py` | `history=[]` → 真实历史 | **本计划 Task 1** | 同上 |
| `backend/tests/integration/repositories/test_answer_history.py` | 3 条测试 | **本计划 Task 1** | 覆盖上面两处 |
| `backend/tests/integration/services/test_memory_agent_history.py` | 1 条测试 | **本计划 Task 1** | 同上 |
| `docs/project-progress.md` | 2026-08-21 R9 对照结论 | **本计划 Task 2** | 独立的文档事实，与代码改动无耦合 |
| `backend/app/repositories/audit.py` | 新增 `record_admin_action` | **移交** `2026-08-21-memory-compress-and-history-suggestions.md` | **零调用者、零测试**——当前是死代码，必须跟第一个消费者（压缩端点）一起提交 |
| `backend/app/schemas/knowledge.py` | `MemoryCompressRequest/Response` + 一处重复 `Field` 导入 | **移交**（同上） | 属于压缩功能的对外契约 |
| `backend/tests/api/test_knowledge_memory_compress.py` | 4 条测试 | **移交**（同上） | 该功能的测试 |
| `scripts/export_chat_fixtures.py` | **无内容改动**，仅 LF/CRLF | **不提交** | `git diff --stat` 不含此文件，只是换行符 |

> **不要**把移交的三项塞进本计划的提交。它们没有消费者、没有测试，提交进去就是把死代码写进历史，而且会让后续那份计划的提交范围变得没法解释。

> `scripts/export_chat_fixtures.py` 当前经 `git diff --ignore-space-at-eol --exit-code -- scripts/export_chat_fixtures.py` 验证没有内容差异。它仍可能因工作区换行符显示为 `M`；本计划没有获得恢复用户文件的授权，因此只报告、不执行 `git checkout --` 或其他覆盖命令。

---

## 3. Task 1：记忆沉淀带上同商家同分类的历史问答

参考实现 `MemoryConsolidationService` 取 `recentAnswers(merchantId, 80)` 后按分类过滤再压缩；我方 `MemoryService.consolidate()` 的 `history` 形参此前从未被传值，硬编码 `history=[]`。表面功能在跑、899 条测试全绿，但记忆永远累积不出商家画像，每次覆盖写入的只是最后一轮摘要。

**代码已在工作区改好，测试也已写好。本任务只做验证与提交，不要重写这两个文件。**

**Files:**

- Modify（已完成，仅验证）：`backend/app/services/memory_agent.py`、`backend/app/repositories/answer.py`
- Test（已写好）：`backend/tests/integration/repositories/test_answer_history.py`（3 条）、`backend/tests/integration/services/test_memory_agent_history.py`（1 条）

- [ ] **步骤 1：确认工作区就是计划描述的状态**

```powershell
cd "d:/vscode html/merchant_assistant"
git diff --stat backend/app/services/memory_agent.py backend/app/repositories/answer.py
```

预期：两个文件都有改动，`answer.py` 约 +43 行、`memory_agent.py` 约 +13 行。若对不上，说明工作区被动过，停下来报告，**不要**猜测缺了什么并自行补写。

- [ ] **步骤 2：跑这四条测试**

```powershell
cd backend
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/repositories/test_answer_history.py tests/integration/services/test_memory_agent_history.py -v
```

预期：4 passed。

- [ ] **步骤 3：变异验证——证明测试真的测得到**

这一步不能跳。`history=[]` 这个缺陷正是在 899 passed 的前提下存活的；一条不断言输入内容的测试，绿了也不能证明任何事。

1. 临时把 `backend/app/services/memory_agent.py` 里的 `history=history` 改成 `history=[]`；
2. 重跑步骤 2 的命令；
3. **预期 `test_consolidation_receives_same_merchant_same_category_history` 变红**（断言 `assert history, "沉淀输入的 history 不能为空"` 失败）；
4. 改回 `history=history`，重跑确认恢复 4 passed。

若第 3 步没有变红，说明测试没有真正断言输入，**报告 BLOCKED**，不要提交。

- [ ] **步骤 4：确认工作区没有残留变异**

```powershell
cd "d:/vscode html/merchant_assistant"
git diff backend/app/services/memory_agent.py
```

逐行确认 `history=history`（不是 `history=[]`）。步骤 3 的手工改动在脏工作区里最容易忘记恢复。

- [ ] **步骤 5：跑全量门禁**（见 §1）

- [ ] **步骤 6：提交（需许可，R2）**

```bash
git add backend/app/services/memory_agent.py \
  backend/app/repositories/answer.py \
  backend/tests/integration/repositories/test_answer_history.py \
  backend/tests/integration/services/test_memory_agent_history.py
git commit -m "fix: 记忆沉淀带上同商家同分类的历史问答"
```

**只 add 这四个文件。** 确认 `git status` 里 `audit.py`、`schemas/knowledge.py`、`test_knowledge_memory_compress.py` 仍是未提交状态——它们归下一份计划。

---

## 4. Task 2：提交 2026-08-21 的 R9 对照结论

`docs/project-progress.md` 的工作区版本记录了 2026-08-21 逐条对照参考项目的结论：`history=[]` 是静默退化、手动压缩端点缺失、知识库版本历史其实已 1:1 还原、`/api/memories` 属我方超纲。这是跨日工作的外部记忆入口，与代码改动无耦合，单独提交。

**Files:**

- Modify（已完成）：`docs/project-progress.md`

- [ ] **步骤 1：按 Task 1 的实际结果订正「下一步」**

工作区版本的「下一步」第 1 条是「修 `memory_agent.py:140` 的 `history=[]`」。Task 1 完成后它已不是待办，改写为已完成，并把下一步指向本轮拆出的三份计划：

- `plans/2026-08-21-memory-compress-and-history-suggestions.md`
- `docs/specs/2026-08-21-daily-report-contract.md`
- `plans/2026-08-21-gap-roadmap.md`

- [ ] **步骤 2：补记 `/api/memories` 的裁定结果**

2026-08-21 用户裁定：按 R9 从文档删除，代码零改动。在「下一步」里把「裁定 `/api/memories` 三条的去留」改成已裁定，并指向 `plans/2026-08-21-gap-roadmap.md` 的文档同步任务。

- [ ] **步骤 3：更新日期与「最近验证」**

「最近验证」一节要如实写明：Task 1 的四条测试通过、变异验证做过；**不要**把 2026-08-20 的 899 passed 写成本轮结果。

- [ ] **步骤 4：提交（需许可）**

```bash
git add docs/project-progress.md
git commit -m "docs: 记录 2026-08-21 的 R9 逐条对照结论与本轮计划拆分"
```

---

## 5. 完成判据

- [ ] 本计划两个获准提交完成后，功能代码只剩明确移交给下一计划的 `backend/app/repositories/audit.py`、`backend/app/schemas/knowledge.py`、`backend/tests/api/test_knowledge_memory_compress.py`；
- [ ] `docs/specs/2026-08-21-daily-report-contract.md`、本轮 3 份计划，以及 2026-08-18 / 19 的范围外未跟踪计划保持原状；这些文件存在时不得宣称“整个工作树干净”；
- [ ] 对 `scripts/export_chat_fixtures.py` 运行 `git diff --ignore-space-at-eol --exit-code -- scripts/export_chat_fixtures.py` 返回 0；即使 `git status` 仍因换行符显示 `M`，也只在交接中说明。若用户另行要求清洁工作树，先取得明确许可再恢复该文件；
- [ ] 全量门禁绿；
- [ ] 变异验证已执行且工作区无残留。
