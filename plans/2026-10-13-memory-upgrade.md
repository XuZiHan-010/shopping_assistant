# 双端记忆升级实施计划

> 在当前会话内逐项执行，采用 test-driven-development 和 executing-plans；用户已授权开始实施，不执行 Git 发布，不调用真实模型。

目标：落实 `docs/specs/2026-10-13-memory-upgrade.md`，升级稳定偏好准入、更新时序、失效屏障和按需召回。

架构：沿用 PostgreSQL/outbox/可信主体，新增角色策略与有界上下文组装模块。API 外部字段保持兼容。

## 任务 1：规格和基线
- [x] 同步 PRD C7/M11/A6、后端 §6.13/§8.14 与前端计划的记忆行为说明。
- [x] `uv run pytest tests/unit/memory tests/unit/models/test_memory_pipeline_metadata.py -q` 基线：105 passed。

## 任务 2：来源顺序与失效屏障
文件：`models/memory_v2.py`、`models/merchant.py`、`memory/pipeline.py`、两个 Store、`jobs/drain_memory_outbox.py`；迁移 `20261013_0052`。
- [x] 在 `tests/integration/v2/test_memory_upgrade.py` 写入旧任务迟到、更正、删后任务回写、关后重新开启、消息确认时间用例；观察现有行为失败。
- [x] 增加内部 `source_order`、`memory_generation` 和商家可空 `key`，编写迁移；Store 的可选参数 `source_order: int=0`、`expected_generation: int|None=None` 供真实 outbox 传入，既有调用保持兼容。
- [x] 主体锁下捕获版本、分配任务序号；排空时复检版本并按（消息时间，序号）比较写入。新消息允许重新表达；删除只取消旧版本任务。
- [x] 定向测试通过；迁移 head→0051→head 与 Alembic check 通过。

## 任务 3：长期偏好准入
文件：`memory/policy.py`（新增）、`memory/extractor.py`、E5 数据集和测试。
- [x] `tests/unit/memory/test_upgrade_policy.py` 用原话与截短证据构造临时需求、稳定分句、未知键、中英别名、角色越界候选，先红。
- [x] `canonical_identity(category, key, role)` 与 `is_long_term(value, evidence, source, supports=...)` 实现受控准入；抽取接收可选 `role`，生产排空传可信角色。
- [x] 更新 MEM-016 为不应沉淀；原始候选回放期望零写入，并新增稳定更正、临时需求评测样例。
- [x] 抽取、安全过滤、E5 Fake 回归通过。

## 任务 4：有界目录与按需读取
文件：`memory/context.py`（新增）、双端 Chat、双端召回工具。
- [x] `tests/unit/memory/test_context.py` 和双端集成测试先验证：旧类别可发现、长度有界、事实/总结不重复、读取带时间、过期/陈旧/跨主体不可读。
- [x] 目录最多 20 类、自动正文最多 3 条；系统注入上限 4000 字符，工具正文上限 6000 字符（均含 JSON/围栏），舍弃完整条目并显示截断。
- [x] 工具默认排除本回合已注入事实；顾客要求查看全部时仍引导已有记忆界面。
- [x] 双端 Chat/API/工具/历史回放回归通过。

## 任务 5：收尾
- [x] 后端全量（独占测试库、空 Key）、Ruff、mypy；公共契约无变化时验证两端 codegen:check。
- [x] 独立代码审查，修复重要发现并验证。
- [x] 更新 `docs/database.md`、导航、进度快照和本计划，报告真实模型验收与浏览器验证的限制。


## 最终验证

后端全量 4865 passed / 5 skipped（符号链接权限 3、独占哨兵 2）/ 0 failed；独占哨兵另跑 2 passed。Ruff、mypy 328 文件、两端 codegen:check、商家记忆测试 2 项与顾客 Adapter 测试 1 项通过。证据和环境限制见 `docs/history/eval/memory-upgrade-2026-10-13.md`。未做真实模型或浏览器 E2E；未执行 Git 发布和生产迁移。
