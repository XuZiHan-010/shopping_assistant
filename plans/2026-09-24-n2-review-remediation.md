# N2 审查整改计划与执行记录

> 用户于 2026-09-24 授权修复 N2 审查发现的七类问题。按 systematic-debugging 与 TDD 执行。不提交或发布 Git。

**2026-09-25 当前状态：N2 审核发现的问题及随后列出的三项剩余问题均已修复，并完成合并后全量 PostgreSQL 回归。** 2979 passed / 4 skipped / 0 failed；独占安全时序测试另跑 1 passed。跳过项为时序测试的常规套件排除，以及本机 Windows 无符号链接创建权限的 3 项。空库迁移到单一 head `20260923_0034`，`alembic check` 无新增操作。N2 审查整改验收通过；N2 产品整体验收仍需按阶段计划另行判定。

**2026-09-24 审查结论：** 七类问题及后续发现的缺陷已完成代码修改，独立复审（Astra 角色）已完成并出具逐项结论
（见 `plans/2026-09-22-astra-checklist.md` §五「N2」），复审中新发现并已修复三项问题
（4 个失败测试的查询过滤缺陷、`draft_apply.py` 并发缺陷、`IdempotentReplay` 死代码，均已按用户裁定处理，
详见 `docs/project-progress.md` 顶部条目）。最新真实 PostgreSQL 全量回归 **2861 passed / 1 skipped / 0 failed**；
独占库 `security_timing` **1 passed**；`ruff check .` 全绿；`mypy app` 232 个文件通过；
测试库 `alembic check` 无待生成迁移；两个前端 `codegen:check`、`lint`/`eslint`、`typecheck`/`tsc`、构建通过，
单元测试（商家端 670 passed、`shop/` 84 passed；会话竞态修改后定向 14 passed）。**审查整改验收通过，N2 产品整体验收尚未完成。**

**目标**：修复已复现的 F1–F7，保留现有契约和业务能力，补足能阻断回归的自动化证据。

**设计**：沿用现有费用守卫、可信会话、数据库事务和工具闸门。未知用量保留预留；断开用取消事件收束工具循环并保存完成部分；显式对话标识必须经过归属检查；审批先鉴权再校验证据；丢弃通过数据库锁串行裁决；安全评测只用确定性攻击脚本，并验证攻击确实经过模型/工具边界。

**边界**：当前工作区未提交实现是整改基线，直接保留并修改，不从 HEAD 重建或覆盖。只读 vendor/参考项目与冻结 Agent 不改。真实 LLM、生产数据和 Git 发布均不在授权范围。`shop/` 已另行交付；本计划仅覆盖 N2 审查整改。

## Task 1：费用与循环（F1/F2/F3）

- [x] 将未知 usage、SSE 外层取消、重生成 MAX_TOKENS 的反例转为正式失败测试。
- [x] 修改 `backend/app/llm/guard.py`：仅 usage_known 时 reconcile，记录原始 usage_known。
- [x] 修改 `backend/app/agent/loop/runner.py` 与 `backend/app/api/routes/v2/chat_stream.py`、两端 Chat 路由：取消事件传入回合；收束派生协程；已开始写操作完成后停止；完成部分和幂等结果在断开收尾落库；重生成截断明确降级。
- [x] 复跑单元测试与真实 PostgreSQL 断开/重试测试（2026-09-24，见 Task 5 执行记录）。

## Task 2：审批入口与并发（F4/F5）

- [x] 在草稿集成测试添加匿名/错误角色/跨店与缺坏证据组合、审批/丢弃屏障并发反例，并在真实 PostgreSQL 中运行。
- [x] 修改 `backend/app/api/routes/v2/merchant_drafts.py`：鉴权、归属优先于证据校验；幂等返回优先于令牌有效性；丢弃锁定并重新检查状态，返回契约 409。
- [x] 补跨进程 nonce 持久化和过期证据 HTTP 同形证据，复跑草稿、证据与生命周期测试（2026-09-24）。
- [x] **Astra 独立复审新发现并已修复**：`draft_apply.py::_lock()` 的 `SELECT ... FOR UPDATE` 未加
      `populate_existing=True`，若调用方在加锁前已用同一 `Session` 持有过该 `Draft`（路由层归属检查正是如此），
      解锁后仍返回身份映射里的旧属性，导致已丢弃的草稿可能被重新应用。已加该选项（沿用 `orders.py` /
      `payment.py` 已有模式），并新增回归测试 `test_lock_refreshes_stale_identity_map_entry`
      （已验证修复前失败、修复后通过）。

## Task 3：真实攻击路径的安全门禁（F6）

- [x] 在 `backend/tests/eval/` 建立明确失败于未执行攻击脚本的测试。
- [x] 为 `SELFAPPROVE` 与 `INJECTION` 用例配置 Fake 攻击回合，商品/知识入口先检索实际注入文本，再尝试被禁止的动作；保持真实端点与 PostgreSQL。
- [x] 明确断言模型/工具调用、围栏与拦截/审计，补关键闸门失效的反向测试；不通过仅断言 200 与无副作用获得假绿。
- [x] 复跑完整安全集（2026-09-24，七类零失败）。**`CURRENT_MILESTONE` 在本计划完成前已被改为 `"N2"`**
      （Astra 独立复审发现，改动来源未查明）；**用户裁定：保留不回退**，已补记录（见
      `plans/2026-09-21-n2-merchant-drafts-and-inventory.md` Task 9、`plans/2026-09-22-astra-checklist.md` E3）。
      Astra 同时指出 `SELFAPPROVE`/`INJECTION` 部分用例调用的是不存在的工具，证明力偏弱；
      2026-09-25 已补强为真实 `set_cart_item` / `draft_restock` 工具路径，`SELFAPPROVE` 先实际起草再尝试越权应用，
      并核对闸门、审计与无副作用，独立 PostgreSQL 安全集 58 passed。

## Task 4：对话归属（F7）

- [x] 将静默新建的旧断言改为跨主体/跨端/不存在/删除对象统一 403，并断言零模型调用及审计。
- [x] 两端 Chat 在开流、幂等回放和模型调用前复用会话目录的归属守卫；只有空 conversation_id 新建。
- [x] 复跑双端 Chat、会话目录与回答持久化测试（2026-09-24，含本轮新修的 4 个失败用例，见 Task 5）。

## Task 5：复审与收口

- [x] **独立复审已完成**（2026-09-24，子代理扮演 Astra 角色，按 `plans/2026-09-22-astra-checklist.md` §九模板
      逐项出具结论；首次因会话额度限流中断于 N2-1，额度重置后完整重跑）。
      结论：N1 前置项 B1–B4、D1–D6、E1、E2 通过；E3 有条件通过（用户裁定后通过，见上）；
      N2-1、N2-5、N2-6、N2-8 通过；N2-2、N2-3、N2-4、N2-7、入口-N2 有条件通过（阻塞项均已修复，见各 Task）。
      逐项结论见 `plans/2026-09-22-astra-checklist.md` §五「N2」。
- [x] **独立测试库回归已完成**（一次性库，`REQUIRE_INTEGRATION_DB=1 uv run pytest -m "not security_timing"`）：
      **2861 passed / 0 failed / 1 deselected**（713 秒）；`uv run alembic upgrade head` 在空库上一次通过；
      `alembic heads` 单一 head `20260923_0034`；`ruff check .` 全绿；`uv run mypy app` 232 个文件通过；
      商家端 `npm run codegen:check`、`lint`、`typecheck`、`test`（670 passed）通过；`shop/` 的
      `codegen:check`、`tokens:check`、`eslint .`、`tsc --noEmit`、`test`（84 passed）通过。
- [x] 更新本文件（本次）、`docs/project-progress.md`（已记录独立复审结论与三项修复）、
      `plans/2026-09-22-astra-checklist.md`（N2-1 至 N2-8 与入口-N2 勾选状态已同步）。

## 执行证据

整改前审查：N2 定向 651 passed，v1/迁移相关 577 passed，Vue 定向 71 passed；额外八条反例分别复现七类问题。测试全绿并不等于 checklist 已通过。

整改中间态（数据库故障前）：费用、循环、工具、v2 服务相关单元测试 574 passed；随后新增断开后的真实循环读/写收束测试，SSE 定向 4 passed；攻击脚本及移除围栏反向测试 3 passed；安全集结构检查 6 passed。相关 Ruff、应用 mypy（23 文件）、安全评测 mypy（2 文件）、前端 codegen:check 通过。以上均使用 Fake LLM，无真实模型调用。

**2026-09-24 最终验收**（数据库故障已解决，独立复审完成）：见 Task 5 与上方「当前状态」。
全程 Fake / 脚本化模型，零真实 LLM 调用，零费用；未执行任何 Git 提交或发布操作。
`shop/`（顾客端 Next.js）已由 `n2-shop-nextjs-app` 计划交付（见 `docs/project-progress.md`），
不再是本轮的阻塞项。**本整改计划（Task 1–5）全部完成，N2 审查整改验收通过。**
本轮追加修复了未验证模型残文、每日预算耗尽提示、非法上游 `tool_call_id`、审批选择校验、跨店会话竞态、
写工具提交后 Chat 失败及回执提交失败的重试安全性、`FAILED_FINAL` 幂等竞争分支，并用故障注入测试覆盖。
**2026-09-25 补齐原剩余项**：C9 商品机器译文/源文回退标注、v2 回答反馈界面及历史状态、N2-7
真实工具攻击用例均已实现，分别在独立 PostgreSQL 库定向通过 130、118、58 项；商家端 675、顾客端
89 项单元测试通过。合并后后端无数据库单元 2044 passed、3 个 Windows 符号链接权限项跳过；
Docker 恢复后，在新建独立 PostgreSQL 测试库全量复跑 **2979 passed / 4 skipped / 0 failed**（845.22 秒），
时序哨兵独占运行 **1 passed**；空库迁移至单一 head `20260923_0034`，`alembic check` 无新增操作。
4 项跳过中 1 项是常规套件排除的时序哨兵（已另跑），3 项是本机 Windows 符号链接权限限制。
公开商品 GET 只消费现有缓存，不触发真实付费模型；
缺少缓存时明确显示源文。具体限制见 `docs/project-progress.md` 顶部。
