# MVP 出口证据矩阵

**状态：** 2026-08-12；供用户决定是否宣告 MVP 完成。

## 判定口径

- `已验证` 只表示证据栏所限定的本地、Fake LLM 或历史真实 PostgreSQL 验证已成功；除非证据明确写有 Railway 线上记录，绝不表示已部署或已完成线上验收。
- `未验证` 表示缺少该出口所需的端到端、真实环境或完整覆盖证据；不是把已有本地测试判为失败。
- `已裁定偏离` 表示用户已经明确批准的产品/配置差异；不是“暂时未做”的替代名称。
- 本轮未创建 Railway 服务、未请求任何真实 API、未调用 DeepSeek，费用为 0；也没有执行 Git 提交、推送或 PR 操作。

## PRD §16 出口

| 条目 | 状态 | 证据 | 缺口说明 |
| --- | --- | --- | --- |
| 1. Railway 公开地址可打开助手 | 未验证 | `frontend/railway.json`、`backend/railway.json` 与 `docs/deployment.md` 已就绪。 | 用户尚未在 Railway 控制台创建/部署服务。 |
| 2. 与 Prototype 的桌面三栏、移动单栏视觉一致 | 未验证 | `frontend/e2e/responsive.spec.ts` 覆盖 360px/1440px；常规 Playwright 26/26 断言输出 `ok`，但 CLI 清理超时（exit 124）。 | 缺少成功退出的常规 E2E 和 F1 的 1440×1000 人工视觉比对。 |
| 3. 可选快速问题或自行输入 | 已验证 | `frontend/e2e/conversation.spec.ts` 的快速问题与自由输入场景；F6 本地 Vitest **26 文件 / 245 passed**。 | 仅本地 Mock/Fake 证据，未在部署域名复验。 |
| 4. 至少四个业务域返回演示数据 | 未验证 | `backend/tests/integration/services/test_safe_query.py` 覆盖受控指标/明细路由；F4 历史真实库 Playwright 有 3 passed。 | 没有一套完整、当前可复跑的四业务域端到端验收记录。 |
| 5. 指标问题展示口径、图表、结论和至少两条建议 | 未验证 | `frontend/e2e/real-api/analytics.spec.ts` 有历史真实后端图表与导出场景；`frontend/src/api/adapters/chat.spec.ts` 覆盖回答适配。 | 未对完整指标展示契约和“至少两条建议”作当前端到端验收。 |
| 6. 明细问题展示总数、预览和 CSV 下载 | 已验证 | `backend/tests/integration/services/test_chat_service.py::test_successful_detail_query_persists_an_export_record_and_signs_the_url`；`frontend/e2e/real-api/analytics.spec.ts` 的导出场景（历史真实库 3 passed）。 | 未在 Railway 域名复验。 |
| 7. 规则问题引用知识库且不查询经营表 | 未验证 | `backend/tests/unit/knowledge/test_domains.py::test_platform_rules_do_not_route_to_data_tables`、`backend/tests/unit/agent/test_graph.py::test_graph_rule_answer_uses_knowledge_content_and_source`。 | 缺少完整规则问题集与真实部署验收。 |
| 8. 连续追问继承上一轮上下文 | 未验证 | `backend/tests/integration/services/test_chat_service.py::test_follow_up_turn_accumulates_in_the_same_conversation`；`frontend/e2e/conversation.spec.ts` 有两轮目录场景。 | 没有完整追问问题集或部署域名证据。 |
| 9. 回答展示处理步骤和质量状态 | 未验证 | `frontend/e2e/conversation.spec.ts` 的质量轨迹可见性；`frontend/src/api/adapters/chat.spec.ts` 覆盖步骤/质量字段。 | 还原度审计 §3.6 证实 UI 只渲染最后一个步骤，未满足“处理步骤”完整展示。 |
| 10. 采纳、点赞和点踩可保存 | 已验证 | `backend/tests/api/test_feedback.py`；`frontend/e2e/conversation.spec.ts` 的键盘采纳反馈场景。 | 本地验证，未在 Railway 验收。 |
| 11. 会话可删除 | 已验证 | `backend/tests/api/test_conversations.py::test_delete_removes_the_conversation_and_returns_204`；`frontend/e2e/conversation.spec.ts` 的二次确认删除场景。 | 本地验证，未在 Railway 验收。 |
| 12. 切换商家后只能取得该商家数据 | 已验证 | `frontend/e2e/real-api/analytics.spec.ts::切换商家后看不到另一个商家的经营数据`（历史真实库）；`backend/tests/integration/repositories/test_analytics_repository.py::test_other_merchants_rows_are_never_visible`。 | 没有 Railway 环境复验。 |
| 13. 不同商家不能互查，服务端拒绝前端指定 merchant_id | 已验证 | `backend/tests/api/test_conversations.py::test_request_body_merchant_id_cannot_widen_the_data_scope`、`test_another_merchant_cannot_post_into_a_foreign_session`。 | 当前本机 Docker 不可用，未重跑全量真实库回归；也未线上复验。 |
| 14. 越权返回 403 并写审计日志 | 已验证 | `backend/tests/api/test_conversations.py::test_cross_merchant_detail_returns_audited_scope_error`、`test_cross_merchant_delete_is_forbidden_and_audited`。 | 同上，仅有本地/历史真实库测试证据。 |
| 15. 模型不能执行任意 SQL | 已验证 | `backend/tests/integration/services/test_safe_query_security.py` 的 SQL 注入与白名单安全回归；R4 的结构化意图/模板 SQL 约束。 | 未进行真实模型验收；该项安全不变量不依赖真实模型网络调用。 |
| 16. 数据库或 LLM 失败时页面显示降级或错误 | 已验证 | `backend/tests/unit/agent/test_graph.py::test_graph_marks_budget_exhaustion_as_visible_chat_degradation`；`frontend/src/api/chat.spec.ts` 的 `LLM_BUDGET_EXCEEDED` 降级适配。 | 未在线上断开数据库/LLM 后复验。 |
| 17. 1 秒内首个 SSE step，JSON 路径返回同一完整响应 | 未验证 | `backend/tests/api/test_chat.py::test_json_chat_equals_sse_done_payload` 与 `test_sse_step_events_carry_only_label_and_node`；本地 Mock E2E 先显示阶段标签。 | 未在真实 CORS 环境测量 1 秒时限。 |
| 18. 确定性路由 100%；真实模型意图准确率 ≥90% | 未验证 | Fake LLM 单测存在；真实模型调用为 0。 | 没有完整确定性路由覆盖率汇总；真实模型准确率必须用完整问题集人工评估，两次线上提问亦无法推导 ≥90%。 |
| 19. 单请求上限、每日预算、限流及显式错误/降级 | 未验证 | `backend/tests/integration/repositories/test_llm_budget_repository.py::test_concurrent_reserve_near_budget_never_overspends`、`backend/tests/api/test_rate_limit_trust_boundary.py`、`backend/tests/unit/llm/test_guard.py::test_complete_does_not_reserve_budget_when_inner_client_unconfigured`。 | 本地证明了关键机制；没有当前全量真实库重跑或部署环境的预算熔断/限流验收。 |
| 20. 360px 和 1440px 均可用 | 未验证 | `frontend/e2e/responsive.spec.ts` 覆盖两种视口，常规 E2E 断言完成但 CLI exit 124。 | 缺少成功退出的 E2E 与线上双视口验收。 |
| 21. 后端单元测试和 API 测试通过 | 未验证 | F6 定向回归共 **28 passed、1 skipped**；静态检查与 `mypy app` 通过。 | 本机 Docker daemon 不可用，未运行当前 `REQUIRE_INTEGRATION_DB=1 pytest`；历史记录不能替代当前全量结果。 |
| 22. 前端组件测试和核心 Playwright 通过 | 未验证 | Vitest **26 文件 / 245 passed**；专用首屏 Playwright 的测试断言输出 `ok 1`。 | 专用首屏与常规 `test:e2e` 都因已知 Windows `webServer` 清理挂起以 exit 124 结束；常规 E2E 的 26/26 断言也输出 `ok`，但两条命令均不能登记为全绿或成功退出的门禁。 |
| 23. 自动化测试没有真实 LLM 调用 | 已验证 | F6 Task 1–7 及 Task 8 报告均记录 DeepSeek 调用 **0**、费用 **0**；测试使用 Fake/Mock。 | 未执行真实模型验收，符合本条的零调用要求。 |
| 24. Railway 健康检查通过 | 未验证 | `backend/tests/api/test_health.py` 为本地健康契约；`frontend/public/health.html` 与 Caddy 静态处理已实现。 | 不存在 Railway URL 或线上健康检查记录。 |
| 25. LLM 密钥和数据库连接串未进入代码和构建产物 | 已验证 | `npm.cmd run secrets:check` 通过；Task 6 受控注入密钥形态会被拦截，清理后复建通过。 | 构建产物本地扫描，不是对未创建的 Railway 变量的证明。 |
| 26. 部署文档可让新 coding agent 重复部署 | 未验证 | `docs/deployment.md` 已在 Task 8 补齐双服务 Root Directory、绝对 Config File Path、变量和 CORS 顺序。 | 尚未由独立人员/新 agent 按手册完成实际 Railway 部署。 |

## 后端 B7「验收（MVP 出口）」

| 条目 | 状态 | 证据 | 缺口说明 |
| --- | --- | --- | --- |
| Railway 重启后数据仍在 | 未验证 | 历史集成记录曾核验 Docker 共享卷仍在。 | Railway 未部署，不能外推至 Railway PostgreSQL。 |
| 健康检查稳定 | 未验证 | `backend/tests/api/test_health.py`。 | 无线上连续健康检查记录。 |
| Migration 只执行一次 | 未验证 | Alembic/迁移测试存在。 | 未在 Railway 发布流程执行迁移。 |
| 应用先于数据库启动可重试 | 未验证 | 代码/部署手册有连接重试设计。 | 未在部署编排中观察。 |
| 超预算不再调用 LLM，且显式降级 | 未验证 | `test_llm_budget_repository.py` 与 `test_graph_marks_budget_exhaustion_as_visible_chat_degradation`。 | 缺少当前真实库与部署环境联测。 |
| 超频返回 `RATE_LIMITED` | 未验证 | `backend/tests/api/test_rate_limit_trust_boundary.py`、错误码适配测试。 | 缺少当前完整回归与线上验收。 |
| 伪造转发头不能绕过限流 | 已验证 | `backend/tests/api/test_rate_limit_trust_boundary.py`（历史真实 PostgreSQL 回归已过）。 | 未在 Railway 代理链复验。 |
| 运维端点需管理员令牌且不泄露敏感数据 | 已验证 | `backend/tests/api/test_admin_ops.py`；F6 Task 1 定向回归 28 passed、1 skipped。 | 未在线上复验。 |
| 生产配置下演示商家端点不可访问 | 已裁定偏离 | 用户已裁定加入显式 `DEMO_DEPLOYMENT_MODE`；`backend/tests/unit/core/test_config.py` 与 `backend/tests/api/test_demo_merchants.py` 验证默认关闭、显式演示部署才开放。 | 非演示生产仍不可访问；对外演示生产显式开启时可访问，故原“生产一律不可访问”不再适用。 |
| 日志能定位请求且不泄露隐私 | 已验证 | `backend/tests/api/test_request_logging.py`、`backend/tests/api/test_admin_ops.py` 的敏感字段断言。 | 未采集 Railway 实例日志。 |
| 前端经部署域名完成核心 E2E，真实 CORS SSE 正常流式 | 未验证 | 前端本地/Mock 与专用首屏 E2E；F6 Task 8 文档给出控制台步骤。 | Railway、精确 Origin 与真实 CORS SSE 均未执行。 |
| PRD §16 全部通过 | 未验证 | 本矩阵 PRD 表。 | 多项仍未验证，尤其真实模型准确率、完整业务覆盖、线上验收与 R9 缺口。 |

## 前端 F6「验收（MVP 出口）」

| 条目 | 状态 | 证据 | 缺口说明 |
| --- | --- | --- | --- |
| 部署域名核心 E2E：提问、阅读回答、反馈、导出 | 未验证 | 本地 `conversation.spec.ts`、历史 `real-api/analytics.spec.ts`；常规 E2E CLI exit 124。 | 无部署域名。 |
| 真实跨域 SSE 1 秒内出现首个阶段标签 | 未验证 | 本地 Mock 场景先显示 step；API 契约测试覆盖 SSE/JSON 等价。 | 无真实 CORS 网络与时限记录。 |
| 刷新后重新选回商家并恢复会话 | 未验证 | `conversation.spec.ts` 有刷新选回商家场景。 | 未经部署域名、真实后端会话恢复验收。 |
| 360px 和 1440px 均可用 | 未验证 | `responsive.spec.ts`；26/26 常规 E2E 断言输出 `ok`。 | CLI 未成功退出，且无线上双视口验收。 |
| P0 E2E 不依赖附件、日报和知识库 | 未验证 | F6 计划与前端计划定义了此范围，首屏/聊天 Mock 测试未启动 P1 服务。 | P0 核心线上 E2E 尚未执行，不能证明实际验收未依赖这些能力。 |

## 必须保留的未验证簇

1. **真实模型意图准确率 ≥90%**：PRD §16 要求人工验收。当前没有真实 DeepSeek 调用；两次计划中的线上聊天即使执行，也不能计算完整问题集准确率。
2. **PRD 完整业务覆盖**：四业务域、规则问答、连续追问、预算熔断与限流都缺少一套完整、当前可复跑的端到端验收，不能由少量示例或两次线上提问代替。
3. **R9 还原度审计未处理缺口**：`docs/yshopping-parity-audit.md` §3.1 指标口径字段、§3.2 三级检索中间层、§3.3 跨业务查询计划、§3.4 纯明细仅表格、§3.5 受控生成指标，以及 §3.6 思考过程只渲染最后一步均未完成。§3.6 是纯前端渲染缺口，归 `plans/2026-08-09-b7-f4-integration-and-r9-remediation.md` 阶段 B Task 8；它直接影响 PRD §16 的处理步骤展示。

## 结论

**前端 F0–F6 代码与文档已完成，Railway 部署就绪；Railway 尚未部署，MVP 尚未宣告完成。**

是否宣告 MVP 完成应由用户审阅本矩阵后决定；至少需要完成 Railway 控制台部署、两轮线上验收（第二轮真实模型调用须先按 R3 获得明确授权）并处理或明确裁定 R9 未处理缺口。
