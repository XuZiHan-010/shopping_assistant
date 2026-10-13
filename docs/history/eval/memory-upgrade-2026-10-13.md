# 双端记忆升级验证记录

## 范围

规格：`docs/specs/2026-10-13-memory-upgrade.md`；主计划：`plans/2026-10-13-memory-upgrade.md`。

完成稳定偏好准入与规范键、商家同键更正、消息时间/来源序号防迟到覆盖、删除/关闭的主体版本屏障、有界类别目录、带时间的按需召回和同回合去重。公开记忆 API 路径/字段不变。

## TDD 证据

- 基线：记忆及 ORM 单测 105 passed。
- 临时限定、截短证据、别名和未知键：新增用例先出现 9 failed；最小实现后 12 passed。后续扩充中英文、角色边界、确认、业务数字、呈现语义用例。
- 顺序与失效：新增真实 PostgreSQL 用例先 5 failed（旧值覆盖、开关回写、删除回写/新确认），实现后与已有 Store/outbox 用例共 33 passed。
- 上下文新接口初次测试因模块缺失失败；实现后 4 passed。双端 Chat/工具接线前 4 failed，接线后与 API/历史回放共 22 passed。
- 同回合工具重复召回：先 2 failed，加入回合内已读取 ID 去重后通过。
- 独立审查发现「平时压过这次」、规则/订单伪装成偏好、顾客数量截断未标记；分别先复现失败再整改。最后一批记忆/E5/相关集成回归 160 passed。
- 迁移：升降级、Alembic check、旧事实不合并、旧任务按消息时间回填顺序共 2 passed。
- 独立审查复核：141 项纯 Fake 回归通过，无剩余 Critical/Important；没有运行共享数据库测试。

## 验证环境与边界

所有模型均为 Fake，`LLM_API_KEY` 为空。原 Docker WSL 磁盘只读，未进行修复或修改；另建独占可丢弃 WSL 测试环境，PostgreSQL 16.15 / pgvector 0.8.6，数据库 `borough_memory_upgrade_test`，未访问生产。全量运行前段观察到 `DataFileImmediateSync` 等待，约四分之一处将该临时实例 `fsync` 关闭以减少磁盘等待；事务、约束与行锁仍由真实 PostgreSQL 执行，本次不验证断电恢复。项目配置与生产数据库未修改。

Ruff 和 mypy（328 个生产文件）通过；两端 codegen:check 通过；商家记忆面板/Adapter 2 项、顾客记忆 Adapter 1 项通过。早期商家定向命令误用了 `.test.ts`，未找到用例；已改用实际 `.spec.ts` 执行并通过。

真实模型精度、召回质量和浏览器 E2E 未验收。本次 E5 数据集由 40 条扩到 46 条，MEM-016 改为不应沉淀，旧真实结果不可直接比较。有限准入规则可能保守拒绝合理表达，须后续固定口径真实评测。删除采用主体级屏障，会取消该主体此前全部未完成任务；不是逐键取消。

后端全量 `REQUIRE_INTEGRATION_DB=1 uv run pytest -q --durations=10`：**4865 passed / 5 skipped / 0 failed**，1368.91 秒。跳过为 3 项 Windows 符号链接权限用例及 2 项需独占运行的时序哨兵；哨兵以 `REQUIRE_SECURITY_TIMING=1` 单独执行，**2 passed**（36.70 秒）。已有 LangGraph 依赖弃用提示 1 条，未改冻结基线。首次全量在审查整改前主动中止，不作为通过证据；上述结果来自整改后完整运行。


临时环境删除命令被自动审批拒绝（仅返回 blocked by policy），未注销或递归删除，改为停止实例；临时目录和注册名 BoroughMemoryTest20261013 保留。
