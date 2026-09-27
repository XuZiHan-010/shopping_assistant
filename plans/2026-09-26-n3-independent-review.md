# N3 独立审查记录（2026-09-26）

依据：`2026-09-24-n3-assignment-and-review.md`、`2026-09-22-astra-checklist.md` §六/§八/§九、现行 PRD 与后端契约。

本轮为只读代码审查与本地验证，不承担修复。审查者：Codex（本轮独立审查）；实现者按分工文件为 Opus / Sol，前端为 Sonnet / Terra。审查对象是当前未提交工作树，不是固定提交。未调用真实 LLM，未执行 Git 发布操作，未修改生产代码或只读快照。

## 结论

**N3 不通过整体验收。** 发现导出护栏缺失、退款预览金额不一致、确认令牌错误契约不一致，以及 Skill 回归证据未真正执行四项问题。另有当前静态检查失败和阶段 C 收口证据缺失。

| 审查项 | 结论 | 证据与限制 |
| --- | --- | --- |
| 入口-N3 | 有条件通过 | A 的角色类型、受信加载与草稿分派接口存在；B/C 所需 M5/M6/M7 表及两项唯一约束在独立测试库实际存在；单一 head `20260925_0040`。N2 既有审查记录可追溯，本轮复跑范围包含 S1/S3 与审批回归，但不替代 N2 产品完整验收；入口勾选和 C 进度文字仍需实施者对齐。 |
| N3-1 路径与受信通道 | 有条件通过 | 名字白名单、启动时目录扫描、运行期内存索引、角色限制、链接与 resolve 双层检查、工具名/成功/SkillSpec/角色四条件均在代码中；本机三项符号链接用例跳过，Windows junction 有实际用例。Linux 证据仅沿用此前记录，本轮未重跑。 |
| N3-2 退款与状态机 | 核心通过；关联金额展示有问题 | Decimal 元内部计算、边界整数分、逐行舍入、历史退款封顶、类型×状态×触发方、47 次上限、SYSTEM 同事务续跳均有实现与测试。聊天预览未复用退款余额计算，见 F2；不能据核心通过判定售后整体通过。 |
| N3-3 顾客两阶段确认 | 不通过 | 签名、purpose 隔离、主体/会话/资源/请求绑定、持久 nonce 与业务同事务、同请求幂等、并发建单互斥成立；已消费证据错误契约被资格预检遮盖，见 F3。 |
| N3-4 导出/口径/售后决定/客服回复 | 不通过 | 导出商家绑定成立，但行数与日期护栏缺失，见 F1。口径来自 MetricRepository/字段注释，未发现任意 SQL 执行通道。售后决定 payload 禁止金额，经统一审批骨架复检并写账本；商家结构化身份用 buyer_alias，详情先审计；回复与决定同事务。 |
| N3-5 11 Skill 冲突回归 | 不通过 | 11 个 Skill、44 条 YAML 用例确实存在，但断言引用不存在的响应字段，现有测试只校验结构；组合测试仍是两个临时示例 Skill，见 F4。不得将此前阶段 A 的“有条件通过”升级为完整通过。 |

## 问题清单

### F1 · 严重：导出没有后端行数上限，也未约束日期跨度

- 位置：`backend/app/tools/merchant/export.py:40`、`:57`；`backend/app/repositories/analytics.py:743`、`:764`。
- `CreateExportArgs` 只把 start/end 转成日期；工具直接创建 ExportSpec，未走带日期规范化的 SafeQueryService。`export_detail()` 查询无 LIMIT，随后把全部结果物化为 list 并组装 CSV。
- 独立探针实际接受 `1900-01-01 → 2099-12-31` 和倒置日期 `2026-09-26 → 2026-01-01`；捕获下载 SQLAlchemy 查询，`_limit_clause is None`。商家过滤确实存在，本发现不是跨店泄漏。
- 后果：可以签发不限跨度、不限行数的同步导出；大结果集占用数据库、内存与请求时间，违反 R4 和 C Task 5 明确的“超限拒绝、建议缩小范围”。工具返回 `row_count=None`，也没有要求的总行数/当前行数/达上限信息。
- 建议：在后端统一校验日期、限定最大导出行数并用上限加一探测超限；按契约拒绝，不静默截断。创建与下载都应保持限制，并补真实下载超限测试；不得只在工具提示里写限制。

### F2 · 一般：聊天售后预览没有扣除历史退款

- 位置：`backend/app/tools/customer/after_sale.py:145`–147；对照 `backend/app/services/v2/after_sales.py:201`。
- prepare_after_sale 直接对选中行 `line_total` 求和；界面预检则通过退款表和 refundable 计算余额。
- 真实 PostgreSQL 复现：同一订单行实付 100 元，历史 REFUNDED 记录 30 元；工具预览为 **10000 分**，界面 challenge 为 **7000 分**，金额一致性断言失败。
- 后果：模型得到的可退金额与顾客实际确认金额不同；已退完某一行但整单尚未全退时，也可能为该行给出原价预览。现有批准时封顶仍在，未发现因此实际超额退款。
- 建议：资格、选中行校验和金额预览共用确定性服务；覆盖部分已退、选中已退完行和多行混合情况。

### F3 · 一般：已消费确认令牌未返回约定的中性证据错误

- 位置：`backend/app/services/v2/after_sales.py:280`–289；契约 §8.11.2 第 3 条。
- confirm_after_sale 在 verify/consume 前执行 `_precheck`；成功建单后换 client_request_id 重放旧 token，会先命中 ALREADY_IN_PROGRESS。
- 真实端点复现：challenge 200 → 首次确认 201 → 换请求 ID 重放，实际 `422 GUARDRAIL_REJECTED` / `ALREADY_IN_PROGRESS`，期望 `422 CONFIRMATION_REQUIRED`。
- 后果：证据失败的公开契约不一致；前端可能按业务拒绝处理，而不是提示重新取得确认。没有重复建单，不能将此问题表述为重放写入成功。
- 建议：保留归属检查和同请求幂等回放优先级，调整新请求的证据验证/消费与业务复检顺序，失败整体回滚；补无效/过期/已消费及状态已改变的端点矩阵。

### F4 · 严重（验收证据）：44 条 Skill 用例尚不具备真实回归能力

- 位置：`backend/tests/unit/skills/test_merchant_skill_content.py:92`、`test_customer_skill_content.py`、`test_conflicts.py:60`；`backend/app/skills/*/*/cases.yaml`；`backend/app/eval/graders/assertions.py:102`。
- 实际统计：11 Skill、44 cases；其中 **44 条 response_field 断言**引用 `tool_calls_include`、`tool_calls_exclude` 或 `skill_conflict_resolved`。这些不是 V2ChatResponseBase 字段。
- 当前 grader 只做响应 JSON 点路径查找，没有上述特殊断言的采集/解释实现。现有用例测试只检查 YAML 可解析、数量和 id 后缀；没有把这些用例运行到端点并验证加载轨迹。
- `test_two_conflicting_skills_both_load_in_call_order` 使用临时 general-care/refund-care，不能证明实际 11 个业务 Skill 的组合覆盖。
- 建议：将加载轨迹作为评测侧证据，提供可执行断言和真实 Skill 组合回归，禁止为测试向生产响应塞入伪字段。Fake 测试验证工具与安全机制；真实模型的意图选择质量另标待人工费用授权，不能把 YAML 校验当作质量通过。

## 其他门禁与范围

- 初次本轮 `uv run ruff check .` 失败两项：`app/repositories/v2/daily_brief.py:47` E501；`tests/unit/services/v2/test_daily_brief.py:11` I001。
- 同轮 `uv run mypy app` 失败两项：`app/services/v2/daily_brief.py:209` unused-ignore；`app/repositories/v2/daily_brief.py:28` no-any-return（共检查 264 源文件）。这些是当前工作树门禁结果，不归因于本轮修改。
- 阶段 C 计划/进度仍列完整简报、工作台、双页合并评审等待收口项；当前目录已有部分新的简报实现，不能仅凭文件存在判定完成。S5/S6/S7 YAML 和局部集成用例不等于计划要求的后端与浏览器两层场景验收。现有独立 e2e 文件为 S1/S2/S3/S4，未找到 C 所需 S2/S5/S6/S7 浏览器场景文件。
- 两端 `npm run codegen:check` 本轮均通过；这只证明 generated.ts 与当前 docs/api.json 一致，不证明运行时 OpenAPI 已完整导出。
- 本轮不运行真实 LLM 摘要/质量评测，不重跑浏览器 E2E、前端全量单测/构建或后端完整全量套件；此前这些验证记录不冒充本轮结果。

## 本轮验证记录

独立本地库：`borough_n3_review_0926_test`（既有回归）、`borough_n3_probe_0926_test`（额外复现）。均在本机 55432 PostgreSQL 上新建，未使用生产库。

既有回归结果：**1474 passed / 3 skipped / 0 failed，363.25 秒**。三项跳过均为本机 Windows 无符号链接创建权限；junction 用例实际执行。范围包含 Skill、v2 服务与工具单测、v2 数据库集成、S1/S2/S3/S4 后端场景和评测门禁，不是后端完整全量。命令：

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_n3_review_0926_test'
$env:REQUIRE_INTEGRATION_DB='1'
uv run pytest tests/unit/skills tests/unit/services/v2 tests/unit/tools tests/integration/v2 tests/e2e tests/eval -q --tb=short
```

额外探针：在系统临时目录创建 `test_borough_n3_review_probe.py`，加载现有 tests.conftest；两条断言分别验证 F2/F3 的期望行为，**2 failed（8.22 秒）**，为已复现产品缺陷，不计入既有套件通过数。生产代码和现有测试未被改写。

整改顺序建议：先补 F1 导出硬限制和 F4 可执行评测，再修 F2/F3 并复跑相关回归；最后完成 C 出口与全量门禁，再决定 N3 验收状态。本记录不授予实现、付费调用或 Git 发布权限。

## 整改复核（同日，用户授权后）

以上是首次只读审查时的状态。随后已直接修复 F1–F4，原发现保留供追溯：

- **F1**：导出工具对起止日期和最多 90 天窗口进行校验；签发前按当前商家统计行数，超过同步上限 1000 行时通过工具护栏拒绝并建议缩小范围，不生成链接。下载时明细查询最多取 1001 行探测超限，拒绝而不截断 CSV；同时覆盖签发后数据增加的情况。真实 Chat 回合验证护栏反馈进入模型上下文且未产生 `ExportFile`。
- **F2**：聊天售后预览按订单行累计已完成退款，再用与界面预检一致的 `refundable` 和整数分换算；部分退款后预览与确认页金额相同。
- **F3**：新请求确认先核对订单归属，再验证并消费证据，随后在同一事务内复检业务资格；已消费 token 返回 `CONFIRMATION_REQUIRED`，同请求幂等回放仍保留，失败事务回滚。
- **F4**：移除 `skill_conflict_resolved` 伪响应字段；评测断言从评测侧加载轨迹读取 `tool_calls_include/exclude`，不污染产品响应。44 条 YAML 用例和 27 个实际 Skill 两两组合已在 Fake LLM 工具循环中执行。此验证覆盖加载与冲突机制，不代表真实模型意图选择质量；后者仍须遵守 R3 单独取得费用授权。

整改定向回归：**241 passed / 3 skipped / 0 failed**（3 项仍为 Windows 符号链接权限）；`mypy app` 检查 264 个文件通过。首次审查所记的简报模块静态错误在复核时已不再出现；本次没有把并行工作树的变化归功于上述四项修复。N3 阶段 C 出口、浏览器场景与真实模型质量仍待各自验收，因此本记录不改判为 N3 整体通过。未调用真实 LLM、未使用生产数据、未执行 Git 发布操作。
