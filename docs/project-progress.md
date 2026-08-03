# 项目进度快照

> 本文件只保留当前可继续开发的事实快照，不追加每日流水账。每次完成一段可验证工作后，更新日期、状态、验证结果、下一步和风险。

**最后更新：2026-08-03**

## 当前阶段

- 后端：B0–B2 已实现并完成收口整改，可进入 B3。
- 前端：F0 已验收；**F1 的代码、自动化验证和文档同步已完成**。1440×1000 的人工视觉比对因本地 Windows Computer Use helper 不可用而待补，不影响已通过的结构与几何验收。

## 已完成

- FastAPI 工程、演示商家身份、PostgreSQL 基础设施、会话与回答持久化；Chat JSON/SSE 双路径、幂等、跨商家审计和服务端推荐问题。
- 前端 F0：Vue 3 + TypeScript + Vite 工程、`/` 与 `/knowledge-base` 路由、OpenAPI Adapter、API 基础地址、全局错误区、Caddy 静态镜像与基础 E2E。
- 前端 F1：Borough 原创 logo、全局 Design Tokens 与基础样式、三栏主布局、桌面/平板/移动响应式、独立 `ChatComposer.vue`、`ConversationColumn.vue`、单实例 `MerchantSwitcher.vue` 和最小 Chat 重置状态。
- F1 复查整改：Enter 发送（Shift+Enter 换行并兼容输入法组合态）、顶层 `header` + 对话 `main` landmark、商家菜单外部点击/Escape 关闭与焦点归还、合法且实际切换商家才重置会话；附件控件在 F7 前明确禁用。
- F1 复查整改：实际应用间距、字号、控件和过渡 Design Tokens；小字号说明文本达到 WCAG AA 对比度；顶栏导航选择器改为专用类名，并补齐品牌图片固有尺寸与跳至对话主区的跳转链接。
- F1 商家列表仅为硬编码演示显示名，并明确由 F2 Auth Store 替换；未接入 Token、`merchant_id`、API、SSE、LLM 或附件能力。
- E2E 正式文件已落位为 `e2e/assistant.spec.ts` 与 `e2e/responsive.spec.ts`，原 `skeleton.spec.ts` 已迁移移除；目录规划已补入 `components/layout/`。

## 最近验证

- 2026-08-03：前端 `lint`、`format:check`、`typecheck`、生产 `build` 均通过。
- 2026-08-03：前端 Vitest **50 passed**；覆盖 Chat Adapter、配置、路由、主布局、商家切换器、对话列、输入区的键盘分支与附件禁用状态。
- 2026-08-03：Playwright **10 passed**；验证 1440px 三栏宽度、561px/580px 顶栏无溢出、390×844 输入可聚焦、360px 无横向滚动、减少动画偏好、小字 WCAG AA 对比度，以及路由与控制台错误。
- 说明：在当前 Codex Windows shell 中，Playwright 自启 Vite 后的子进程回收会使命令超时；复用受控本地 Vite 后，10 项 E2E 在 7.0 秒内通过并正常退出。未改动项目的 Playwright 配置。
- 本次未运行 `codegen:check`，以遵守 F1 当前任务“不得读取 `docs/api.json` 与 `src/api/generated.ts`”的约束。

## 下一步

1. 在本地浏览器 helper 可用时，补做 1440×1000 Borough 页面与只读 Prototype 的一次性人工视觉核对，并将结论回写本文件。
2. 前端 F2：接入 Auth Store、Mock 会话、聊天 Store 的完整状态与前端 Mock 闭环。
3. 后端 B3：实现指标目录、知识检索与结构化意图；首次真实 DeepSeek 调用前，必须取得用户对模型、调用次数和费用的明确同意。

## 风险与约束

- 未获明确同意不得调用真实 DeepSeek API、OCR 或日报生成；单元测试必须 mock LLM。
- 商家身份只能由 Bearer Token 解析；前端不得传递或信任 `merchant_id`。
- `yshopping-merchant-ai 4/` 与 `yshopping-prototype/` 只读；新代码与品牌资产必须使用 Borough。
- F1 尚待补充一次人工视觉比对；自动化几何、无障碍焦点和减少动画验收已通过。

## 关键入口

- `AGENTS.md`：项目规则、目录与开发顺序。
- `docs/PRD.md`：产品范围与验收标准。
- `docs/frontend-development-plan.md`：F0–F9 前端阶段计划。
- `docs/backend-development-plan.md`：后端阶段与 API/SSE 契约。
- `frontend/src/views/AssistantView.vue`：F1 三栏主页面。
- `frontend/e2e/assistant.spec.ts`、`frontend/e2e/responsive.spec.ts`：F1 E2E 验收。
