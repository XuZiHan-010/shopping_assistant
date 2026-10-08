# N1 独立审查整改计划

> 2026-09-22：用户已明确授权直接修复审查问题。采用 TDD；各模块独立实现，根执行者统一运行数据库验证与全量回归。禁止 Git 发布和真实 LLM 调用。

**目标：** 修复 N1 审查发现的安全、幂等、流式与验收证据缺口，不扩大产品范围。

**设计：** 既有数据库关闭原因保留，通过领域层显式双向映射转为冻结的 API 枚举；不修改已应用迁移。会话合并由行锁内状态驱动，撤销对账未完成时不得开放会话访问。评测报告先结构化脱敏；零 skip 记录覆盖整个 pytest 会话；空集不通过。模型流以协议终止事件为完成条件。

## 任务与验证

2026-09-23 用户要求继续完成 N1 全部验收。本轮追加收口范围：

- [x] E1 语言执行链：先红后绿验证全部 HTTP turn、真实错误响应、显式语言头冲突与重复头拒绝。
- [x] E1 登记门禁：按 PRD 随对象交付，保持 N1 阶段与当前最低类别；替换过时的未来标签禁令，
  增加真实对象存在、当前阶段配额及 HTTP 双端双语分层的反向测试。
- [ ] 独占 PostgreSQL 全量（集成与时序均强制）、静态/前端验证、Astra 独立复审及状态收口。

边界复核：评测 Task 7 步骤 3 明确留到 N2，不计作 N1 未完成项；历史基线运行与双协议冒烟
证据继续保留，不新增真实调用。N2 `converse()` 费用问题仍交 N2，不在本次 N1 修复范围内。

- [x] B：`app/llm/*_adapter.py` 补终止事件校验与 Anthropic 隐去推理块回放。先用 MockTransport 证明缺终止事件会误成功，再断言 ERROR、空工具列表与保留已有文本；运行 `uv run pytest tests/unit/llm -q`。
- [x] C：`app/domain/order_status_mapping.py` 增加存储值与 `CloseReason` 双向转换，覆盖两个关闭原因与空值、未知值拒绝；补所有已有对应枚举的契约一致性检查。保留历史迁移与事实数据，更新数据计划中的表达边界。
- [x] D：仓储行锁结果控制一次性合并；改绑异常转换为 409；启动对账失败不得放行会话；规范 Bearer 解析；补 403 响应头一致性。数据库测试覆盖同身份并发、异身份冲突、事务回滚和启动恢复。
- [x] E：结构化与文本载荷脱敏、空集拒绝、session 级零 skip 记录。子进程回归必须验证一条 skip 后接 pass 仍退出非零，缺数据库也退出非零。
- [x] CI：完成可审阅的 GitHub Actions 工作流，PostgreSQL 服务、显式测试数据库、mock 配置、后端全量与独立时序哨兵、前端类型同步/会话 Adapter；无真实密钥。补静态测试防止漏跑安全门禁/时序哨兵。
- [ ] 收口：真实本地测试库全量 `REQUIRE_INTEGRATION_DB=1 REQUIRE_SECURITY_TIMING=1 uv run pytest -q`，Ruff/mypy 与前端检查；更新进度、导航及审查清单的证据说明。未提交/未触发远端 CI 与未新做真实模型调用须如实标明。

## 执行边界

工作区包含大量现有未提交实现，直接在现有工作区定点修复，不迁移或丢弃这些修改。子任务仅修改分配文件，数据库测试串行；代码修复后再次只读审查，不将自行修复自动等同于独立复审通过。

## 2026-09-23 验证与复核

- C/D/E 定向真实 PostgreSQL 回归：87 passed / 1 skipped；跳过项为未开启专用开关的时序哨兵，随后纳入启用开关的全量运行。
- 缺库反向验证使用 `127.0.0.1:1/borough_test`，未访问实际测试库：
  `REQUIRE_INTEGRATION_DB=0` 运行安全用例产生 23 skip，session 钩子强制退出码 1；
  `REQUIRE_INTEGRATION_DB=1` 运行 `SEC-BUYERKEY-001` 在夹具直接报错，退出码 1。
  两者均按预期拒绝假绿；另有 5 种隔离子进程用例覆盖 skip 后接 pass、标记 skip 与模块级 skip。
- C/CI 由非实现代理只读复核，无阻塞问题，16 项无数据库测试通过；
  D/E 由非实现代理只读复核，无阻塞问题，43 项无数据库测试通过。
- B 交叉复核发现终止事件后继续读取会误降级，已追加立即停止读取修复；新增 2 项测试先红后绿，
  streaming / Anthropic / parity 共 89 passed，streaming 36 passed。
  原审查代理复审 89 passed，确认一次性计费与响应关闭，此前 P2 已关闭。
- CI 类型检查揭露 7 个既有前端测试夹具类型错误，已改用领域类型/组件 `$props` 及精确重载；
  不改产品行为，`npm run typecheck` 通过，相关 7 文件 84 tests passed。
- 最终定向后端 LLM / 映射 / CI / 种子测试 252 passed；Ruff 全仓通过，mypy 208 文件通过；
  前端全量 53 文件、593 tests passed，`codegen:check` 通过。
- 本轮修复范围的交叉复核不等于整份 Astra 清单全部通过；原清单尚未覆盖的项目保留待审。
- 工作区已新增其他轮次的 N2 实现及其里程碑登记测试；不提前推进 `CURRENT_MILESTONE`，
  不删用例或弱化门禁以消除已登记的 N2 过渡态失败。
- 远端 GitHub Actions 未触发；没有 Git 提交/发布，没有新增真实模型调用。

## 2026-09-23 Astra 完整审核记录

审查者：Astra；实现者：B/E 为 Sonnet、D 为 Opus，前轮整改为 Codex。
范围：当前未提交工作树的 N1 B1–B4、D1–D6、E1–E3。N2 业务实现已混入工作树，
因此将 N1 审核结果与当前整仓门禁结果分别记录。此次仅修改审核记录与状态文档，不修业务实现。

### 发现与复现

1. **[一般，E1 阻塞] 安全用例的语言标签未进入真实请求。**
   `backend/app/eval/security_harness.py:207` 的 `_execute_http()` 只复制用例显式 headers，
   调用链未传递 `EvalCase.locale`，现有 N1 英文用例也未显式写 `Accept-Language`。
   无数据库 ASGI 探针复现：加载真实 `SEC-BUYERKEY-002` 并经现有 `_execute_http()` 发请求，
   输出 `declared_locale=en-US, accept_language=None, resolved_locale=zh-CN`。
   `validate_coverage()` 虽然看到两种标签，实际 HTTP 运行仍只有中文，违反 PRD E1 的有效分层要求。
   整改要求：把用例语言接入端点请求，定义显式 header 与标签冲突的处理，并断言请求头及实际响应语言；
   原语用例没有 HTTP 语言路径，不应据其标签宣称已验证英文端点。
2. **[一般，E1 / N1 收口阻塞] 当前安全门禁登记规则与 N2 已落地用例冲突。**
   `backend/tests/eval/test_security_gate.py:83` 拒绝所有比 `CURRENT_MILESTONE=N1` 更晚的用例，
   工作树已随 N2 路由登记 10 条 N2 用例。该失败此前已登记，不能把“已知”视为通过。
   需按现行 PRD 对齐“随路由登记并执行”与“里程碑收尾推进”的门禁规则及计划，保留未实现端点、
   缺失安全类别与 skip 的拒绝能力；本次不提前把里程碑改成 N2，也不删除用例。
3. **[严重，N2 交接项，不计入 N1-B 适配器缺陷] 未知用量被退款并记为已知零消耗。**
   `backend/app/llm/guard.py:186` 的新增 `converse()` 无条件按 `turn.tokens - estimated` 对账，
   随后的 `_record()` 没有传 `turn.usage_known`，默认值是 `True`。
   无网络、无数据库的 fake 复现：上游返回 `tokens=0, usage_known=False`；实际预留 `201`、
   对账 `-201`、落账 `usage_known=True, total_tokens=0`。超时/断流等未知费用可能因此逃过每日预算累计。
   原有 `complete()` 会保留未知费用预留且如实记账，N1 两协议适配器也正确返回未知标记；
   问题位于 N2 新增封装。应交 N2 费用接线复审，补未知成功、超时、断流及已知零费用对照测试。
4. **[建议，E3 非阻塞] 冻结守卫可进一步覆盖图源码哈希。**
   当前 `test_baseline_freeze.py` 只断言节点列表及源码不含 `/api/v2`；修改边或节点实现仍可能通过。
   本轮实测 `graph.py` blob 为 `5e466bd48cb6bce2fe3d4d13c78a533b00615d47`，
   `uv.lock` SHA-256 为 `772d9cd2acd8fb9bbc3e1e459c7db242fb9c8da7067e1baef26230302f36a314`，
   均与 `FROZEN.md` 一致，种子仍为 `20260804`，未发现当前基线漂移。

### 协议与范围核对

- B1 对照 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
  与 [Anthropic 流事件定义](https://platform.claude.com/docs/en/build-with-claude/streaming)：
  分片按 index 拼接、终止事件与累计 usage 处理吻合；两协议均有跨分片和多工具 MockTransport 用例。
- B2/B3 对照 [DeepSeek Anthropic 兼容范围](https://api-docs.deepseek.com/guides/anthropic_api/)
  与 [思考模式回放要求](https://api-docs.deepseek.com/guides/thinking_mode/)：
  请求体回放、协议交叉拒绝、显式 thinking 和缺缓存字段保留 None 已核对。
  `redacted_thinking` 是防御性兼容测试，DeepSeek 文档并未承诺支持，不将该 mock 当作真实供应商支持证据。
- B4 按实施计划中的后续裁定审：历史 42 次冒烟已有三批授权记录，本轮不重跑；
  历史观测注释和退役说明允许保留旧模型名，生效配置统一 `deepseek-flash`。
- D5 的一次查询由调用方 fetch 实现；N1 证明范围是测试探针与 `require_owned()`，不能替代 N2 各业务路由隔离验收。
- D6 按权威契约 §8.8.2/§8.9.2 核对：签发/绑定三个响应须 no-store，两个注销响应为 204 无体；
  清单“5 条都带 no-store”用词过宽，不据此修改业务契约。OpenAPI 已增量加入 N2 路由，
  本轮核对五条 N1 会话路由仍保留严格哨兵，不能再要求当前全仓恰好只有五条 v2 路径。

### 本轮验证证据

- 定向无数据库审核测试：**342 passed**（LLM、凭证原语、配置、日志、启动、CI、skip 钩子、评测骨架与报告）。
- `uv run ruff check .` 通过；`uv run mypy app` **208 文件通过**。
- 前端 `codegen:check`、`typecheck` 通过；会话 Adapter **5 passed**。
- 缺库反向验证：仅连接 `127.0.0.1:1/borough_test`；关闭强制 DB 开关时，1 条安全用例 skip 后
  session 钩子强制退出码 **1**；开启开关时夹具直接报错，退出码 **1**。五种隔离子进程用例亦通过。
- Docker Desktop 不可用；使用本机已有 PostgreSQL 16.15 在新临时目录、`127.0.0.1:55439`
  建立独占 `borough_test`，未复用原测试数据。以 `REQUIRE_INTEGRATION_DB=1`
  与 `REQUIRE_SECURITY_TIMING=1` 执行 `uv run pytest -q --tb=short`：
  **2435 passed / 1 failed / 0 skipped，611.72 秒，退出码 1**。
  唯一失败是 `test_no_case_is_introduced_ahead_of_its_milestone`，对应发现 2；
  时序哨兵、v1 API、凭证存储、真实并发绑定/回滚、来源版本竞争及实际安全用例均通过。
- 未触发远端 CI；本轮没有真实模型调用、Git 提交或发布。

### 逐项结论

以下各项均由 Astra 对当前实现与测试核对，具体发现编号引用上文；
“通过”限定为该审核项，不表示当前整仓门禁通过。

| 审查项 | 结论 | 证据核对 / 问题 |
| --- | --- | --- |
| B1 流式增量解析 | 通过 | `test_streaming.py` 两协议分片拼接、多工具 index 归并、末尾用量、断流与终止事件测试；已对照官方事件形状 |
| B2 历史序列化与推理回放 | 通过 | `test_history_serialization.py` 断言实际出站请求体、工具结果、同协议推理与跨协议拒绝 |
| B3 缓存与 thinking | 通过 | 两适配器缓存缺省 None、Anthropic 三项输入计量；`test_llm_config.py` 和适配器请求体断言保证显式开关 |
| B4 v1 与费用边界 | 通过 | `complete()` 签名与主体行为保留，协议切换测试、v1 回归通过；无 respx；配置及历史冒烟授权记录已核对 |
| D1 凭证 | 通过 | `test_session_repository.py` 明文不落库、缺失/过期/撤销均返回 None；唯一指纹索引后 compare_digest；公开错误统一 |
| D2 绑定事务与并发 | 通过 | 独立连接竞争、行锁内一次性合并、同身份幂等、异身份 409、合并失败整体回滚；路由拒绝自带身份 |
| D3 撤销级联与启动对账 | 通过 | issuer 指纹对账已接 lifespan；真实重启对账测试与连接失败/恢复、对账失败停止服务测试通过 |
| D4 角色守卫 | 通过 | 双向跨角色 403+审计、未绑定专用错误码、v1 API 回归、管理员独立鉴权；代码不读取客户端身份字段 |
| D5 统一 403 | 通过 | 真实探针响应体及响应头相同，单次定形查询；启用的 500 对时序样本哨兵通过；生产代码不导入 scope_probe |
| D6 来源状态与签发路由 | 通过 | 全作用域过滤、条件版本更新与并发测试、会话路由及 OpenAPI 哨兵、日志脱敏、生产弱密钥拒绝；范围解释见上文 |
| E1 安全集 | **不通过** | 13 条 N1 用例与 10 条 N2 用例实际执行通过，四类数量满足且不调用裁判；但语言标签未生效（发现 1），当前里程碑门禁仍红（发现 2） |
| E2 零 skip | 通过 | 缺库两种开关反向实跑均退出 1；skip 后 pass、标记及模块级 skip 子进程回归通过 |
| E3 隔离与冻结基线 | 通过 | 单向依赖扫描、冻结测试通过；图/锁文件哈希及种子与记录一致，CURRENT_MILESTONE 仍为 N1；发现 4 为非阻塞建议 |

未覆盖：未重新运行真实模型评测或历史冒烟；未触发远端 GitHub Actions；
未对 N2 做完整审查，也未完成入口-N2。N1 评测 Task 7 步骤 3 的真实新旧对照仍属另行验收。
本轮审核已完成 **13/13**，通过 **12/13**；连同此前 C1–C5，N1 清单为 **18/18 已审、17/18 通过**。
E1 整改与复审、全量门禁转绿之前，N1 不得标记为整体完成；上方整改“收口”复选框保持未勾选。

## 2026-09-23 E1 整改复审与最终验收停点

- E1 两项整改已完成：语言贯穿全部 HTTP turn，显式语言头冲突/大小写重复在加载时拒绝；
  登记门禁按真实方法/路由及白名单原语判断，保留 N1 阶段、到期类别数量、端点四组合分层与零 skip。
  后续阶段用例仍全部执行，但不填充当前阶段最低配额。实施计划已按 PRD §15 对齐。
- Astra 独立只读复审两轮均无阻塞问题，两份新增反向/语言测试最终 **18 passed**。
  真实 PostgreSQL 评测集 **99 passed / 0 failed / 0 skipped**（181.62 秒）。
  缺库反向验证：关闭/开启强制 DB 开关均退出 1。Ruff 全仓通过、mypy 216 文件通过；
  前端 codegen:check、typecheck、会话 Adapter 5 项通过。
- **最终验收尚未完成，不将 E1 复审通过等同于整体验收完成。**
  首次全仓回归被并行新增的 N2 `test_checkout_concurrency.py` 收集错误中断：
  当时 `app.services.v2.checkout` 尚不存在。未修改或跳过该用例以宣称全仓通过。
- 随后明确选择 N1 + v1 的 184 个测试文件：保留全部 eval、v2 Schema 与两个会话 API 文件；
  排除 N2 `integration/v2`、`integration/tools`、`unit/agent/loop`、`unit/tools`、`unit/services/v2`、
  非会话 v2 API 及 S3 支撑测试。独占 `127.0.0.1:55439/borough_n1_acceptance_test`，
  `REQUIRE_INTEGRATION_DB=1`、`REQUIRE_SECURITY_TIMING=1`，结果 **2195 passed / 6 failed / 0 skipped**
  （543.35 秒）。六个失败均在旧行回填/迁移往返时遇到 N2 新迁移 `20260923_0031`
  downgrade 删除不存在的 `order_items.title_snapshot`；需在迁移文件稳定后以新库复验，
  不能据动态工作树的失败直接修改已应用迁移或认定 N1 已通过。
- 前端全量 **646 passed / 1 failed**：`src/router/index.spec.ts`「两条路由都能渲染」15 秒超时；
  未扩大超时或将其记为通过，待稳定环境复验。
- 评测 Task 7 步骤 3 是明确的 N2 新旧对照交接项，保留未勾选；历史真实质量基线有已知缺陷，
  不声称其质量全绿。当前 E1 代码复审已关闭，但最终回归未全绿，N1 整体仍待验收收口。
  本轮未调用真实模型、未提交或触发远端 CI，未修改 N2 结账实现与迁移。
