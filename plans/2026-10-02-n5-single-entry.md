# N5 单入口演示实施计划（顾客视角按钮 + 快捷提问引导，D-N5-4）

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [x]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2），不调用真实 LLM（R3），不做任何 Railway 操作（Railway 变量在 `n5-budget-ops-and-railway` Task 5 落地）。

**目标：** 实现 2026-10-02 用户裁定 D-N5-4：线上对外只给商家端一个入口；商家端侧栏「顾客视角」在新标签页打开本商家的顾客端店铺页（2026-10-04 本地联调确认位置）；
顾客端首页快捷提问覆盖五个顾客 Skill 与一条规则问答，让只点一个链接的访问者也能体验顾客端 Agent。

**为什么：** Borough 用于求职演示，面试官通常只打开一个链接。两个独立 URL 会让顾客端被忽略；
顾客端若只有四条泛泛的提问，也看不出售后、规则引用、记忆这些能力。

**规格来源：** PRD M1（顾客视角入口）、C1（快捷提问引导）、§10.7（单入口演示）、§15 N5；契约 `docs/backend-development-plan.md`
§8.9.1 `MerchantSessionCreateResponse.shop_slug`（2026-10-02 增补）；`docs/frontend-development-plan.md` 第 18 条；`AGENTS.md` R5、§8.5。

**阶段归属：** N5 总览阶段 **E**（`plans/2026-09-27-n5-module-roadmap.md`）。纯本地、零费用，可与 A、B 并行；
**必须在 C Task 5 步骤 3（本地 compose 跑 S1–S8）之前完成**，D Task 7 演示脚本按单入口组织。

---

## 入口条件

- [x] PRD M1、C1、§10.7、§15 N5 与契约 §8.9.1 已按 D-N5-4 更新（2026-10-02 已完成，开工时复核仍一致）；
- [x] 核对实际代码：商家会话响应当前只有 `session_id / role / expires_at / merchant_display_name`
      （`backend/app/schemas/v2/merchant_session.py`）；`ShopSlug` 定义在 `app/schemas/v2/shop_session.py`；
      商家 `shop_slug` 即 `merchants.merchant_code`（`app/repositories/merchant.py::get_active_by_shop_slug`）；
      顾客端快捷提问为 `shop/src/views/HomeView.tsx` 的 4 个固定键 `home.quick1–4`。不一致时先改本计划。

---

## 全局约束

- 中文（R1）；不执行 Git 操作（R2）；不调用真实 LLM（R3）。
- **按钮只是链接**：不在 URL、查询参数、`postMessage` 或存储里传递商家会话 ID、演示 Token 或任何凭证；
  顾客端照常创建自己的访客会话（R5）。`target="_blank"` 必须配 `rel="noopener noreferrer"`。
- `shop_slug` 由后端从已验证商家会话解析，**不接受请求传入**，前端不拼接、不猜测。
- 顾客端地址来自构建变量 `VITE_SHOP_BASE_URL`；**缺失时不显示按钮**，不回退到同源或硬编码地址
  （与 `VITE_API_BASE_URL`「漏配必须响亮失败」同一思路，但这里是可选功能，缺失即隐藏）。
- 字段流向遵守 `AGENTS.md` §8.5：OpenAPI → `generated.ts` → Adapter → 类型 → Store → 组件；`generated.ts` 禁止手改。
- 快捷提问是固定文案，点击只发送该问题；**不为演示预置答案**，回答照常走工具循环与闸门。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/schemas/v2/common.py` | 承接 `ShopSlug` 约束（两端共享），`shop_session.py` 改为从此导入 |
| `backend/app/schemas/v2/merchant_session.py` | `MerchantSessionCreateResponse.shop_slug` |
| `backend/app/services/session_service.py`（以实际签发处为准） | 签发商家会话时填入该商家 `merchant_code` |
| `docs/api.json`、`docs/api.md`、`frontend/src/api/generated.ts`、`shop/src/api/generated.ts` | 导出与重新生成 |
| `frontend/src/api/adapters/session.ts`、`frontend/src/stores/auth.ts` | 映射 `shopSlug` 并保存在内存会话状态 |
| `frontend/src/components/shell/SideNav.vue` | 侧栏「顾客视角」按钮 |
| `frontend/.env.example`、`frontend/src/env.d.ts`（以实际类型声明文件为准） | `VITE_SHOP_BASE_URL` |
| `frontend/src/i18n/` | 按钮中英文案 |
| `shop/src/views/HomeView.tsx`、`shop/src/i18n/messages.ts` | 快捷提问扩充 |

---

### Task 1：契约字段落地（`shop_slug`）

- [x] **步骤 1：写失败测试**——Schema 单测：缺 `shop_slug` 或格式不符拒绝；`ShopSlug` 移入 `common.py` 后两端约束相同。
      API 测试：`POST /api/v2/merchant/sessions` 返回的 `shop_slug` 等于该演示商家的 `merchant_code`；
      请求体带 `shop_slug` 仍按 `extra="forbid"` 返回 422；OpenAPI 哨兵（`tests/api/v2/test_openapi_session_contract.py`）同步新字段
- [x] **步骤 2：实现 → 导出 OpenAPI**（`cd backend; uv run python ../scripts/export_openapi.py`）→ 两端 `npm run codegen` →
      `codegen:check` 通过
- [x] **步骤 3：Adapter 与 Store**——`session.ts` 映射 `shopSlug`，契约测试覆盖；`auth` Store 保存于内存（与会话 ID 同生命周期，
      不写 localStorage），切换商家时随会话一起替换

### Task 2：商家端「顾客视角」按钮

- [x] **步骤 1：写失败组件测试**：
      ① `VITE_SHOP_BASE_URL` 未配置时不渲染按钮；② 配置后 `href` 恰为 `${base}/${shopSlug}`（去除 base 尾斜杠），
      `target="_blank"`、`rel` 含 `noopener` 与 `noreferrer`；③ `href` 中不含会话 ID、演示 Token 或 `?`；
      ④ 中英文案随 `useLocaleStore()` 切换；⑤ 未登录（无会话）时不渲染
- [x] **步骤 2：实现**——放在顶栏右侧、偏好设置旁；移动端（375px）不造成横向溢出；`.env.example` 写占位
      `VITE_SHOP_BASE_URL=https://your-shop-host.example.com` 与说明
- [x] **步骤 3：Mock E2E 一例**（沿用 `e2e/support/v2MerchantMock.ts`）：登录后按钮可见、链接正确、新标签打开；
      `npm run test`、`typecheck`、`lint`、`build` 通过

### Task 3：顾客端快捷提问引导

- [x] **步骤 1：写失败测试**——快捷提问至少 6 条，逐条标注覆盖的能力：搜索发现、选购研究（对比）、目标规划（组合方案）、
      售后服务（退换货 / 订单状态）、记忆与个性化、平台规则问答（应给出引用）；中英键一一对应、无缺译；
      点击发送的正是该条文案；375px 无横向溢出
- [x] **步骤 2：实现**——文案用演示店铺**实际存在**的商品与规则（以 WS 替换后的演示商品为准，逐条核对种子数据），
      避免演示时得到「没有找到」；访客身份下需要已绑定身份的提问（如订单状态）要能得到「请先选择演示身份」的正常引导，
      而不是错误
- [x] **步骤 3：用脚本化 Fake LLM 跑一遍每条提问的工具路径**（确认会调用预期工具、闸门不误拒）；
      真实模型下的回答质量属 R3，不在本计划验证，D Task 4 统一处理。`shop` 单测、`tsc`、`eslint`、`build` 通过

### Task 4：自检与交接

- [x] 后端相关测试、`ruff check .`、`mypy app`；两端 `codegen:check`；`rg -n "session|token" frontend/src/layouts` 中新按钮附近无凭证拼接；
      把 `VITE_SHOP_BASE_URL` 交给 `n5-budget-ops-and-railway` Task 5（merchant 服务构建变量），并在 `docs/project-progress.md` 记录

---

## 本计划明确不做的事

| 不做 | 原因 |
| --- | --- |
| 顾客端反向跳回商家端 | 顾客端是公开站点，不展示商家端入口 |
| 单点登录 / 跨端共享会话 | 违反 R5：两类会话角色不可互换，按钮只是链接 |
| 把顾客端嵌进商家端（iframe） | 独立部署、独立 Origin 是 §10.7 的既定拓扑 |
| 为演示预置回答或缓存答案 | 违反 R7：不得把预置内容包装成模型分析 |

---

## 执行记录（2026-10-03）

12 步全部完成（Opus 单会话，Fake LLM，零费用）。证据与全部偏离裁定（`Ruling:`）见
`.superpowers/sdd/2026-10-02-n5-single-entry/progress.md`。与计划原文的三处差异：

1. **按钮位置**：W 重设计后桌面端没有顶栏，按钮放在侧栏账号区上方（偏好设置入口正上方），窄屏在侧栏抽屉里。
   PRD M1 仍写「顶栏」，待用户确认是否改措辞。
2. **访客身份说明**：实施时发现访客问本人订单会让模型拿猜的订单号调 `get_my_order`、整轮 403。新增
   `GUEST_SESSION_NOTE`（仅访客回合、接在稳定前缀之后；后端计划 §6.13 已补），归属闸门不变。
3. **规则问答文案**：顾客可见的规则文档只有「退货业务流程图」有实质内容，规则一条因此问退货退款流程。
