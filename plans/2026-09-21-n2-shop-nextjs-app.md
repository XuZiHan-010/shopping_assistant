# N2 Next.js 顾客端工程实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [x]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程本地 Fake LLM 后端，零费用。

**目标：** 在仓库根新建 `shop/`，用 Next.js + TypeScript 实现顾客端 C1–C5 最小集页面，
并跑通 **S1 浏览器 E2E**（PRD §12.2 要求 S1–S4 用 Fake LLM 浏览器 E2E）。

**架构：** 与商家端 Vue **共享 OpenAPI 类型、设计 token 与图标，不共享框架组件**
（`AGENTS.md` §七）。字段流同样单向：`OpenAPI → generated.ts → adapters → types → 状态 → 组件`。
浏览器直连 Backend（严格 CORS），**不引入反向代理，也不用 Next.js API Routes 做代理**
（`AGENTS.md` §十一「不引入反向代理容器」）。

**技术栈：** Next.js（App Router）、TypeScript、React Testing Library + Vitest、Playwright。

**规格来源：** PRD C1–C5、§7.5、S1；`AGENTS.md` §七、§8.3、§8.5、§十一；
契约计划 §8.7、§8.8、§8.10；视觉方向参考 `frontend/prototypes/borough-dual-end-prototype.html`
的顾客端部分（非规范性，只借鉴视觉）。

---

## 入口条件

- [x] `n2-trade-closed-loop` 已完成，`docs/api.json` 已导出全部 v2 顾客路由；
- [x] 会话计划已完成（含 Task 7 会话签发路由）：`POST /api/v2/shop/sessions`、`POST /api/v2/shop/sessions/demo-customer`、
      `DELETE /api/v2/shop/sessions/current` 可用且已在 `docs/api.json` 中；
- [x] **顾客端会话 Adapter 由本计划建**：会话计划 Task 7 只生成了商家端 `frontend/src/api/generated.ts`，`shop/` 的生成类型与
      会话 Adapter 在本计划建工程时从同一份 `docs/api.json` 生成；
- [x] `n2-trade-closed-loop` Task 2 已把 N1 的 `EmptyCartMerge` 换成真实购物车合并实现（否则下一条无法成立）；
- [x] **核对会话计划实际落地的绑定语义**：重新绑定同一演示身份时，服务端确实返回该身份已有的购物车。
      若实际实现不是这样，先改会话计划与本计划，不要在前端补偿。

---

## 已裁定：刷新后的购物车行为（2026-09-21 用户裁定，已写入 PRD C3）

会话凭证**只存浏览器内存**，不写 `localStorage` / `sessionStorage` / URL。

| 身份 | 刷新后 | 原购物车的真实状态 |
| --- | --- | --- |
| 未绑定访客 | 创建新访客会话 | **暂时无法访问，不是被删除**——服务端记录仍在，只是新会话关联不到它 |
| 已绑定演示顾客 | 创建新访客会话 | 重新绑定**同一**演示身份后，**恢复自己的购物车**（购物车按 `buyer_key` 存在服务端） |

**页面与测试都必须明确体现这一行为**（见 Task 2、Task 8），不能让它看起来像 bug：
页面上的提示文案要说"未绑定身份时刷新后无法找回购物车；绑定演示身份后可恢复"，
**不得写成"购物车已清空 / 已删除"**——那与服务端事实不符。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **会话 ID 不写 URL**（`AGENTS.md` §十一），不进日志与构建产物。
- **`shop/` 与 `frontend/` 零交集**：不得 import 对方文件，不得在对方目录里建文件。
- 库存**只显示三档**，不显示数量（D5）；结账与支付页**明确标注演示**（D13）。
- **金额只展示后端给的值**，前端不计算合计、不计算优惠（D13）。
- `NEXT_PUBLIC_API_BASE_URL` 漏配时**响亮失败**，不回退同源 `/api`——与商家端
  `src/api/client.ts` 的既有做法一致。

---

## 两个跨服务共享问题

Railway 的 `shop` 服务根目录是 `/shop`，**构建上下文里没有仓库根的 `docs/` 与 `frontend/`**。
因此"共享"不能靠构建时读取，只能靠**提交进仓库的同步副本 + 漂移检查**——
这正是商家端 `generated.ts` 已经在用的模式（`AGENTS.md` §十一）。

| 共享物 | 副本位置 | 来源 | 漂移检查 |
| --- | --- | --- | --- |
| OpenAPI 类型 | `shop/src/api/generated.ts` | `docs/api.json` | `npm run codegen:check` |
| 设计 token | `shop/src/styles/tokens.css` | `frontend/src/assets/tokens.css` | `npm run tokens:check` |
| 品牌 logo | `shop/public/borough-logo.svg` | `frontend/public/borough-logo.svg` | `npm run tokens:check` 一并比对 |

**镜像构建期不跑 codegen 与 token 同步**。两个 check 在本地与 CI 跑，保证提交的副本没过期。

顾客端在共享 token 之上**追加**自己的消费级 token（更大字阶、暖纸底、衬线标题），
写在 `shop/src/styles/shop-tokens.css`，**不修改共享副本**。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `shop/package.json`、`next.config.ts`、`tsconfig.json` | 工程骨架 |
| `shop/Dockerfile` | 独立镜像，监听 `PORT` |
| `shop/railway.json` | Railway 配置 |
| `shop/scripts/check-generated.mjs`、`check-tokens.mjs` | 漂移检查 |
| `shop/src/api/generated.ts` | codegen 产物，禁止手改 |
| `shop/src/api/client.ts` | base URL 解析，漏配响亮失败 |
| `shop/src/api/credentials.ts` | 内存会话 + `X-Session-Id` |
| `shop/src/api/adapters/*.ts` | wire → 领域模型 |
| `shop/src/api/sse.ts` | v2 事件解析（按字节流累积，不假设单次读取是完整事件） |
| `shop/src/styles/tokens.css` | 共享 token 副本 |
| `shop/src/styles/shop-tokens.css` | 顾客端追加 token |
| `shop/src/app/[shop_slug]/page.tsx` | 店铺页 |
| `shop/src/app/[shop_slug]/products/[product_id]/page.tsx` | 商品详情 |
| `shop/src/app/[shop_slug]/assistant/page.tsx` | 导购 Agent |
| `shop/src/app/[shop_slug]/cart/page.tsx` | 购物车与结账 |
| `shop/src/app/[shop_slug]/orders/[order_id]/page.tsx` | 订单与履约 |
| `shop/e2e/s1-presale-to-payment.spec.ts` | S1 浏览器 E2E |

---

### Task 1：工程骨架与两项漂移检查

- [x] **步骤 1：初始化 Next.js + TypeScript 工程**，严格模式开启
- [x] **步骤 2：写 `check-generated.mjs` 与 `check-tokens.mjs`**

两个脚本都做同一件事：**重新生成一份到临时位置，与提交的副本逐字节比对，不一致则退出码非零**。

```js
// check-tokens.mjs
const upstream = readFileSync('../frontend/src/assets/tokens.css', 'utf-8')
const copy = readFileSync('src/styles/tokens.css', 'utf-8')
if (normalize(upstream) !== normalize(copy)) {
  console.error('设计 token 副本已过期：运行 npm run tokens:sync')
  process.exit(1)
}
```

- [x] **步骤 3：验证检查真的会挡**——故意改坏副本一个字符，确认 check 失败；改回确认通过。
- [x] **步骤 4：`client.ts` 漏配测试**

```ts
it('NEXT_PUBLIC_API_BASE_URL 缺失时抛错，不回退同源', () => {
  expect(() => resolveApiBaseUrl(undefined)).toThrow(ApiConfigError)
})
```

---

### Task 2：会话与凭证

- 进入 `/{shop_slug}` 时调 `POST /api/v2/shop/sessions` 取得访客会话，**只存内存**（PRD C3，2026-09-21 用户裁定）；
- 选择演示顾客 → `POST /sessions/demo-customer` 原地绑定（会话计划已定义为保留原凭证的幂等绑定）；
  响应 `cart_adjusted=true` 时提示“部分商品因售罄或数量上限已调整”，并重新拉取购物车（PRD C3，E9）；
- 换身份须先 `DELETE /sessions/current` 再新建（D7⑥：已绑定顾客的购物车不得切换归属）；
- 演示顾客身份入口**只在演示模式开放**（D7④），界面标注"演示身份，非真实登录"。

- [x] **步骤 1：写失败测试**

```ts
it('会话 ID 不进入 URL', async () => {
  await openShop('borough-100')
  expect(window.location.href).not.toContain(sessionIdForTest())
})

it('会话 ID 不落持久化存储（PRD C3 裁定）', async () => {
  await openShop('borough-100')
  const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })
  expect(dump).not.toContain(sessionIdForTest())
})

it('已绑定顾客换身份前先注销当前会话', async () => {
  await bindDemoCustomer('alice'); await switchDemoCustomer('bob')
  expect(api.deleteCurrentSession).toHaveBeenCalled()
})

it('未绑定访客的购物车页明示刷新后无法找回，且不说"已删除"', () => {
  render(<CartPage session={guestSession()} items={[]} />)
  expect(screen.getByText(/未绑定身份时刷新后无法找回购物车/)).toBeInTheDocument()
  expect(screen.getByText(/绑定演示身份后可恢复/)).toBeInTheDocument()
  expect(screen.queryByText(/已删除|已清空/)).toBeNull()
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 3：店铺页与商品详情（C1）

**公开页面可以服务端渲染**（无鉴权，利于首屏）；需会话的页面一律客户端渲染。

- 库存只渲染三档 `有货 / 紧张 / 售罄`；
- 只显示**已生效**的券；
- 商品属性缺失时显示"商家未提供"，**不留空、不隐藏该行**——这是顾客能看见
  "Agent 为什么说不知道"的依据；
- 双语：翻译不可用时明确回退源文并标注，**不把机器译文冒充商家原文**（C9）。

- [x] **步骤 1：写失败测试**

```ts
it('商品卡片不渲染任何库存数量', () => {
  render(<ProductCard product={withStockTier('LOW')} />)
  expect(screen.queryByText(/\d+\s*件/)).toBeNull()
  expect(screen.getByText('紧张')).toBeInTheDocument()
})

it('缺失属性显示「商家未提供」而不是空行', () => {
  render(<AttributeTable attrs={[{ key: '产地', value: null }]} />)
  expect(screen.getByText('商家未提供')).toBeInTheDocument()
})

it('机器译文带标注', () => {
  render(<ProductDetail product={withTranslation({ machine: true })} locale="en-US" />)
  expect(screen.getByText(/machine translated/i)).toBeInTheDocument()
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 4：导购 Agent（C2 最小集）

- SSE 事件集与商家端相同（契约计划 §8.7.5）；**按字节流累积解析**，
  不假设一次读取对应一个完整事件（`docs/backend-development-plan.md` §8.4 线协议）；
- `tool_call` / `tool_result` 显示工具名、状态、耗时、行数，**不显示参数或结果**；
- Agent 加购后，购物车角标实时更新——购物车状态以**服务端 `GET /cart` 为准**，
  不从 SSE 文本里解析；
- 结账摘要**仅供展示**，页面标注"以结账页计算为准"。

- [x] **步骤 1：写失败测试**

```ts
it('SSE 在 UTF-8 多字节字符中间被切开时仍能正确解析', async () => {
  const bytes = encode('event: turn_complete\ndata: {"answer":"本店有 2 款"}\n\n')
  const chunks = splitAt(bytes, [7, 23, 41])          // 刻意切在中文字符中间
  const events = await collect(parseSse(streamOf(chunks)))
  expect(events.at(-1)?.payload.answer).toBe('本店有 2 款')
})

it('购物车角标来自 GET /cart，而不是解析回答文本', async () => {
  await sendMessage('帮我加一个')
  expect(api.getCart).toHaveBeenCalled()
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 5：购物车与结账（C3、C4）

- 提交订单时生成 `client_request_id`，**网络重试复用同一个**；
- **不可用项（库存不足、下架、券过期）逐项列出**，不静默移除（D13）；
- 金额**全部来自后端响应**，前端不做任何加减乘除；
- 支付页顶部常驻"演示支付，不产生真实扣款"；
- 30 分钟未支付：订单页显示已关闭，库存已释放（后端事实），前端不自行计时判定。

- [x] **步骤 1：写失败测试**

```ts
it('前端不计算订单合计', () => {
  const src = readFileSync('src/app/[shop_slug]/cart/page.tsx', 'utf-8')
  expect(src).not.toMatch(/reduce\([^)]*price/)
})

it('不可用项逐项展示且不从请求中静默移除', async () => {
  api.submitOrder.mockRejectedValueOnce(apiError('INSUFFICIENT_STOCK', 409,
    { unavailable: [{ product_id: P2 }] }))
  await clickSubmit()
  expect(screen.getByText(/库存不足/)).toBeInTheDocument()
  expect(cartItems()).toContain(P2)                 // 仍在购物车里，由顾客决定
})

it('网络重试复用同一 client_request_id', async () => {
  api.submitOrder.mockRejectedValueOnce(networkError()).mockResolvedValueOnce(order())
  await clickSubmit()
  const ids = api.submitOrder.mock.calls.map((c) => c[0].clientRequestId)
  expect(new Set(ids).size).toBe(1)
})
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 6：订单与履约（C5）

- 支付、履约、售后**三个状态分开展示**（D14⑥），不合成一个"订单状态"；
- 事件时间按查看者时区换算，同时可查看来源时区（D14⑩）；
- 本版无物流公司与运单号，**不显示占位的假单号**。

- [x] **步骤 1：写失败测试**——三维状态各自渲染；无运单号字段时不出现"运单号"文案。
- [x] **步骤 2：确认失败 → 实现 → 确认通过**

---

### Task 7：部署配置

- `shop/Dockerfile`：Node 多阶段构建，监听 Railway 注入的 `PORT`；
- `shop/railway.json`：Root Directory `/shop`；
- Backend 的 CORS 允许 Origin 追加 `shop` 的精确域名（**不使用 `*`**，`AGENTS.md` §十一）；
- 更新 `docs/deployment.md` 的「目标服务拓扑」节。

**本计划只写配置，不执行部署**——Railway 控制台操作属于 `n5-budget-ops-and-railway`。

- [x] **步骤 1：本地构建镜像并启动**，确认监听 `PORT` 且健康
- [x] **步骤 2：确认镜像构建过程不读取 `../docs` 或 `../frontend`**

```powershell
cd shop; docker build --no-cache . 2>&1 | Select-String "docs/|frontend/"
```

期望：无命中。命中说明构建期在跨目录读取，Railway 上会失败。

---

### Task 8：S1 浏览器 E2E

**文件：** `shop/e2e/s1-presale-to-payment.spec.ts`

```text
进入店铺 → 选择演示顾客 → 向导购提问 → Agent 对比两款商品
→ 加购 → 购物车页提交订单 → 支付页模拟支付 → 订单页显示「已支付」
```

后端用本地 Fake LLM，**子进程管理参照商家端 `frontend/scripts/e2e-process.mjs`**，
不用 Playwright 自带 `webServer`。

- [x] **步骤 1：编排 E2E**
- [x] **步骤 2：补三条刷新与越权用例**：
      ① 未绑定访客加购 → 刷新 → 页面显示空购物车**且显示"未绑定身份时刷新后无法找回购物车"的提示**；
      同时断言**服务端原购物车记录仍然存在**（证明是无法访问，不是删除）；
      ② 已绑定演示顾客加购 → 刷新 → 重新绑定同一身份 → **原购物车商品恢复**；
      ③ 直接访问他人订单 URL，显示与"不存在"一致的页面

---

### Task 9：自检

```powershell
cd shop
npm run codegen:check
npm run tokens:check
npm run lint
npm run typecheck
npm run test
npm run test:e2e
```

```powershell
cd "d:/vscode html/merchant_assistant"
rg -n "from ['\"]\.\./\.\./frontend|from ['\"]@borough/web" shop/src/
rg -n "localStorage|sessionStorage" shop/src/ --glob '!*.test.*'
```

第一条期望零命中（`shop/` 不 import 商家端代码）；第二条逐条确认没有存凭证。

更新 `docs/project-progress.md` 与 `docs/project-navigation.md`（新增 `shop/` 目录索引）。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 售后页、记忆页 | `n3-customer-skills-and-after-sales`、`n4-memory-pipeline` |
| 5 个 Skill 的完整导购体验 | `n3-customer-skills-and-after-sales` |
| Railway 实际部署 | `n5-budget-ops-and-railway` |
| 真实用户登录 | 不在本版范围（D7④） |

---

## 执行记录（2026-09-24，内联执行，未做 Git 提交）

入口条件已逐条对照代码核实：`docs/api.json` 含全部 v2 顾客路由；`EmptyCartMerge` 仅剩测试替身
（`session_deps.py`），绑定走 `merge_guest_into_buyer`，重新绑定同一 `buyer_key` 返回其原购物车（S1 E2E 刷新②实证）。

**裁定 / 与计划的偏差**

| 项 | 处理 |
| --- | --- |
| C9「机器译文」标注（Task 3 第三条测试） | **2026-09-24 补齐**：商品列表/详情按 `Accept-Language` 读取本商家既有机器译文缓存；响应携带源语言、版本与逐字段 `SOURCE / MACHINE / FALLBACK`，商品卡片、详情、属性均显示机器译文或源文回退提示；店铺/商品浏览文案支持中英切换。公开 GET 不调用真实 LLM，缓存缺失时明确回退源文；`source: DEMO` 仍独立标注「演示数据」 |
| Task 2「alice → bob」 | 演示身份是服务端按 `shop_slug` 固定映射的单一 `buyer_key`，绑定请求无身份参数；界面只有一个「绑定演示顾客」，换身份 = `DELETE /sessions/current` 再新建访客 |
| Task 4 工具行「耗时、行数」 | `ToolCallDisplay` 只有工具名、状态、摘要；按实际字段展示 |
| 支付页 | 计划文件清单无独立支付页：支付面板放在订单页（待支付时显示，常驻「演示支付，不产生真实扣款」） |
| 公开数据读取 | 单独 `catalogApi.ts`（不碰会话凭证）——服务端组件共享模块级凭证会混淆不同访客 |
| `NetworkError` 重试 | 提交订单在同一次点击内最多自动重试 2 次，全部复用同一 `client_request_id` |
| 后端 | 新增可选 `SHOP_ORIGIN`（CORS 精确 Origin，禁 `*`/路径/凭据）；新增 S1 E2E 后端入口 `backend/tests/support/e2e_s1_app.py` 与 `backend/scripts/seed_s1_e2e.py` |
| CI | `.github/workflows/n1-checks.yml` 新增 `shop` job（codegen/tokens/lint/typecheck/test，不含需数据库的 E2E） |

**E2E 暴露并修复的真实缺陷**：后端只在 `turn_complete` 里给 `tool_calls`（无逐条流式事件）时，工具行不显示——已补单测后修复。

**验证**：`shop/` 单元 67 passed；`codegen:check`、`tokens:check`、`eslint`、`tsc --noEmit` 通过；`next build` 通过；
`npm run test:e2e` 4 passed；镜像 `docker build --no-cache` 成功且无跨目录读取。
