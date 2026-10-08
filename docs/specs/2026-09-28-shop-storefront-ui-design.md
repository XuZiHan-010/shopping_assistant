# 顾客端店面 UI 重设计（定稿）与迁移方案

- 日期：2026-09-28
- 状态：
  - **视觉与布局已由用户定稿**（第二版原型，含“店员”改名“智能助手”）；
  - 2026-09-28 用户审阅本规格，采纳三项建议：§3.5 第一期补只读订单工具 `get_my_order`；§2.2 规则摘要与优惠券放进「全部商品」展开区；§2.5「申请售后」跳转现有售后页；
  - §3.4 的 PRD 与契约改动由实施计划第一步执行；
  - 实施计划为 `plans/2026-09-28-shop-storefront-redesign.md`；2026-09-29 已开工，当前进度见 `docs/project-progress.md`。
- 定稿原型：`frontend/prototypes/borough-shop-redesign.html`（第二版）
- 结构参照：Anthropic retail `storefront-web`（`vendor/anthropic-commerce-agents/examples/retail/storefront-web/`，只读参考，不复制代码）
- 适用范围：顾客端 Next.js 应用 `shop/`，以及它依赖的少量后端契约与演示数据。商家端见 `2026-09-28-merchant-workbench-ui-design.md`

## 一、裁定

2026-09-28，用户对照 ACME 本地演示后裁定：

| 事项 | 裁定 |
| --- | --- |
| 整体结构 | 直接对齐 Anthropic `storefront-web`：顶栏视图切换 + 主区 + 底部常驻输入框 + 右侧常驻购物车 |
| 配色与字体 | 保留 Borough「市集大厅」，与商家端定稿一致 |
| 实现方式 | 方案 A：在 `shop/` 现有 Next.js + 纯 CSS 上按原型重写外壳，不复制 ACME 的 `web-shared` 组件、不引入 Tailwind |
| 分期 | **第一期**：外壳、首页、购物车侧栏、订单视图、动态抽屉、偏好设置、商品名与图片。**第二期**另写规格：对话内嵌商品卡、对比表、加购确认卡 |
| 首页“热门” | 后端按近 30 天销量排序，不用目录顺序冒充 |
| 演示商品 | 保留五个类目，24 件换成真实商品名、简介、属性与价格 |
| 商品图片 | 用户用外部 AI 工具生成，按 §4.3 规格放进仓库，随镜像部署 |
| 命名 | 助手统一叫“智能助手”（英文 Assistant），不叫“店员” |
| 设置入口 | 2026-10-04 用户裁定：齿轮从左下角悬浮按钮移到顶栏右上角（身份按钮右侧）。做 Borough 自己的偏好设置（主题 / 语言 / 字号）。ACME 演示左下角的 “N” 是 Next.js 开发工具，不照搬 |

原第一版顾客端原型（店铺刊物式布局）作废，文件已被第二版覆盖。

## 二、定稿要点

### 2.1 外壳

- **顶栏**：Borough 商标与店名 · 视图切换「智能助手 / 订单」· 「动态」按钮 · 身份。
  - 「订单」上的数字角标只统计**待付款**订单，用警示色。
  - 身份按钮打开小菜单：访客显示「绑定演示顾客」，已绑定显示「退出演示身份」，并注明“演示身份，非真实登录”。
- **右侧购物车**：宽度 400px，宽屏常驻；窗口宽度 ≤1180px 时收进顶栏按钮，点开为抽屉。
- **底部输入框**：主区底部常驻，所有视图可用。在订单视图提问时自动切回智能助手视图。输入框下方一行演示声明。
- **顶栏右上角齿轮**（2026-10-04 起，原为左下角悬浮）：偏好设置，含主题（跟随系统 / 浅色 / 深色）、语言（中文 / English）、界面字号（小 / 标准 / 大）。
- 断点：1180px 购物车改抽屉；760px 首页单列、热门两列、顶栏只留图标；420px 视图标签只留图标。**375px 宽度无横向滚动**（§12.4）。

### 2.2 智能助手视图：首页（尚未提问时）

自上而下：

1. **日期与问候**：衬线大字“晚上好，欢迎回来”。按本机时间分早上 / 下午 / 晚上；访客不加“欢迎回来”。**不显示顾客姓名**，系统里没有这个字段。
2. **一句话订单概况**：如“4 单进行中，1 单今天派送中。**1 单待付款。**”，待付款部分用警示色。访客改为引导绑定的说明。
3. **四张快捷提问卡**：2×2 排列，文案见原型。点击后作为普通消息发给智能助手，不带任何隐藏参数。
4. **进行中的订单**：
   - 最多显示 3 单，排序为派送中 → 待付款 → 运输中 → 已发货 → 待发货；
   - 每行显示首件商品图、商品名（“等 N 件”）、状态标签、最近更新时间或支付截止时间；
   - 待付款的行按钮是「去支付」（进入订单详情），其余是「问问」（向智能助手提问该订单）；
   - 右上角「全部订单」切到订单视图；
   - 访客显示“绑定演示顾客后，这里会显示你的订单”及绑定按钮，不请求订单接口。
5. **本周热门**：近 30 天销量前 8 件，四列方图。每个方块显示商品图、名称、价格，库存非“有货”时加档位标签。点开是商品详情浮层。
   - 右上角「全部商品」原地展开为全部在售商品。展开后区块头部显示**店铺规则摘要与已生效优惠券**，满足 C1“店铺页展示本店在售商品、已生效优惠券、店铺规则摘要”。这是对原型的补充，原型里没有这一条。

### 2.3 智能助手视图：对话（提问之后）

- 主区换成对话，头部有标题、「对话记录」「新对话」两个按钮。
- 顾客消息为右侧浅底气泡。智能助手消息左侧放砖红星标头像和“Borough 智能助手”名称：
  - 名称旁有“查了 N 步”，可展开工具步骤。步骤只显示工具的显示名、状态和摘要，参数与结果不出现（契约 §8.7.5 脱敏）；
  - 回答正文按纯文本渲染；
  - 降级时正文下方显示警示色提示，写明原因（R7）；
  - 最后一条回答下方显示“猜你想问”按钮。
- 第一期**不渲染卡片**。回答里提到的商品只是文字；加购后以右侧购物车为准，每轮结束后刷新（沿用现有做法）。
- 对话状态提到外壳层（`[shop_slug]/layout` 下的 Provider）。切到订单视图再切回来，对话不丢。

### 2.4 「动态」抽屉

右侧抽屉，三个页签：

| 页签 | 内容 | 来源 |
| --- | --- | --- |
| 本轮过程 | 可前后翻看每一轮：问题原文、工具步骤（显示名 + 状态 + 摘要 + 内部工具名小字）、分析来源、降级原因、客户端测得的用时 | 各轮 `ChatTurn`；用时由前端从发送到 `turn_complete` 计时，只作展示 |
| 我记住的 | 记忆开关、记忆列表、逐条删除；访客显示绑定提示 | 迁入现有 `MemoriesClient` 逻辑与 `memoryApi`，关闭前的确认与清空规则不变（C7） |
| 对话记录 | 「新对话」按钮、当前对话、历史对话；可打开、删除 | 迁入现有 `ConversationDirectory` 逻辑，新建 / 浏览 / 跳转 / 删除全部保留（§12.4） |

原型里关闭记忆用的是浏览器 `confirm()`。实施时沿用 `MemoriesClient` 现有的页内确认。

### 2.5 订单视图

- 分三组：进行中 / 已完成（含已关闭）/ 我的售后。
- 订单行点击后原地展开详情：
  - 左栏是商品明细与实付（价格快照）；
  - 右栏是物流时间线（履约事件）；
  - 下方是操作：待付款显示「去支付」「取消订单」；已签收且无进行中售后显示「申请售后」；所有订单都有「问问智能助手」。
- **「申请售后」跳转到现有售后流程页**（`/{shop}/after-sales?order=…`，换新外壳样式），不采用原型里的内嵌表单。原因是 C8 要求提交前预览随单摘要，C6 要求补充信息，这两项现有页面都已实现，内嵌表单都没有。
- 「我的售后」行点击进入对应售后详情。

### 2.6 商品详情浮层

- 左边是方图，右边依次是：类目与编号、名称、价格与库存档位、短描述、「加入购物车」「问问智能助手」、属性表、详细描述。
- 缺失的属性显示「店家暂未提供 · 问问智能助手」。点“问问”向智能助手提问该属性，由后端工具生成内容缺口信号（C2、§12.4）。
  哪些属性算缺失由后端按类目必填表（`content_completeness.REQUIRED_ATTRIBUTES_BY_CATEGORY`）确定性给出，见 §3.3；前端不自己判断，因为顾客端响应里没有类目字段。
- 机器译文和缺译回退的标注（`TranslationNote`）在方块、浮层、购物车里都保留（C9）。
- 直接访问 `/{shop}/products/{id}` 仍是服务端渲染的完整页，内容与浮层相同，供分享和首屏使用。

### 2.7 购物车

- 每行：商品图、名称、行金额、单价、档位、数量步进器、移除。
- 底部：优惠券选择（只选，不在前端算优惠）、小计、“优惠与应付以提交订单后系统计算为准”、演示结账说明、「提交订单」。
- 访客：提交按钮禁用，旁边给绑定入口；并**明示“未绑定时刷新后无法找回购物车”**（C3 刷新行为）。
- 绑定时 `cart_adjusted=true` 必须提示“部分商品因售罄或数量上限已调整”（C3）。
- 下单被拒时，逐项列出不可用商品（沿用 `CartView` 现有逻辑）。成功后切到订单视图并展开新订单。

### 2.8 视觉 token

与商家端定稿同一套色板（`--ground #f6f1e7`、`--card #fffdf8`、铸铁绿 `--iron #1f3b2f`、金 `--gilt #c39a3a`、砖红 `--accent #b5502f`），深色模式写两份（`data-theme="dark"` 与 `system` 下的 `prefers-color-scheme`），字号档 `--scale` 取 0.92 / 1 / 1.1，叠纸面颗粒。顾客端专有的只有：

- 选中视图标签用铸铁绿实底、金色图标；
- 五个类目的占位图底色（`--t-dress` 等），只在图片加载前或无图时出现。

## 三、迁移

### 3.1 可以直接复用

- 原型的 CSS 基本原样拆进 `shop/src/app/globals.css` 与组件样式。原型里的后代选择器迁移时改成 class。
- 商标 SVG 与商家端提案一致。替换 `borough-logo.svg` 仍按商家端规格，另行确认。
- 字体：原型走 Google Fonts。实施改用 `next/font` 自托管 Fraunces、Instrument Sans、Noto Serif SC、Noto Sans SC 子集，并设 `display: swap`。

### 3.2 按原型重写外壳（逻辑已有）

| 原型部分 | 现有代码 | 做法 |
| --- | --- | --- |
| 顶栏 + 视图切换 + 身份菜单 | `session/ShopShell.tsx` | 重写外壳。会话开启、绑定、退出、`cart_adjusted` 提示逻辑保留 |
| 购物车侧栏 | `components/CartView.tsx`、`cart/CartClient.tsx` | 改为外壳常驻面板；金额只格式化后端值，不求和、不算优惠（沿用现有注释约束） |
| 首页 | `app/[shop_slug]/page.tsx`（店铺页） | 改为智能助手视图首页，数据见 §3.3 |
| 对话 | `assistant/AssistantClient.tsx` | 聊天状态上移到外壳 Provider；消息渲染按 §2.3 |
| 动态抽屉 | `ConversationDirectory.tsx`、`MemoriesClient.tsx` | 两者迁入抽屉页签；新增“本轮过程”页签 |
| 订单视图 | `orders/[order_id]/OrderClient.tsx`、`components/OrderView.tsx` | 新建订单列表视图，详情原地展开；支付、取消的幂等键逻辑保留 |
| 售后 | `after-sales/AfterSalesClient.tsx` | 只换外壳样式，流程不变 |
| 商品详情 | `products/[product_id]/page.tsx` | 抽出共用详情组件，页面与浮层共用 |
| 偏好设置 | 无 | 新建。语言写 cookie（`shop_locale`，非敏感），服务端渲染与所有客户端请求据此设 `Accept-Language`；没有 cookie 的首访一律中文，不按浏览器语言协商（2026-10-04 用户裁定，与商家端一致）。主题、字号存 localStorage，读写包 try/catch；布局头部内联脚本先设 `data-theme` / `data-size`，避免闪烁 |
| 双语文案 | 各组件内联 `locale === 'en-US' ? … : …` | 新建 `shop/src/i18n/` 两份字典，组件不再内联中英对。工具显示名在字典里维护映射，未知工具名回退原名 |

**路由调整：**

| 路径 | 调整后 |
| --- | --- |
| `/{shop}` | 智能助手视图（首页 / 对话） |
| `/{shop}/orders` | 新增，订单视图 |
| `/{shop}/orders/{id}` | 订单视图，并展开该订单 |
| `/{shop}/after-sales` | 保留，换样式 |
| `/{shop}/products/{id}` | 保留，完整页 |
| `/{shop}/assistant` | 重定向到 `/{shop}` |
| `/{shop}/cart` | 重定向到 `/{shop}`。窄屏时自动打开购物车抽屉 |
| `/{shop}/memories` | 重定向到 `/{shop}`，并打开动态抽屉的「我记住的」 |

会话 ID 仍只存内存、不写 URL（AGENTS.md §十一）。重定向只带视图参数。

### 3.3 原型需要、现有接口没有的部分

| 原型部分 | 缺口 | 处置 |
| --- | --- | --- |
| 本周热门 | 商品列表只能按 `created_at DESC` 分页 | `GET /api/v2/shop/stores/{shop_slug}/products` 增加查询参数 `sort: newest / popular`，默认 `newest`，现有行为不变。`popular` 按近 30 个业务日**已支付件数**降序，并列按 `created_at DESC, id DESC`。数据源与商家端经营指标相同的已支付订单明细，计划阶段核对具体表。响应**不返回销量数字**，只给顺序。签名游标额外绑定 `sort` |
| 首页和订单列表每行的商品图与名称 | `OrderSummary` 只有状态、金额、件数、时间 | `OrderSummary` 增加 `lead_item: {product_id, name, image_url或null}`（按订单明细顺序取首行，名称取价格快照）与 `last_event_at: UTC datetime`（最新履约事件时间）。只增字段，仍按 `merchant_id + buyer_key` 双重过滤 |
| 概况句与角标 | 无 | 前端按订单列表首页（`limit=20`）计数，属于展示层计数，不是经营指标。演示顾客订单数远小于 20，计划中注明这一前提 |
| 用时 | `ChatTurn` 无耗时字段 | 前端计时，只作展示，不新增字段 |
| 商品浮层的缺失属性行 | 顾客端商品详情没有类目，前端无从知道缺哪项 | `ProductDetailResponse` 增加 `missing_attributes: string[]`（0–20 项）：该类目必填属性里属性表缺失或为空的**源属性名**，按名称排序。前端用固定词表显示英文（产地 / 材质 / 尺码 / 保质期），未登记的名称原样显示。不改商家端的内容完整度计算。（2026-09-28 写计划时发现，补入） |

**不得用写死的示意数字或文案冒充真实数据（R7）。** 原型里的订单、记忆、对话记录都是示意。

### 3.4 需要同步的 PRD 与契约（按 AGENTS.md「先 PRD → 再契约 → 再计划 → 最后索引」）

| 文档 | 改动 |
| --- | --- |
| PRD C1 | 店铺页形态改为：智能助手首页 + 「全部商品」展开区，展开区显示规则摘要与优惠券；首页热门按近 30 天销量 |
| PRD C2 | 助手对外名称统一为“智能助手”；新增只读订单查询工具（见 §3.5） |
| PRD §11.2.2 | 路径不变。商品列表语义补 `sort`；订单列表语义补 `lead_item` / `last_event_at` |
| PRD §8.3 | 演示目录改为 §4.1 的真实商品，保留刻意缺口（2026-10-04 起为两个，#06 已补图），图片路径改 `.webp` |
| PRD §15 | 新增阶段「WS · 顾客端店面重设计」，位置见 §5 |
| 契约 §8.8.2 | 商品列表 `sort` 参数、排序规则、游标绑定 |
| 契约 §8.8.1 | `ProductDetailResponse` 新增 `missing_attributes` |
| 契约 §8.10.1 | `OrderSummary` 新增两字段 |
| 契约（顾客工具） | 新工具的输入输出与闸门，写在现有顾客工具契约处 |

### 3.5 范围补充：只读订单查询工具（2026-09-28 用户已确认纳入第一期）

原型首页和订单视图每一单都有「问问」。现有顾客工具只有商品、属性、店铺规则、购物车、售后资格、售后预览、记忆，**没有查本人订单状态与物流的工具**。智能助手现在答不了“这单到哪了”，只能降级。

**第一期补一个只读工具 `get_my_order`：**

- 输入 `order_id`；
- 输出支付状态、履约状态、支付截止、最近 5 条履约事件，以及订单明细的名称与数量；
- 闸门与 `check_after_sale_eligibility` 相同：`merchant_id + buyer_key` 双重过滤，只允许 v2 订单，访客直接拒绝；
- 不写任何数据，不在工具载荷里暴露 `buyer_key`；
- 归入售后服务 Skill 的可用工具；
- 按 PRD §15 的要求，随工具登记安全用例（跨顾客读取、访客读取）。

「问问」发出的消息里带订单号，例如“订单 BO-… 现在到哪了？”，模型据此调用工具。

（备选方案“不补工具、隐藏「问问」”已放弃。）

## 四、演示商品与图片

### 4.1 目录（保留五个类目；下标 = 现有种子顺序，类目按 `下标 % 5` 循环）

| # | 类目 | 中文名 | 英文名 | 价格（元） | 说明 |
| --- | --- | --- | --- | --- | --- |
| 01 | 女装 | 真丝印花半裙 | Silk print midi skirt | 569 | 审核中，不上架 |
| 02 | 男装 | 牛津纺长袖衬衫 | Oxford cloth shirt | 239 | |
| 03 | 鞋靴 | 手工缝线切尔西靴 | Goodyear-welt Chelsea boots | 699 | **刻意缺「产地」** |
| 04 | 家居 | 粗陶手作咖啡杯（两只装） | Stoneware mug pair | 128 | 库存紧张 |
| 05 | 美妆 | 燕麦舒缓保湿面霜 | Oat calming moisturiser | 159 | **刻意说明很短、无成分表** |
| 06 | 女装 | 亚麻宽松开衫 | Relaxed linen cardigan | 329 | 原为刻意无图；2026-10-04 用户裁定补图 |
| 07 | 男装 | 水洗帆布工装夹克 | Washed canvas chore jacket | 459 | |
| 08 | 鞋靴 | 复古德训运动鞋 | Retro trainers | 389 | |
| 09 | 家居 | 橡木砧板 | Oak chopping board | 199 | 审核中，不上架 |
| 10 | 美妆 | 玫瑰果油修护精华 | Rosehip repair serum | 219 | |
| 11 | 女装 | 羊毛混纺高领毛衣 | Wool-blend roll-neck jumper | 399 | |
| 12 | 男装 | 美利奴羊毛针织开衫 | Merino knit cardigan | 529 | |
| 13 | 鞋靴 | 软底乐福鞋 | Soft-sole loafers | 459 | |
| 14 | 家居 | 亚麻格纹桌布 | Linen check tablecloth | 169 | |
| 15 | 美妆 | 苦橙花淡香水 | Neroli eau de toilette | 399 | |
| 16 | 女装 | 高腰直筒牛仔裤 | High-rise straight jeans | 299 | |
| 17 | 男装 | 格纹羊绒围巾 | Check cashmere scarf | 489 | 审核中，不上架 |
| 18 | 鞋靴 | 防泼水徒步短靴 | Water-resistant hiking boots | 629 | 原型中示意为售罄；种子库存不改，仍为有货 |
| 19 | 家居 | 无花果雪松香氛蜡烛 | Fig & cedar candle | 149 | |
| 20 | 美妆 | 氨基酸温和洁面乳 | Gentle amino cleanser | 89 | |
| 21 | 女装 | 法式碎花连衣裙 | French floral dress | 459 | |
| 22 | 男装 | 修身斜纹休闲裤 | Slim twill trousers | 279 | |
| 23 | 鞋靴 | 羊皮芭蕾平底鞋 | Leather ballet flats | 399 | |
| 24 | 家居 | 羊毛混纺沙发毯 | Wool-blend throw | 359 | |

- 简介、材质 / 功效、产地、尺码 / 规格以原型 `RAW` 数组为准，实施时搬进 `backend/app/analytics/demo_data.py`。源语言为中文，英文走现有本地化缓存。
- **属性键必须覆盖后端类目必填表**，否则会误报内容缺口：女装、男装、鞋靴写「材质、产地、尺码」；家居写「材质、产地」（可另加尺寸或容量）；美妆写「产地、保质期」（可另加功效、规格）。原型里美妆没有「保质期」、服装用的是「尺码」以外的写法，以本条为准。刻意缺口只有 #03 的「产地」。
- 审核状态、库存（#04 为 3 件，其余 100 件）、刻意缺口的下标都不变（2026-10-04 起只剩 #03、#05 两个，#06 已补图）。售罄的展示由测试数据覆盖，不改种子库存，以免牵动库存告警等既有测试。
- **确定性约束**：价格改为上表固定值，但 `rng.uniform` 调用要保留（结果弃用），否则后续的商品 id 与上架日期会整体漂移，破坏 PRD §8.3 与 `test_demo_determinism`。
- 商家端经营数据（成交额、类目归因）会随价格变化。演示事实由种子重新生成，不需要人工改数字。

### 4.2 已部署环境的数据更新

- Railway 演示库里的商品行，须通过**现有演示数据刷新路径**更新名称、描述、属性、价格与图片地址，不写手工 SQL。
- 计划阶段先核对刷新路径是否覆盖已存在商品行的内容字段。不覆盖时补一个幂等的按 `product_code` 更新步骤，仍受 `ALLOW_DEMO_DATA_REFRESH` 控制。

### 4.3 图片交付规格（用户生成，我方接入与校验）

- 数量：24 张（2026-10-04 起；此前 23 张，#06 刻意无图）；三件审核中商品也要图，商家端商品页已用到。
- 生成：1:1 正方形，建议生成 1024×1024。
- 入库：
  - 转为 **800×800 WebP**，质量约 80，单张 ≤200KB；
  - 存到 `shop/public/demo/products/NN.webp`（NN 为 §4.1 编号）；
  - 种子里的 `image_url` 从 `.png` 改为 `/demo/products/NN.webp`。
- 同目录新增 `IMAGE-CREDITS.md`，写明 AI 生成工具、生成日期，以及“为本项目生成的虚构商品图，不含真实品牌”。
- **Railway**：图片提交进仓库后，会随 `shop` 的构建产物一起部署，不依赖对象存储、外链或运行时抓取。外部图片主机白名单 `ALLOWED_IMAGE_HOSTS` 保持为空。
- 渲染：`<img loading="lazy" decoding="async" width height>`，给固定宽高比防止布局跳动；`image_url` 为空时显示“暂无图片”斜纹占位。
- **已知边界**：`/demo/products/…` 是相对路径，只在 `shop` 的域名下有效。商家端目前不渲染商品图。将来商家端要显示时，另议使用 `shop` 的公开地址，本期不处理。
- 统一风格提示词见附录 A。转换和校验由实施计划里的一个脚本完成：尺寸、格式、大小、文件名与种子一一对应。

## 五、实施顺序与阶段位置

新阶段 **WS · 顾客端店面重设计**：

- **可以与商家端 W 并行的部分**：后端与数据相关的步骤，包括 PRD / 契约同步、`sort=popular`、`OrderSummary` 新字段、`get_my_order`、演示目录。`docs/api.json` 的导出须与 W、N4 串行（沿用 N4 路线图的规则）。
- **前端外壳要等 W 的 token 任务完成**：`shop/src/styles/tokens.css` 由 `npm run tokens:sync` 从商家端复制而来。W 替换商家端 token 后，`shop` 先同步，再写顾客端专有 token，避免两套色板分叉。
- **与 N4 B Task 8（顾客记忆页）的关系**：记忆页的功能迁进动态抽屉。如果 Task 8 还没收尾，就直接在新外壳里完成，不再做独立页面的样式。

建议顺序：

1. PRD 与契约同步（§3.4）。
2. 后端：商品排序、`OrderSummary` 字段、`get_my_order` 与安全用例、演示目录与刷新路径。
3. OpenAPI 导出、`codegen`、Adapter。
4. 在 W 的 token 任务之后：同步 token、偏好设置、i18n 字典、外壳。
5. 首页、对话、动态抽屉。
6. 订单视图、购物车侧栏、商品浮层、路由重定向。
7. 接入图片（用户交付后），运行校验脚本。
8. 验收。

## 六、验证

- **后端**（Fake LLM、真实 PostgreSQL）：
  - `sort=popular` 的顺序确定性、跨店隔离、游标绑定 `sort`；
  - `OrderSummary` 新字段的一致性与双重过滤；
  - `get_my_order` 的三类闸门用例（本人 / 他人 / 访客）；
  - 演示目录保留三个缺口，图片路径与文件一一对应。
- **前端**：`npm run test`、`typecheck`、`lint`、`codegen:check`、`tokens:check`、`build`。
- **Mock E2E**：
  - 访客与已绑定两种首页；
  - 快捷卡发送；
  - 订单「问问」与「去支付」；
  - 动态抽屉里的新建、浏览、跳转、删除会话；
  - 记忆关闭确认；
  - 中英切换与缺译标注；
  - 375px 宽度无横向滚动；
  - 旧路由重定向。
- 全程不调用真实模型。真实模型对新订单工具的回答质量，属于按 R3 另行授权的人工验收。

## 七、第二期（不在本规格内）

对话内嵌商品卡、对比表、加购确认卡。届时在契约 §8 为 `ShopChatResponse` 设计结构化展示块，数据来自工具结果，由后端校验后填充，不由模型直接生成金额或库存（R4 精神）。第一期的外壳与消息布局要给卡片留出位置，但不预先定义字段。

---

## 附录 A · 商品图生成提示词

**统一风格前缀**（每条都加在前面）：

> Studio product photograph, single item centered, soft natural window light from the left, warm cream paper backdrop (#f6f1e7) with a subtle paper texture, gentle soft shadow, muted natural colours, square 1:1, no text, no logo, no brand marks, no people, no hands, e-commerce catalogue style, high detail.

| 文件 | 商品 | 主体描述 |
| --- | --- | --- |
| 01.webp | 真丝印花半裙 | an A-line ankle-length silk midi skirt with a small muted botanical print, laid flat and slightly draped |
| 02.webp | 牛津纺长袖衬衫 | a pale blue cotton oxford button-down shirt, neatly folded |
| 03.webp | 手工缝线切尔西靴 | a pair of dark brown calf-leather Chelsea boots with elastic side panels and visible welt stitching, three-quarter view |
| 04.webp | 粗陶手作咖啡杯（两只装） | two hand-thrown stoneware mugs in matte oatmeal and sage glazes, slightly irregular shapes |
| 05.webp | 燕麦舒缓保湿面霜 | a plain frosted glass cream jar with a white lid, a few oat flakes beside it |
| 06.webp | 亚麻宽松开衫 | a relaxed-fit washed linen open-front cardigan in a natural flax beige colour, dropped shoulders, slightly crumpled linen texture, no buttons, laid flat with the sleeves loosely arranged（2026-10-04 补） |
| 07.webp | 水洗帆布工装夹克 | an olive washed-canvas chore jacket with four patch pockets, laid flat |
| 08.webp | 复古德训运动鞋 | a pair of white leather retro trainers with tan suede overlays and a gum rubber sole, side view |
| 09.webp | 橡木砧板 | a solid white-oak chopping board with rounded corners, angled view |
| 10.webp | 玫瑰果油修护精华 | a small amber glass dropper bottle of golden rosehip oil, a dried rosehip beside it |
| 11.webp | 羊毛混纺高领毛衣 | a camel fine-knit roll-neck jumper, folded |
| 12.webp | 美利奴羊毛针织开衫 | a charcoal merino V-neck cardigan with shell buttons, folded |
| 13.webp | 软底乐福鞋 | a pair of soft black lambskin loafers, three-quarter view |
| 14.webp | 亚麻格纹桌布 | a folded natural linen tablecloth with a muted green check pattern |
| 15.webp | 苦橙花淡香水 | a minimal clear glass perfume bottle with pale liquid, a sprig of orange blossom beside it |
| 16.webp | 高腰直筒牛仔裤 | a pair of mid-blue high-rise straight-leg jeans, folded to show the waistband |
| 17.webp | 格纹羊绒围巾 | a softly folded cashmere scarf in a muted grey and camel check |
| 18.webp | 防泼水徒步短靴 | a pair of rugged brown nylon-and-leather hiking boots with lug soles |
| 19.webp | 无花果雪松香氛蜡烛 | a soy wax candle in a matte green ceramic vessel, unlit, a fig leaf beside it |
| 20.webp | 氨基酸温和洁面乳 | a plain white squeeze tube of facial cleanser lying at a slight angle |
| 21.webp | 法式碎花连衣裙 | a knee-length viscose dress with a small cream-on-navy floral print and tie V-neck, on a hanger |
| 22.webp | 修身斜纹休闲裤 | a pair of stone-colour slim cotton twill trousers, folded |
| 23.webp | 羊皮芭蕾平底鞋 | a pair of blush-pink lambskin ballet flats, top view |
| 24.webp | 羊毛混纺沙发毯 | a folded oatmeal wool-blend throw blanket with fringed edges |

#06（亚麻宽松开衫）最初刻意不生成，2026-10-04 按用户裁定补上。
