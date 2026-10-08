# Astra 审查清单：N1–N5 高风险审查点

> 建立：2026-09-22
> 性质：**审查清单，不是实施计划**。不新增需求、不改步骤；各审查点的依据以对应实施计划与 PRD 为准。
> 与实施计划冲突时，按 `AGENTS.md` §五 的权威关系处理，不在本文件里就地改口径。

## 一、为什么要有这份清单

Astra 是当前可用的最强模型，但额度有限。它不负责写大部分代码，只放在下面这类地方：

**测试全绿也可能是错的**——越权静默放行、回填漏行、并发竞态、假绿门禁、协议形状写错但 mock 也按错的写。
这些问题实现者自己很难发现，需要一个不同的强模型交叉审查。

工作量大但套路固定的任务（契约、前端页面、文档收口）不进本清单，由实现模型自检即可。

## 二、使用规则

1. **审查时机**：实现者完成一个 Task 且该 Task 的验证全绿后、勾选复选框前，交给 Astra 审查。
   标 **【必审】** 的项未通过审查不得勾选；标 **【抽审】** 的项可在里程碑验收前集中审一次。
2. **审查者 ≠ 实现者**：若某项由 Astra 自己实现，改由 Opus 或 Sol 审查，并在结论里注明。
3. **Astra 只读审查**：输出结论与问题清单，不直接改代码；修复由原实现者完成后再复审。
   用户另行要求 Astra 修复的除外。
4. **边界不变**：审查同样受 R2、R3 约束——不执行 Git 发布操作；不运行任何真实 LLM 调用
   （B Task 6、E Task 7 等费用任务只审代码与计划，不代为执行）；只读目录不碰。
5. **要证据，不要描述**：每项都列了「必须看到的证据」。实现者只说"已处理"不算，Astra 要看到对应测试或代码。
6. **结论记录**：每次审查按 §九 模板输出，结论写进该 Task 的执行记录或 `docs/project-progress.md` 的验证结果，
   本文件只更新 §三 的勾选状态。

## 三、模型分工与审查进度

| 模块 / 计划 | 实现模型 | Astra 审查项 | 状态 |
| --- | --- | --- | --- |
| N1-A 契约 | 已完成 | 不审（已有 93/93 变异检验） | — |
| N1-B LLM 客户端 | Sonnet；前轮 Codex 整改 | B1–B4 | ✅ 2026-09-23 Astra 完整审核通过 4/4；本轮 Mock 与 v1 回归通过 |
| N1-C 数据迁移与种子 | Sol | C1–C5 | ✅ 2026-09-22 复审通过 |
| N1-D 会话身份 | Opus；前轮 Codex 整改 | D1–D6 | ✅ 2026-09-23 Astra 完整审核通过 6/6；真实 PostgreSQL 并发、隔离与时序哨兵通过 |
| N1-E 评测骨架 | Sonnet；Codex 整改 | E1–E3 | ✅ 2026-09-23 E1 整改已获 Astra 独立复审通过；E2/E3 沿用通过。评测集 99 passed；N1 最终回归另有阻塞，不能据此宣称整体验收完成；Task 7 步骤 3 属 N2 对照 |
| N2 | A、C：Opus；B：Sol；D、E：Sonnet；F：Terra（Codex）（2026-09-22，见 `plans/2026-09-22-n2-assignment-and-review.md`） | N2-1 – N2-8 | ✅ 2026-09-24 Astra 独立复审 8/8 通过（3 项发现问题已修复复跑，详见 §五） |
| N3 | 阶段 A、C：Opus；阶段 B：Sol | N3-1 – N3-5 | ✅ 2026-09-28 全部通过：N3-1 于 2026-09-25 通过；N3-2 至 N3-5 经 2026-09-26 Codex 独立审查（F1–F4）与 2026-09-28 Opus 整改后复审通过（N3-5 为机制层，真实模型质量待 R3 人工验收） |
| N4 | 实际：Opus 单会话实现；审查由独立子代理完成（见 `plans/2026-09-27-n4-assignment-and-review.md`「2026-10-02 审查状态」） | N4-1 – N4-4 | ✅ 2026-10-02：N4-1 通过；N4-2 有条件→复核通过；N4-3 锚点部分通过、③评测口径须冻结后真实重跑（待 R3）；N4-4 有条件通过，F1/F3/F4/F6/F9 当日整改并变异验证 |
| N5 | 2026-10-02 用户确认：Opus 单会话实现；各批次由独立子代理审查（见 `plans/2026-09-27-n5-assignment-and-review.md` 文首） | 入口-N5、N5-1 – N5-5 | 🔶 2026-10-03：入口-N5 有条件通过（E1–E4 文档漂移已当日修正）；**N5-1 通过**；**N5-2 有条件通过 → F1–F5 整改后同一独立子代理复核通过**（F6 延后为建议）；N5-3–N5-5 未审 |

另有两项**入口审查**（§八）：每个里程碑开工前做一次。

2026-09-23 Astra 复审：N1 **18/18 审核项已通过**（含此前 C1–C5）。2026-10-04 独立本地数据库全量
**4590 passed / 3 Windows 符号链接权限 skipped / 0 failed**，同时强制集成与时序；安全子进程及评测执行防护定向 31 passed。
N1–N4 的真实质量评测和盲审仍未完成，N4-3 不勾选。
历史 N1＋v1 回归 **2195 passed / 6 failed / 0 skipped**（N2 新迁移降级失败、前端另有超时）不再作为最新状态。
逐项结论、复现、N2 费用交接问题及未覆盖项见
[`N1 审查整改记录`](2026-09-22-n1-review-remediation.md)「E1 整改复审与最终验收停点」。
最新证据见 [`N1–N4 验收结果`](../docs/history/eval/n1-n4-acceptance-results-2026-10-03.md)；
末次评测防护补丁的再次独立复核因代理额度限制未执行，不冒充独立通过。
按 §二规则，当前审核状态以本节为准；下方条目保留审查点原文，不以旧复选框推翻本节结论。

---

## 四、N1

### 模块 B · LLM 客户端（`plans/2026-09-21-n1-llm-client-and-adapters.md`，实现：Sonnet）

- [ ] **B1【必审】Task 2 / Task 3 流式增量解析**
  - 审查点：两种协议的流式事件形状不同；工具调用参数分片拼接、多个并发工具调用按 index 归并、
    流末尾用量块的解析。
  - 必须看到的证据：每种协议至少有一条"工具参数跨多个分片"和一条"一轮多个工具调用"的 MockTransport 用例。
  - 常见假绿：mock 是实现者按自己理解写的，实现和 mock 一起错。对照官方文档形状核对 mock 本身。
- [ ] **B2【必审】多轮工具历史序列化与 `reasoning_content` 回放**
  - 审查点：assistant 的工具调用与 tool 结果在下一轮请求体中的形状；`reasoning_content` 是否只在对应协议回放。
  - 必须看到的证据：断言请求体的测试（不是只断言返回值）。
- [ ] **B3【必审】缓存计量与 `LLM_THINKING`**
  - 审查点：提供方未上报缓存字段时为 `None` 而不是 0；`LLM_THINKING` 必须显式配置，不依赖提供方默认。
- [ ] **B4【抽审】只增不改与费用边界**
  - 审查点：`complete()` 签名与行为不变、v1 全部测试仍绿；未新增 `respx`；Task 6 未被执行或伪造结果；
    Task 5 默认模型名迁移后 `.env.example`、`config.py`、README 与测试一致，没有残留 `deepseek-chat` / `deepseek-v4-flash`。
  - 注意：B Task 4–5 与 D 都改 `config.py`，审查时确认没有覆盖对方改动。

### 模块 C · 数据迁移与种子（`plans/2026-09-21-n1-data-migration-and-seeds.md`，实现：Sol）

- [x] **C1【必审】Task 2 既有行回填**
  - 审查点：预检发现无法唯一映射的行时 `RAISE` 中止并报出行数与订单号，而不是猜；
    迁移不 import 应用代码（用 SQL `CASE`），且与 `app/domain/order_status_mapping.py` 的映射逐项一致；
    先可空加列 → 回填 → `SET NOT NULL` + CHECK → `lifecycle_origin` `DROP DEFAULT` 的顺序。
  - 必须看到的证据：`tests/integration/test_legacy_backfill.py` 在**有 v1 订单的库**上跑升级 → 降级 → 再升级；
    有一条用例构造歧义行并断言迁移中止。
  - 常见假绿：只在空库上跑通迁移。
- [x] **C2【必审】Task 3 事件账本不可变**
  - 审查点：追加写由数据库触发器保证，不靠应用层；回填事件的 `dedupe_key` 确定、可重复；
    投影可由事件重算（`rebuild_projections`）。
  - 必须看到的证据：直接对事件表执行 UPDATE / DELETE 被拒的测试，断言具体 SQLSTATE 与约束 / 触发器名。
- [x] **C3【必审】约束测试的写法**
  - 审查点：全部约束测试断言具体 SQLSTATE 与约束名（`DBAPIError`），不存在 `pytest.raises(Exception)` 之类恒绿写法。
  - 做法：全文搜索一遍，逐个看。
- [x] **C4【抽审】可售量不建列、枚举一致**
  - 审查点：可售量由「在库 − 占用」派生，没有第二事实源；`test_db_enums_equal_contract_enums` 存在且真的比对全部枚举。
- [x] **C5【抽审】迁移链与种子**
  - 审查点：`alembic heads` 恰好一个；与 D 共用的 `0017`–`0026` 修订号没有冲突或分叉；
    种子同一 seed 两次运行字节一致、演示商家恒为 3 家；`agent_sessions` 表没有在 C 中重复建。

### 模块 D · 会话身份（`plans/2026-09-21-n1-session-identity.md`，实现：Opus）

- [ ] **D1【必审】Task 1–3 凭证**
  - 审查点：明文会话 ID 只在签发时存在，库中只有指纹；`resolve()` 先按指纹查唯一索引再 `hmac.compare_digest`；
    过期、已注销、已撤销对外不可区分。
  - 必须看到的证据：计划中 `test_issued_token_is_not_stored_in_plaintext`、
    `test_expired_revoked_and_missing_are_indistinguishable` 存在且未被弱化。
- [ ] **D2【必审】Task 3 绑定演示顾客的事务与并发**
  - 审查点：`SELECT ... FOR UPDATE` 锁会话行，没有先读后写竞态；绑定与购物车合并同事务，合并失败时 `buyer_key` 保持 `NULL`；
    同身份幂等、异身份 `409 SESSION_ALREADY_BOUND`；`bind_demo_customer` 不接受请求体顾客 ID。
  - 必须看到的证据：并发绑定不同身份只有一方生效的真实 PostgreSQL 测试。
- [ ] **D3【必审】Task 3 撤销级联与启动对账**
  - 审查点：`revoke_by_issuer()` 不是孤立方法——启动时与 `DEMO_MERCHANT_TOKENS` 对账并撤销已移除 issuer；只比较指纹，不记录原 Token。
- [ ] **D4【必审】Task 4 角色守卫**
  - 审查点：角色不符是 403 + 审计，不是 401；未绑定顾客走 `CUSTOMER_BINDING_REQUIRED`，不复用 `SESSION_ROLE_MISMATCH`；
    依赖不读取请求体 / 查询参数 / 其他头里的 `merchant_id` / `buyer_key`；管理端点不受 `X-Session-Id` 影响；
    审计不含明文 session、`buyer_key`、请求正文。
  - 必须看到的证据：v1 `tests/api/` 零回归。
- [ ] **D5【必审】Task 5 统一 403 非枚举**
  - 审查点：「不存在」与「不属于当前主体」响应逐字段一致、耗时一致（`security_timing` 哨兵）；
    `require_owned()` 是一次定形查询，不是先查存在再查归属；`scope_probe` 只在测试中可见，没有被 `app/` 导入。
  - 常见假绿：只比较状态码，不比较响应体、响应头和耗时分布。
- [ ] **D6【抽审】Task 6–7 来源状态与签发路由**
  - 审查点：来源状态按「登录主体 + 店铺 + 对话」隔离并带版本号防覆盖；5 条签发路由带 `Cache-Control: no-store`；
    `docs/api.json` 只新增这 5 条 v2 路径；日志与 tracing 对 `X-Session-Id` 全量脱敏；生产环境弱 `BUYER_ALIAS_SECRET` 启动失败。

### 模块 E · 评测骨架（`plans/2026-09-21-n1-eval-harness.md`）

- [ ] **E1【必审】Task 2 关键安全集**
  - 审查点：跨租户、SQL 注入意图、身份覆盖、`buyer_key` 伪造四类每类 ≥3 条且打到真实端点 / 原语；
    权限、金额、状态迁移全部由代码断言，安全用例不使用 LLM 裁判；`introduced_in` 与路由覆盖守卫生效。
- [ ] **E2【必审】零 skip 钩子**
  - 审查点：缺数据库时门禁运行**失败**而不是整批 skip 变绿。
  - 必须看到的证据：故意不配数据库跑一次门禁，确认失败。
- [x] **E3【抽审】隔离与基线**（2026-09-24 Astra 独立复审：有条件通过 → 用户裁定后通过）
  - 审查点：`app/eval/` 不被任何生产模块 import 的扫描测试存在；LangGraph 基线的依赖与评测数据已固定；
    `CURRENT_MILESTONE` 只能由里程碑收尾任务修改。
  - **2026-09-24 发现**：`CURRENT_MILESTONE`（`tests/eval/test_security_gate.py:26`）在 N2 收尾前已被
    改为 `"N2"`，改动来源未查明。**用户裁定：保留 `"N2"`，不回退**（补记录，见
    `plans/2026-09-21-n2-merchant-drafts-and-inventory.md` Task 9）。不算假绿——新门禁下用例无论如何都会执行，
    该常量只影响各类最少条数，改严更严格。

---

## 五、N2

> **2026-09-24 独立复审完成，N2 审查通过。** 子代理扮演 Astra 角色按本节逐项审查并出具 §九模板结论
> （首次尝试因会话额度限流中断于 N2-1，额度重置后完整重跑）。复审中新发现三项问题并已全部修复：
> ① `test_merchant_chat.py` / `test_shop_chat.py` 各两组参数化用例因查询未按 `operation` 过滤断言错误记录；
> ② `draft_apply.py::_lock()` 的 `FOR UPDATE` 未加 `populate_existing=True`，可能导致已丢弃草稿被重新应用
> （已修复并加回归测试）；③ `app/core/errors.py` 的 `IdempotentReplay` 为从未被抛出的死代码（已删除）。
> 修复后真实 PostgreSQL 全量回归 **2861 passed / 0 failed / 1 deselected**；`ruff check .` 全绿；
> `mypy app` 232 个文件通过；两个前端 `codegen:check` / lint / typecheck / 单测全部通过。
> 详见 [N2 整改计划](2026-09-24-n2-review-remediation.md) Task 5 与 `docs/project-progress.md` 顶部条目。
> `shop/` 已由 `n2-shop-nextjs-app` 交付，不再是缺口。

- [x] **N2-1【必审】`n2-tool-loop-and-registry` Task 2 四类闸门**（2026-09-24 Astra 独立复审：通过，2 条建议未阻塞）
  - 审查点：闸门零 LLM、在工具执行前生效；两类失败用不同异常表达；模型不能通过工具参数改写身份或商家范围。
  - 必须看到的证据：`test_gates.py`：来源闸门拒绝其他对话的对象、闸门固定顺序（spy 断言调用序列）、护栏原因对商家可见、安全闸门对所有角色中性、审批闸门把写操作转为草稿；两类异常分别断言；闸门路径零 LLM 调用。
  - 常见假绿：闸门只在单测里被直接调用，主循环实际没经过闸门；spy 只断言「被调用过」而不是「在工具执行前被调用」。
- [x] **N2-2【必审】`n2-tool-loop-and-registry` Task 3–4 预算与主循环**（2026-09-24 Astra 独立复审：有条件通过 → 阻塞项（4 个失败测试、ruff 错误）已修复并复跑全绿）
  - 审查点：轮数、工具、LLM 调用、时间、token 上限都有测试打到边界；v2 使用 `AGENT_LOOP_MAX_LLM_CALLS`，v1 的上限不变；
    超限时降级字段对用户可见（R7），不把规则兜底包装成模型分析。
  - 必须看到的证据：`test_limits.py` 三条（最坏路径预算不足被拒、默认预算满足公式、v1 预算不受影响）+ v1 零回归；`test_runner.py`：最大轮数停止并披露、致命错误终止且不进 Reviewer、只读并发、含写批次串行、确定性检查先于 LLM Reviewer、工具结果注入被围栏、客户端断开后不再调 LLM；五项上限各有一条打到边界的用例。
  - 常见假绿：上限只测「超过」没测「恰好等于」；降级字段在 Schema 里存在，但测试没断言它出现在响应里（R7）。
- [x] **N2-3【必审】`n2-merchant-drafts-and-inventory` Task 3 审批证据**（2026-09-24 Astra 独立复审：有条件通过 → 死代码已删除、文档描述已更正）
  - 审查点：按契约 §8.7.9 落地，没有另立一套密钥或防重放；nonce 持久化并与业务写入**同事务**原子消费；
    各类证据错误对外同一中性结构；Agent 工具结果、MCP、SSE、日志、审计都拿不到证据。
  - 必须看到的证据：迁移升降级 + `alembic check`；同 request id 重试返回首次结果、换 request id 复用证据被拒、各类证据失败对外不可区分（逐字段比较）、证据绑定草稿版本与签发会话、消费记录跨进程重启仍有效、草稿详情不可缓存、任何工具或 SSE 路径拿不到证据（注册表扫描）。
  - 常见假绿：nonce 存在内存或独立事务里，重启测试其实是同一进程；「不可区分」只比了状态码没比响应体。
- [x] **N2-4【必审】`n2-merchant-drafts-and-inventory` Task 4 应用事务**（2026-09-24 Astra 独立复审：有条件通过 → `_lock()` 并发缺陷已修复并加回归测试）
  - 审查点：固定步骤顺序（归属检查 → 幂等查询 → 证据消费 → 写入）；**模型无法自批**——任何工具路径都不能产生已批准状态；
    草稿过期由业务路径自检截止时间，不依赖 Cron。
  - 必须看到的证据：**真实 PostgreSQL**：基线过期时拒绝并保留暂存、护栏按当前配置复检、并发应用恰有一个成功、账本同时记录起草者与批准者、跨店应用 403 且写审计；固定步骤顺序在代码里可见；扫描注册表确认没有工具能产生已批准状态。
  - 常见假绿：并发测试用同一个连接串行执行，两个任务从未真正竞争；「模型不能自批」只测了一个工具。
- [x] **N2-5【必审】`n2-trade-closed-loop` Task 3 结账事务**（2026-09-24 Astra 独立复审：通过，1 条建议未阻塞）
  - 审查点：真实 PostgreSQL 上的并发超卖测试；不可用项明确返回清单、不静默调整；按 §8.7.3 唯一域幂等；
    `lifecycle_origin = 'V2'` 并在同事务同步投影；`buyer_key` 来自会话。
  - 必须看到的证据：**真实 PostgreSQL**：最后一件的竞争恰有一个成功、一行失败整单回滚、重复提交返回同一订单、客户端传价被拒、价格快照不受后续调价影响。
  - 常见假绿：`db_pool` 只开了一个连接；库存初值足够大，竞争从未发生。
- [x] **N2-6【必审】`n2-trade-closed-loop` Task 4 支付与超时关闭竞争**（2026-09-24 Astra 独立复审：通过，1 条建议未阻塞）
  - 审查点：支付与超时关闭并发时只有一方生效，占库存正确释放；未支付关闭由业务路径自检，Cron 只清理。
  - 必须看到的证据：支付与关闭竞争恰有一方生效且占库正确释放、支付幂等、截止时间后支付失败（即使关闭任务没跑）、关闭任务只动超过 30 分钟的订单。
  - 常见假绿：用真实时钟等待而不是注入时钟，测试偶发通过；关闭逻辑只在 Cron 里，业务路径没有自检。
- [x] **N2-7【抽审】安全集补齐**（2026-09-24 Astra 独立复审：有条件通过 → `CURRENT_MILESTONE` 由用户裁定保留 N2；攻击强度补强已完成）
  - 审查点：越权审批、模型自批、提示词注入（顾客对话、商品描述、知识文档三个入口）三类已登记且真实运行，七类零失败。
  - 必须看到的证据：七类用例全部登记，`introduced_in: N2`、`form: ENDPOINT`，每类 ≥3 条，真实 PostgreSQL 上零 skip、零失败。
  - 常见假绿：用例登记了但被 `introduced_in` 过滤掉没跑；`CURRENT_MILESTONE` 被某个模块提前改成 N2。
  - 2026-09-24 补强证据：注入攻击使用真实 `set_cart_item` / `draft_restock`，断言预期的来源、身份或角色闸门及审计；自批先由真实 `get_inventory_alerts` → `draft_restock` 产生待审批草稿，再证明聊天无法调用应用工具、草稿和库存保持原状态。独立 PostgreSQL 测试库上安全门禁 58 passed。
- [x] **N2-8【抽审】两个前端的凭证处理**（2026-09-24 Astra 独立复审：通过，1 条建议未阻塞）
  - 审查点：会话 ID 只在内存、不写 URL / localStorage；Vue 端审批界面不回显证据；组件不直接消费 `generated.ts`；
    Next.js 端未绑定访客刷新后的提示与 PRD C3 一致。
  - 必须看到的证据：搜索 `localStorage` / `sessionStorage` / URL 拼接会话 ID 为零；组件不 import `generated.ts`；`shop/` 刷新提示有测试。
  - 常见假绿：E2E 只跑了「已绑定」路径；证据虽未渲染但被写进 Pinia 持久化状态。

## 六、N3

- [x] **N3-1【必审】`n3-skill-loader` Task 2 白名单目录与路径逃逸**
  - 审查点：`../`、绝对路径、符号链接、编码绕过都被拒；只加载受信目录中的 Skill。
  - **2026-09-25 Astra 审查通过。** 11 个逃逸用例独立复核（脚本重跑 `NAME_PATTERN`，非仅信任测试断言），
    全部在白名单正则层被结构性拒绝；`reject_links()` 变异测试证实符号链接/junction 有双层防御
    （逐级 `is_symlink()`/`is_junction()` + `resolve()` 后 `is_relative_to()` 兜底），junction 用例在
    本机 Windows 实际执行通过（不需管理员权限）；受信通道判定（`runner.py::tool_content()`）核对
    工具名 + 成功 + `isinstance(payload, SkillSpec)` + 角色归属四者，结构上无法被其他工具伪造。
    `ruff check`、`mypy` 全绿。详见 `docs/project-progress.md` 本轮记录。
- [x] **N3-2【必审】`n3-customer-skills-and-after-sales` Task 3–4 退款计算与售后状态机**
  - 审查点：金额整数分、舍入顺序与契约一致；单行累计退款不超过快照金额；状态迁移按类型限定，非法迁移被拒。
  - 触发方已于 2026-09-24 由用户裁定并写入 PRD §7.2、契约 §8.11.2：审查时核对状态机同时校验迁移表与触发方，`SYSTEM` 跳只能同事务续跳。
  - **2026-09-26 独立审查（Codex）核心通过，F2 预览金额不一致；2026-09-28 复审（Opus，非实现者）通过**，
    F2 已修复并有回归测试。详见 `plans/2026-09-26-n3-independent-review.md`「整改后复审」。
- [x] **N3-3【必审】`n3-customer-skills-and-after-sales` Task 5 顾客发起售后两阶段确认**
  - 审查点：确认令牌签名、一次性、绑定主体与资源；模型不能替顾客完成确认。
  - **2026-09-26 独立审查（Codex）因 F3 不通过；2026-09-28 复审（Opus，非实现者）通过**：顺序为归属 → 验证 → 消费 →
    加锁复检，已消费返回 `CONFIRMATION_REQUIRED`，失败随事务回滚；顾客工具只产出预览，拿不到令牌。
- [x] **N3-4【必审】`n3-merchant-skills` Task 5–6：导出、口径问答；`n3-customer-skills-and-after-sales` Task 8、10：售后决定处理器与客服回复**（2026-09-24 N3 分 A/B/C 阶段后客服回复移入阶段 B）
  - 审查点：导出范围由后端强制商家范围与行数上限（R4）；指标口径的 SQL 只来自受控资产、不回流执行；
    商家售后决定统一走草稿审批（`DraftKind.AFTER_SALE_DECISION`，payload 不含金额）；商家只看到脱敏别名。
  - **2026-09-28 审核记录（Opus；用户 2026-09-28 指示由本会话完成审查并收口，据此勾选。下载审计修复为本会话自审）：**
    四个审查点在代码层成立——导出商家 ID 取自服务端会话并纳入签名、日期取自落库记录、创建与下载各卡
    1000 行上限；`get_metric_definition` 只读正式目录与字段注释、不执行 SQL、不升级为 LLM 调用；
    `DecisionPayload` `extra="forbid"` 无金额，退款在批准时按快照后端计算，回复随批准写入；商家端 Schema、
    路由、工具无 `buyer_key`，只有 `buyer_alias`。
    **发现并已修复 1 处阻塞项**：PRD §408 / SEC10 要求「创建与下载分别审计」，但 `/api/exports/{export_id}`
    从未写下载审计（`export.py` 注释与此前台账均误称已覆盖）。已在签名校验通过、内容生成成功后写
    `EXPORT_DOWNLOADED`，失败下载不写；新增 `test_signed_download_is_audited_separately_from_creation`、
    `test_rejected_download_writes_no_download_audit`（先红后绿），OpenAPI 无变化。
    **未修复的次要项**：CSV 公式转义未覆盖以 `\t`、`\r` 开头的单元格；`sale_detail` 对工单存在性用 `assert`；
    售后工具显示语言写死中文。
- [x] **N3-5【抽审】`n3-skill-loader` Task 4 冲突与回归**
  - 审查点：多个 Skill 同时命中时有确定性裁决，冲突测试真的覆盖了 11 个 Skill 的组合。
  - **2026-09-25 Astra 审查通过（有条件）。** 裁决顺序固定写在静态提示 `_INDEX_HEADER`、不依赖 Skill 正文，
    `test_safety_rule_wins_over_skill_instruction`、`test_two_conflicting_skills_both_load_in_call_order`
    验证越界指令换不来新能力、两个互斥 Skill 加载时互不覆盖。**条件**：11 个 Skill 的真实组合尚不存在
    （B/C 阶段业务 Skill 未落地），"覆盖 11 个 Skill 组合"目前只在框架层面成立；B/C 各自 `cases.yaml`
    落地后需要补一次真实组合的回归复核。
  - **2026-09-26 独立审查（Codex）因 F4 判不通过，不得沿用阶段 A 的有条件通过。2026-09-28 复审（Opus）通过（机制层）**：
    `tests/unit/skills/test_real_skill_cases.py` 以 11 份真实 Skill 执行 44 条用例与 27 组同角色两两组合；跨角色加载被拒。
    脚本化模型按 YAML 期望加载，只证明加载、角色、围栏与不覆盖；真实模型意图选择质量按 R3 待人工验收。

## 七、N4

- [x] **N4-1【必审】`n4-memory-pipeline` Task 1 双重过滤**
  - 审查点：顾客记忆按 `merchant_id + buyer_key`、商家记忆按 `merchant_id` 过滤，且在查询层强制，不靠调用方自觉；
    v1 商家记忆没有迁入 v2。
  - **2026-09-27 编组说明**：PRD A6 的「双重过滤」指写入前后的敏感信息过滤，与上述租户隔离是两件事；本项两者都审。任务对应改为 Task 0、1、4、5，证据要求见 `plans/2026-09-27-n4-assignment-and-review.md` §四。
- [x] **N4-2【必审】`n4-memory-pipeline` Task 2–3 抽取与异步管线**
  - 审查点：抽取不写入隐私字段；异步失败不影响主回答；顾客记忆 180 天过期由读取路径自检，Cron 只清理。
  - **2026-09-27 编组说明**：180 天过期落在 Task 4，已并入本项；异步方式按后端计划 §6.13 为 outbox，不是 `BackgroundTasks`。
- [ ] **N4-3【抽审】**（2026-10-05：冻结口径真实重跑与 60 份独立盲审已完成，跨组判定为**有条件通过**；两策略真实来源保留分别仅 6/12、7/12，质量缺陷未清零，故不勾为无条件通过；见 `docs/history/eval/n1-n4-final-acceptance-synthesis-2026-10-05.md`）**`n4-context-compaction` Task 1、Task 5**
  - 审查点：三项必保留信息在两种策略下都保留；E5 对比实验的指标与样本在跑之前就固定，没有看结果后再改口径。
- [x] **N4-4【抽审】`n4-hybrid-retrieval` Task 2、Task 5**
  - 审查点：索引版本状态机切换是原子的，切换中途失败不留下半新半旧索引；重排没有证明收益就不保留。

## 八、N5 与入口审查

- [x] **N5-1【必审】`n5-mcp-readonly` Task 1 凭证**（2026-10-03 独立子代理审查：通过；建议 G1/G2 已采纳）
  - 审查点：只经后端命令行签发与撤销；原值只展示一次、库中存哈希；限定商家、scope、有效期；撤销后下一次请求即失效。
- [x] **N5-2【必审】`n5-mcp-readonly` Task 2–3 鉴权顺序与工具面投影**（2026-10-03 独立子代理审查：有条件通过 → F1 限流键、F2 错误分层、F3 降级透传、F4 输出规整、F5 通知阶梯整改后复核通过）
  - 审查点：鉴权先于任何数据访问；MCP 工具面只读，写工具与审批证据不可见。
- [ ] **N5-3【必审】`n5-budget-ops-and-railway` Task 1、Task 6 预算与公开部署前置**
  - 审查点：基础限流、单请求 LLM 上限、每日预算熔断三项都生效后才允许真实 Key 部署到公开地址；
    `/api/admin/ops/status` 不返回 Token、Prompt、经营数据或完整请求正文。
  - **2026-09-27 编组说明**：`ops/status` 禁止项属 Task 3，已并入本项；本项拆两批审（代码 / 公网验收记录），见 `plans/2026-09-27-n5-assignment-and-review.md` §五。
  - **2026-10-05 独立代码审查未通过**：两端 v2 Chat 缺限流、单请求预算耗尽仍预扣日额度、预估未计完整工具参数。前两项已修复，预估改为 UTF-8 字节加完整序列化工具参数和协议余量；预算守卫 26 例、相关集成 48 例通过。上游实际用量若仍高于预扣，单次调用可使当日实耗超上限；公网批次未验收，保持未勾选。
- [ ] **N5-4【抽审】`n5-budget-ops-and-railway` Task 4 Cron**
  - 审查点：所有任务幂等、可重入；迁移不由 Backend 或 Cron 并发执行。
  - **2026-10-05 独立只读审查**：发现索引构建返回 `FAILED` 被记成 Cron 成功，以及过期订单单笔失败中断同批；两项已按先红后绿修复，本地 Cron／指标仓储／支付竞态／索引版本相关 64 例通过。修复后的独立复核与 Railway 实际调度尚未完成，继续不勾选。
- [ ] **N5-5【抽审】`n5-final-eval-and-closeout` Task 1、Task 4**
  - 审查点：路由覆盖对账以代码为准；全量评测报告不把局部通过称为全量通过、不把待人工验收项写成已验证。
  - **2026-10-05 独立抽审未通过**：E2/E3 全量指标缺实测已在报告列明，§12.3 三指标联合对账已补。另发现 §12.1 的旧时序证据实际测商品探针；现补真实订单详情端点各 500 次时序测试并在独占一次性 PostgreSQL 运行通过。N5MCP 数量门槛原未启用，现切至 N5 并纳入该类别，守卫 2 例通过。需对修订后的矩阵和报告复核，保持未勾选。

### 入口审查（每个里程碑开工前一次）

- [x] **入口-N2**（2026-09-24 Astra 独立复审：有条件通过 → 计划文字漂移已修正，见 §五） / [x] **入口-N3**（2026-09-26 Codex 独立审查：有条件通过） / [x] **入口-N4**（2026-09-28 Opus：有条件通过，见下） / [x] **入口-N5**（2026-10-03 独立子代理审查：有条件通过——E1–E4 计划与部署文档漂移已当日修正，P1「事后补审」如实记录；见 `.superpowers/sdd/2026-09-21-n5-mcp-readonly/progress.md`）
  - **入口-N4 结论（2026-09-28，按当日 00:34 后的计划版本核对）**：
    - `n4-context-compaction`：通过。`agent_loop_max_llm_calls` 公式校验（`config.py:263`）与 `compaction_max_calls` 在位；§6.12 两策略、
      三项必保留、历史数字无来源与计划一致；D-N4-1 已裁定。
    - `n4-memory-pipeline`：通过。三张记忆表在真实库存在（迁移 `20260922_0022`）；`app/schemas/v2/memory.py` 有 `CustomerMemoryItem`
      至 `MerchantMemoryDeleteResponse`，记忆路由未挂载；§6.13 的 outbox + `SKIP LOCKED`、禁用 `BackgroundTasks`、访客不抽取、
      独立预算、180 天不续期、写入前后过滤均已写入计划。与压缩计划 Task 0 串行属流程约束。
    - `n4-hybrid-retrieval`：**有条件**。S7 两层基准（`tests/e2e/test_s7_definitions_loop.py`、`frontend/e2e/n3/merchant-skills.spec.ts`）
      存在且通过；§6.14 原子切换、失败沿用旧版并标陈旧、无旧版降级关键词三条必测均有计划用例。**阻塞**：本地镜像
      `postgres:16-alpine` 无 pgvector（计划 Task 2 步骤 0 处理），**Railway Postgres 是否可启用 `vector` 须用户确认**，未确认前 C 不开工。
      文字漂移：`load_domain` 实际在 `retrieval.py:200`（计划写 169，为类定义行）、`search_rules` 调用在 `definitions.py:145`（计划写 133），
      已在计划中改正；Task 4 测试名 `test_retrieve_signature_unchanged` 为旧称，内容已按 `load_domain` 写，不影响。
    - 三份计划共同的「N3 整体验收通过」条件以 `docs/project-progress.md` 2026-09-28 N3 验收记录为准。
  - 审查点：对照上游计划**实际落地**的接口，逐项核对本里程碑各计划的「入口条件」；
    发现不一致时列出需按 PRD → 契约 → 计划 → 索引修正的位置，不在实现里自选。

---

## 九、审查结论模板

```text
审查项：<编号与名称>
审查者：Astra（实现者：<模型>）
范围：<文件 / 提交范围 / 测试命令>
结论：通过 | 有条件通过 | 不通过
问题：
  1. [严重|一般|建议] <文件:行> <问题> —— <会导致的具体后果>
证据核对：<逐条对照本清单「必须看到的证据」，缺哪条写哪条>
未覆盖：<本次没看的部分及原因>
```
