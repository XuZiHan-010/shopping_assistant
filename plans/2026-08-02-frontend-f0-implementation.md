# 前端 F0 工程骨架实施计划

> **For agentic workers:** 按 Task 顺序执行，每个 Task 内按 Step 顺序。Step 用 `- [ ]` 跟踪。
> 每个 Task 结束前跑通该 Task 的验收命令，全绿才进入下一个 Task。

**Goal:** 建立 `frontend/` 工程骨架，使 F1–F6 能在稳定的 Vue 3 + TypeScript、OpenAPI 生成类型和部署边界上开发。

**Tech Stack:** Vue 3、TypeScript、Vite、Vue Router、Pinia、zod、Vitest、@vue/test-utils、happy-dom、Playwright、ESLint、Prettier、openapi-typescript、Caddy。

**权威依据：** `docs/frontend-development-plan.md` F0 清单（11 项）、§3.1/§3.2 依赖表、§4 目标目录、§5.0 Adapter 边界、§10 错误展示表、§11 禁止事项。

---

## 一、前置条件（已满足，开工前复核）

| 条件 | 状态 |
| --- | --- |
| `docs/api.json` 含完整错误契约（`ErrorResponse`/`ErrorCode`，每条路由声明 §8.0 错误码） | ✅ 2026-08-01 完成 |
| `docs/api.json` 声明 `/api/chat` 双传输（`application/json` + `text/event-stream`） | ✅ 2026-08-01 完成 |
| `ChatResponse.category` 已枚举化为 `QuestionCategory`（11 值） | ✅ 2026-08-01 完成 |
| 后端质量门禁全绿（209 passed, 0 skipped） | ✅ 2026-08-01 完成 |
| Node 工具链 | ✅ Node v24.14.0 / npm 11.9.0 |

**若 `docs/api.json` 与后端不同步，先在 `backend/` 跑 `uv run python ../scripts/export_openapi.py` 再开工。**

---

## 二、Global Constraints

- 面向用户的文案用中文；代码标识符用英文。
- **不手写任何 API 字段类型**，全部来自 `src/api/generated.ts`（§5.0）。
- 组件不得直接消费 `generated.ts`，也不得自行转换字段——只走 `src/api/adapters/`（§11）。
- 不创建 `/login` 路由或 `LoginView.vue`（属 P2）。
- 不把 Token 写入 `localStorage`；`.env.example` 只放占位符。
- F0 不实现三栏视觉、Borough logo、Mock 会话、SSE 解析器、Chat Store（F1–F3）。
- 不调用真实后端、不调用 LLM、不产生费用。
- 不执行 Git commit/push/tag/PR；当前目录不是 Git 仓库。

---

## 三、本计划已吸收的评审结论

2026-08-01 对一份早期 F0 设计草案做过评审，发现 2 项阻塞、2 项设计矛盾、3 项文档不一致和 6 项弱化。
那份草案与配套的整改清单已被本文件取代并删除；结论逐条落在下表对应的 Task 里，本文件是唯一现行方案：

| 编号 | 结论 | 落在 |
| --- | --- | --- |
| B1 | `generated.ts` 提交进仓库；Docker 构建不跑 codegen；增加 `codegen:check` | Task 3 |
| B2 | 完整 `ChatResponse` Adapter 放在 F0，不是 F3 | Task 4 |
| B3 | 契约测试用后端导出的真实 fixture，不用前端自造载荷 | Task 2、Task 4 |
| B4 | 删除 `VITE_API_BASE_URL` 的同源回退，缺失即报错 | Task 3 |
| B5 | 配置读取点放 `src/api/client.ts`，不新增 `src/config/` | Task 3 |
| B6 | 占位页直接用 `views/KnowledgeBaseView.vue` 最终文件名 | Task 5 |
| B7 | Caddy 选型写进 AGENTS.md 与前端方案 | Task 7 |
| B8 | zod 只守语义不变量，不复制字段形状 | Task 4 |
| B9 | `test:e2e` 必须是可通过的脚本，写真实 smoke | Task 6 |
| B10 | `/login` 不存在改为两条可执行断言 | Task 5 |
| B11 | 补齐 `happy-dom` 与 `zod` 依赖 | Task 1 |

---

## Task 1: 创建工程骨架与依赖

**Files:**
- Create: `frontend/package.json`、`frontend/vite.config.ts`、`frontend/tsconfig*.json`、`frontend/index.html`
- Create: `frontend/eslint.config.js`、`frontend/.prettierrc.json`、`frontend/.gitignore`

**Interfaces:** 产出可运行 `npm run lint`、`format:check`、`test`、`build` 的工程。

- [x] **Step 1: 初始化工程**

在仓库根目录执行，不要用交互式脚手架（`npm create vue@latest` 会提问，本环境无法交互）：

```
mkdir frontend
cd frontend
npm init -y
```

然后手写 `package.json`：`name` 固定为 `@borough/web`，`private: true`，`type: "module"`。

- [x] **Step 2: 安装依赖**

依赖集合必须与 `docs/frontend-development-plan.md` §3.1/§3.2 一致，不多不少：

```
npm i vue vue-router pinia echarts @lucide/vue zod
npm i -D typescript vite @vitejs/plugin-vue vue-tsc @types/node \
         vitest @vue/test-utils happy-dom \
         @playwright/test \
         eslint eslint-plugin-vue @vue/eslint-config-typescript \
         prettier openapi-typescript
```

三处与 §3.1/§3.2 原表的差异，均已同步回该表：

- `happy-dom` 与 `zod` 是原设计遗漏项（B11）：Router 测试要渲染组件，没有 DOM 环境跑不起来；
- **图标包用 `@lucide/vue` 而非 `lucide-vue-next`**——后者上游已废弃，安装时会打印
  `Package deprecated. Please use @lucide/vue instead`；
- `@types/node` 必须显式安装：`vite.config.ts` 用 `node:url`，`tsconfig.node.json` 又声明了
  `types: ["node"]`。它目前能从传递依赖里解析到，但依赖树一变就会以难懂的错误炸掉构建。

- [x] **Step 3: 写必须存在的脚本**

按 F0「必须存在的脚本」逐字提供，并补两条 codegen 脚本（B1）：

```json
{
  "dev": "vite",
  "build": "vue-tsc -b && vite build",
  "test": "vitest run",
  "test:e2e": "playwright test",
  "lint": "eslint .",
  "format:check": "prettier --check .",
  "codegen": "openapi-typescript ../docs/api.json -o src/api/generated.ts",
  "codegen:check": "node scripts/check-generated.mjs"
}
```

- [x] **Step 4: 配置 Vite、TypeScript 与测试环境**

`vite.config.ts` 配 `@vitejs/plugin-vue`、`@/` 别名指向 `src/`，以及 Vitest：

```ts
test: {
  environment: 'happy-dom',
  include: ['src/**/*.spec.ts'],
}
```

`tsconfig` 用 `tsconfig.json` + `tsconfig.app.json` + `tsconfig.node.json` 三件套（§4 目标目录要求），`strict: true`，路径别名与 Vite 对齐。

两个已踩过的坑：

- `defineConfig` 必须从 **`vitest/config`** 导入，Vite 自己的 `defineConfig` 不接受 `test` 字段，
  否则 `vue-tsc -b` 报 `TS2769: 'test' does not exist in type 'UserConfigExport'`；
- ESLint 配置用 **`eslint.config.js`** 而非 `.ts`。ESLint 9 加载 TypeScript 配置需要额外的
  `jiti` 依赖，而 §4 目标目录写的本来就是 `.js`。

- [x] **Step 5: 验收**

Run（在 `frontend/`）：`npm run lint && npm run format:check && npm run build`

Expected: 全部通过。此时还没有源文件，`build` 需要一个最小 `index.html` 与 `src/main.ts` 才能成功——本 Step 允许先创建它们的最小形态，Task 5 再补路由。

---

## Task 2: 导出后端 Chat Fixture

**Files:**
- Create: `scripts/export_chat_fixtures.py`
- Create: `docs/fixtures/chat/*.json`
- Create: `backend/tests/api/test_chat_fixtures.py`

**Interfaces:** 产出前端契约测试可直接消费的真实 `ChatResponse` 载荷。

**为什么需要这一步（B3）**：如果让前端自己按 `generated.ts` 的类型构造测试载荷，类型只能保证字段名，保证不了语义——前端可以合法造出 `answer_mode: "CHAT"` 配 `analysis_sources: ["DATABASE"]` 这种后端永远不会产生的组合，测试照样绿，等于自己批改自己的作业。

- [x] **Step 1: 写失败的 fixture 哨兵测试**

断言 `docs/fixtures/chat/` 下五个文件存在，且与当前 `FakeAgent` 的输出逐字节一致（比对方式与 `docs/api.json` 哨兵相同）。

- [x] **Step 2: 运行测试确认失败**

Run（在 `backend/`）：`uv run pytest tests/api/test_chat_fixtures.py -v`

- [x] **Step 3: 实现导出脚本**

覆盖 `FakeAgent` 的全部输出形态：

| 文件 | 触发问题 | 验证点 |
| --- | --- | --- |
| `metric-refund.json` | 最近7天退货量趋势 | METRIC 八字段 + visualization + recommendations + FALLBACK 降级 |
| `metric-gmv.json` | 昨天总 GMV 是多少？ | METRIC + TRADE 分类 |
| `metric-order-detail.json` | 查看最近订单明细 | `total_rows=327`、`truncated=true`、`export` 为 null |
| `rule-platform.json` | 我要货品上架，具体规则有吗？ | RULE 模式下按模式字段全部缺省 |
| `chat-greeting.json` | 你好 | CHAT + `["NONE"]` + `degraded=false` |
| `invalid-refused.json` | 帮我修改订单金额 | INVALID 拒绝语义 |

**必须处理确定性**：`ChatResponse.id` 来自 `uuid4()`、`created_at` 来自 `now()`，直接导出会让每次 diff 都不同，哨兵永远为红，最终必然被人加参数绕过。脚本须把这两个字段覆盖为确定性值（`id` 用命名空间 UUID5，`created_at` 用固定时间戳），并在脚本内注明原因。

- [x] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/api/test_chat_fixtures.py -v`

- [x] **Step 5: 后端全量回归**

Run（在 `backend/`）：`uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q`

Expected: 全绿，209 + 新增用例。

---

## Task 3: OpenAPI 类型生成与配置读取点

**Files:**
- Create: `frontend/src/api/generated.ts`（生成产物）
- Create: `frontend/scripts/check-generated.mjs`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/.env.example`、`frontend/.env.development`

- [x] **Step 1: 生成类型**

Run（在 `frontend/`）：`npm run codegen`

**`src/api/generated.ts` 必须提交进仓库**（B1）。原因：Railway 的 frontend service Root Directory 是 `/frontend`（AGENTS.md §十四），Docker 构建上下文里没有 `docs/`，构建期跑 `codegen` 会因找不到 `../docs/api.json` 而失败，且报错难以定位。因此构建期不生成，只消费已提交的产物。

在文件顶部保留 openapi-typescript 的生成注释，并在 `.eslintignore` / `prettier` 忽略列表中排除它。

- [x] **Step 2: 写漂移检查脚本**

`scripts/check-generated.mjs`：重新生成到临时文件，与提交版本逐字节比对，不一致时以非零码退出并提示重新运行 `npm run codegen`。纳入本地质量门禁与 CI，**不纳入 Docker 构建**。

- [x] **Step 3: 实现配置读取点**

`src/api/client.ts` F0 只负责一件事——导出 API 基础地址（B5，不新增 `src/config/`，§4 目录树没有该目录，AGENTS.md §7.5 把这个职责归给 `client.ts`）。F3 再在同一文件补 HTTP 客户端与鉴权头。

**不要提供同源 `/api` 回退**（B4）。Caddy 明确不代理 `/api`，AGENTS.md §十四 也定死了「Backend 公开 + 严格 CORS，不引入反向代理容器」。有回退时，生产漏配变量会让请求打到静态服务器上拿 404，表现成「接口坏了」而不是「配置漏了」。正确做法是缺失即抛出可展示的中文错误。

开发环境通过 `.env.development` 提供默认值指向本地后端；`.env.example` 只放占位符，不得含真实值（R6）。

- [x] **Step 4: 验收**

Run: `npm run codegen:check && npm run build`

Expected: 通过。手动改一行 `generated.ts` 后 `codegen:check` 必须失败。

---

## Task 4: ChatResponse Adapter 与契约测试

**Files:**
- Create: `frontend/src/types/chat.ts`
- Create: `frontend/src/api/adapters/chat.ts`
- Create: `frontend/src/api/adapters/chat.spec.ts`

**Interfaces:** `toChatAnswer(payload: components['schemas']['ChatResponse']): ChatAnswer`

**为什么是完整 Adapter 而不是最小版（B2）**：原设计把完整 Adapter 排在 F3，但 F2「Mock 会话闭环」在 F3 之前，且 F2 要渲染整轮回答（指标卡、图表、建议、质量轨迹）。§5.0 又禁止组件绕过 Adapter。所以完整 Adapter 的位置最晚是 F2，排在 F3 不成立。B2 契约已冻结，一次写完比分三次改同一文件更省事，也是对后端契约「是否真的可消费」的第一次真实检验。

- [x] **Step 1: 写失败的契约测试**

从 `docs/fixtures/chat/` 读取真实载荷（Vitest 配一个指向 `../docs/fixtures` 的别名），断言：

- snake_case → camelCase 转换正确；
- METRIC fixture 的 `metric_*` 八字段、`visualization`、`recommendations` 全部映射到位；
- RULE / CHAT / INVALID fixture 的按模式字段转换结果为 `undefined`，**不伪造默认值**（§5.0 明文要求）；
- `analysis_sources`、`degraded`、`degraded_reason`、`quality_*` 进入 `qualityTrace`；
- 空回答被拒绝并抛出中文错误。

- [x] **Step 2: 运行测试确认失败**

Run: `npm run test`

- [x] **Step 3: 实现领域类型与 Adapter**

`src/types/chat.ts` 定义领域模型（camelCase），覆盖 §5.1–§5.8。

`src/api/adapters/chat.ts` 是生成类型到领域模型的唯一转换点。用 zod **只守语义不变量，不复制字段形状**（B8，形状由 `generated.ts` 负责，复制一遍就成了第二套契约）：

- `answer_mode` 在枚举内；
- `analysis_sources` 非空数组；
- `CHAT` / `INVALID` 必须且只能是 `["NONE"]`，且 `degraded === false`；
- 含 `FALLBACK` 时 `degraded === true`；
- `METRIC` 必须带齐 `metric_*` 八字段与 `visualization`；
- `quality_attempts` 在 0–2。

违反时抛出可展示的中文错误。这组守卫同时能在 F2 挡住「Mock 造出后端不可能产生的组合」。

- [x] **Step 4: 运行测试确认通过**

Run: `npm run test`

Expected: PASS，且每条不变量各有一条断言其被拒绝的用例。

- [x] **Step 5: 静态检查**

Run: `npm run lint && npm run build`

---

## Task 5: 路由、App 骨架与全局错误提示

**Files:**
- Create: `frontend/src/main.ts`、`frontend/src/App.vue`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/views/AssistantView.vue`、`frontend/src/views/KnowledgeBaseView.vue`
- Create: `frontend/src/composables/useAppError.ts`
- Create: `frontend/src/router/index.spec.ts`

- [x] **Step 1: 写失败的路由测试**

按 B10 的可执行断言写（原验收「`/login` 未注册」在有兜底路由时无法证明——兜底会吃掉它，`router.resolve('/login')` 会匹配到 catch-all 而不是无匹配）：

1. `/` 与 `/knowledge-base` 能解析并渲染；
2. 路由表中不存在 `path` 或 `name` 含 `login` 的记录；
3. `router.resolve('/login')` 解析到兜底路由，而非某个专门的登录路由；
4. 仓库中不存在 `views/LoginView.vue`。

- [x] **Step 2: 运行测试确认失败**

Run: `npm run test`

- [x] **Step 3: 实现路由与骨架**

`views/KnowledgeBaseView.vue` **直接用最终文件名**（B6），内容为占位，F8 在同一文件填实现——原设计的 `KnowledgeBasePlaceholderView.vue` 到 F8 要么改路由要么留死文件。

`App.vue` 只承载 `<RouterView>` 和一个无障碍状态区域（`role="status"` / `aria-live="polite"`）用于展示全局错误。`useAppError.ts` 提供 `showError(message)`。

`main.ts` 注册 Pinia 与 Router。F0 不创建任何 Store。

- [x] **Step 4: 运行测试确认通过**

Run: `npm run test && npm run build`

- [x] **Step 5: 手动确认**

Run: `npm run dev`，确认 `/` 可打开、`/knowledge-base` 显示占位页且无控制台错误。

---

## Task 6: Playwright Smoke

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/skeleton.spec.ts`

- [x] **Step 1: 配置 Playwright**

`webServer` 指向 `npm run dev`，`baseURL` 用本地端口。浏览器二进制不纳入 F0 强制项，首次运行前执行 `npx playwright install chromium`。

- [x] **Step 2: 写真实 smoke**

访问 `/` 断言助手入口渲染；访问 `/knowledge-base` 断言占位页渲染且无控制台错误。

这不是「空白测试充数」——F0 确实有两条路由可断言。**不使用 `--pass-with-no-tests` 绕过**（B9），那等于承认脚本无意义，而 F0 清单要求 `test:e2e` 脚本必须存在。

- [x] **Step 3: 验收**

Run: `npx playwright install chromium && npm run test:e2e`

Expected: 通过，且至少一条用例有实际断言。

---

## Task 7: Docker 静态镜像与文档同步

**Files:**
- Create: `frontend/Dockerfile`、`frontend/Caddyfile`、`frontend/public/health.html`
- Modify: `AGENTS.md`、`docs/frontend-development-plan.md`、`docs/project-progress.md`

- [x] **Step 1: 实现镜像**

Node 多阶段构建执行 `npm ci && npm run build`，产物 `dist/` 复制进 Caddy 镜像。Caddy 提供静态文件、`/health.html`，非文件路由回退至 `index.html`。

**不代理 `/api`**：生产由 `VITE_API_BASE_URL` 指向公开后端，后端用严格 CORS。构建期不跑 `codegen`（B1）。

**`tsconfig.app.json` 必须 `exclude` 掉 `src/**/*.spec.ts`。** 契约测试引用仓库根的
`docs/fixtures`，而镜像构建上下文是 `/frontend`，看不到那个目录——留在应用工程里会让
`docker build` 以 `TS2307: Cannot find module '@fixtures/...'` 失败，而本地因为目录存在
完全察觉不到。测试的类型检查由 `tsconfig.vitest.json` + `npm run typecheck` 覆盖，该工程
**刻意不被 `tsconfig.json` 引用**，否则 `vue-tsc -b` 会在镜像里一并检查它，又回到同一个错误。

**Caddyfile 要给 `/api/*` 一个明确 404**，不能让它落进 SPA 回退。否则前端一旦误用同源
路径，会拿到 200 + `index.html`，然后在把 HTML 当 JSON 解析时报出一个跟根因毫无关系的错误。

- [x] **Step 2: 验证镜像**

```
docker build -t borough-web --build-arg VITE_API_BASE_URL=https://api.example.com ./frontend
docker run -d --name borough-web-test -p 8081:80 borough-web
```

逐项确认，只看构建成功是不够的：

| 请求 | 期望 |
| --- | --- |
| `/` 与 `/knowledge-base` | 200（SPA 回退生效） |
| `/health.html` | 200，内容为 `ok` |
| `/` 的 `Cache-Control` | `no-cache`（否则用户会拿旧 HTML 请求已删除的 chunk） |
| `/assets/*` 的 `Cache-Control` | `public, max-age=31536000, immutable` |
| `/api/health` | **404**，不是 200 + HTML |

- [x] **Step 3: 同步文档（B7 等）**

| 文档 | 更新内容 |
| --- | --- |
| `AGENTS.md` §十四 | 记录 Caddy 选型、镜像职责与「不代理 `/api`」约束 |
| `AGENTS.md` §七 | 确认 `frontend/` 目录索引与实际一致 |
| `docs/frontend-development-plan.md` §4 | 目录树补 `scripts/check-generated.mjs`；F0 清单补 `codegen:check` 与 fixture 消费 |
| `docs/frontend-development-plan.md` §3.2 | 确认依赖表与实际安装一致 |
| `docs/project-progress.md` | 更新日期、F0 状态与验证结果 |

- [x] **Step 4: F0 全量验收**

Run（在 `frontend/`）：

```
npm ci
npm run lint
npm run format:check
npm run codegen:check
npm run test
npm run build
npm run test:e2e
```

Expected: 全部通过。对照 `docs/frontend-development-plan.md` F0「验收」八条逐项确认。

---

## 四、本计划不做什么

- 不实现三栏主布局、Design Tokens 迁移、Borough logo（F1）；
- 不实现商家切换、认证请求头、Chat Store、SSE 解析器、Mock 会话（F2–F3）；
- 不实现图表、明细表、质量轨迹、反馈（F4–F5）；
- 不做 Railway 发布（F6）；
- 不改动后端契约——`docs/api.json` 在 F0 期间只读，如需变更须先改后端并重新导出；
- 不改动只读参考项目 `yshopping-merchant-ai 4/` 与 `yshopping-prototype/`；
- 不执行任何 Git 操作。
