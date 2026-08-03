# 后端 B2：Chat API 与 Fake Agent 设计

## 目标

严格实现 `docs/backend-development-plan.md` 中 B2 定义的 P0 后端能力：以可信商家身份为边界，提供会话式 Chat API、SSE/JSON 双传输、幂等处理、预置推荐问题和可在 B3 被替换的 Fake Agent。自动化测试不访问网络或调用真实 LLM。

## 范围与边界

- 本阶段只修改 `backend/` 及必要的后端文档产物；不实现前端 F2。
- 不引入真实 LLM、LangGraph、指标/知识检索、经营数据查询、CSV 导出、反馈或 P1 功能。
- 复用 B1 的 Bearer Token Merchant Context、会话 Repository、商家隔离和审计能力；请求中任何 `merchant_id` 均不影响身份。
- 不改动只读参考项目 `yshopping-merchant-ai 4/`。

## 契约与传输

`POST /api/chat` 接收 `message`、可选 `session_id`、P0 固定为空的 `attachment_ids`、以及必填 `client_request_id`。默认返回 SSE；当 `Accept: application/json` 时返回普通 JSON。

SSE 只发送 `step`、`done`、`error` 三种事件。`step` 仅包含安全的 `{label, node}`；`done` 是完整 `ChatResponse`；流必须以 `done` 或 `error` 之一结束。JSON 路径的响应体与 `done` 载荷逐字段相同。响应头、空行分帧、15 秒心跳和流开始前/后的错误语义均遵守后端开发方案 §8.4。

`ChatResponse` 使用 §8.2 的扁平 snake_case 契约。始终存在的字段与按模式必填字段由 Pydantic 模型级校验区分：无数据模式不得被数据字段阻塞；`analysis_sources`、`degraded`、质量状态和建议问题必须遵守该节约束。

## 应用服务与持久化

Chat 应用服务是路由和 Fake Agent 的边界：它从已认证 Merchant Context 获取商家范围，创建或校验会话，保存用户消息，执行 Fake Agent，保存完整回答和助手消息，并将持久化回答转换为响应。

`answers` 表中既有 `(merchant_id, client_request_id)` 唯一约束和 `request_digest` 是幂等性唯一来源。处理行为完全遵守 §8.5：摘要不一致返回 `IDEMPOTENCY_KEY_REUSED`；处理中返回 `REQUEST_IN_PROGRESS`；成功时复用已保存回答；可重试失败复用记录后重新执行；终态失败返回原错误。正常的 `INVALID` 仍是成功的业务回答。

会话 API 提供列表、详情和删除。所有访问和删除必须按可信 `merchant_id` 过滤；已存在但属于其他商家的会话经 B1 MerchantScopeService 记录审计并返回跨商家错误。

## Fake Agent 与推荐问题

Fake Agent 支持 Prototype 预置场景，确定性地产出回答及逐节点步骤，满足前端在没有真实 LLM 时的完整交互。Fake 回答必须明确为降级结果，使用 `analysis_sources=["FALLBACK"]`、`degraded=true` 和可见降级原因，绝不声称来自数据库或模型。

推荐问题由服务端纯数据配置产生，并在每个聊天响应中附带当前三题及不重复的备选组；不请求模型、不额外发请求。配置按业务域组织，每域至少两组三题；`CHAT` 使用入门问题组。B3 的白名单完成后，推荐配置由其校验；B2 不提前复制 B3 白名单。

Fake Agent 是 B2 过渡实现；B3 建立真实 Graph 和 Fake LLM 后必须移除该路径，而不改变 API 或持久化契约。

## 测试与验收

使用 TDD。测试先验证失败，再最小实现使其通过。

- Schema：请求约束、按模式必填字段、来源和降级组合、质量尝试次数。
- API：认证、JSON/SSE 载荷一致、SSE 顺序/收尾/心跳、422、会话连续追问、列表/详情/删除、商家隔离。
- 幂等：摘要冲突、处理中、已成功、可重试失败、终态失败，以及并发重复提交仅执行一次。
- Fake Agent 与推荐问题：预置场景、步骤安全性、降级标记、业务域候选组、`CHAT` 入门组和备选去重。
- 集成测试仅使用真实 PostgreSQL；单元与 API 测试不访问网络和真实 LLM。

验收命令在 `backend/` 运行：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest`。OpenAPI 及其契约快照同步更新。
