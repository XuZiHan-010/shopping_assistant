# F2 Mock 会话闭环设计

## 目标

交付完整的问答闭环 UI 与状态机：发送、SSE 流式阶段标签、五种消息状态、商家切换与刷新恢复、会话历史与轮次目录。数据全部来自后端导出的 fixture 镜像，传输层由 Mock 实现。

**阶段契约：F2 把 UI 和状态机做完，F3 只换传输层实现，不写新 UI。** 任何"F3 再补这个界面"的设计都违反本约定。

## 范围

覆盖当前契约的四个业务端点：`POST /api/chat`（SSE 与 JSON 双路径）、`GET /api/demo/merchants`、`GET /api/conversations`、`GET|DELETE /api/conversations/{id}`。

不做：真实 HTTP 客户端、鉴权头装配、错误码分支、ECharts 图表、DETAIL 表格、CSV 导出、反馈接口、附件。前四项属于 F3，中间三项属于 F4，反馈属于 F5，附件属于 F7。

已完成不重做：`src/api/adapters/chat.ts` 与 `src/types/chat.ts` 由 F0 交付且测试齐全，F2 只消费不改写。

前端方案 §F3 把"创建 `api/chat.ts`"列为 F3 任务，但按本阶段契约该文件必须在 F2 建立，F3 只替换其底层 transport 与错误处理。写 F3 计划时不要重复创建。

## 架构

分层与 Mock 切入点：

```
Chat Store  ──→  api/chat.ts  ──→  readChatStream  ──→  ChatTransport  ──→  网络
                                    (sse.ts)            ↑ Mock 在这里替换
```

`ChatTransport` 是一个函数类型，真实实现是 `fetch`，Mock 实现构造 `Response`，body 为吐出 SSE 字节的 `ReadableStream`。其上三层不知道 Mock 存在。

切在传输层而非服务层，是为了让 SSE 解析器在 F2 就面对真实字节流：Mock 按随机边界切块，刻意切断多字节 UTF-8 字符和事件中间。解析器是 F2 唯一有算法复杂度的模块，也是最容易出隐蔽缺陷的地方——中文在块边界变成乱码肉眼看不出来，必须专门构造才能触发。把它推迟到 F3 首次接真机才验证，反馈环最慢。后端对自己的解析器采用同样的测法（后端方案 §14），前后端对称。

### 模块

```text
src/api/
├── transport.ts                 ChatTransport 类型、真实实现、按环境选择
├── sse.ts                       SSE 解析（纯缓冲逻辑 + 流读取）
├── chat.ts                      四个端点的调用封装，返回领域模型
└── mock/
    ├── fixtures.generated.ts    后端 fixture 镜像（生成产物，勿手改）
    ├── scenarios.ts             问题文本 → fixture 映射、会话与商家演示数据
    └── transport.ts             Mock ChatTransport

src/stores/
├── chat.ts                      会话、消息、轮次、流状态（F1 的最小 Store 在此扩展）
└── auth.ts                      演示商家列表、当前商家、Token、持久化

src/components/chat/
├── ChatMessage.vue              用户与助手消息、阶段标签、状态与重试入口
└── ConversationNav.vue          当前会话的轮次目录

src/components/layout/
└── ConversationDrawer.vue       历史会话列表与删除（接 F1 顶栏的目录按钮）

src/components/insights/
├── MetricDefinitionPanel.vue    指标口径文本
├── MetricChartPanel.vue         图表占位，F4 填充
└── RecommendationPanel.vue      建议卡片与猜你想问
```

`ConversationColumn.vue` 与 `ChatComposer.vue` 由 F1 交付，F2 扩展而非重建。

### fixture 交付

`docs/fixtures/chat/*.json` 是源，`src/api/mock/fixtures.generated.ts` 是提交进仓库的镜像，`npm run fixtures` 生成，`npm run fixtures:check` 做漂移检查并纳入门禁。这与 `docs/api.json` → `src/api/generated.ts` → `codegen:check` 完全对称。

不能用 alias 直接导入源文件：Railway 的 frontend service Root Directory 是 `/frontend`，Docker 构建上下文没有 `docs/`；`@fixtures` 的 TS 路径映射也只存在于 `tsconfig.vitest.json`，应用工程看不到它。

镜像用 `as const satisfies components['schemas']['ChatResponse']` 声明。JSON 导入会把 `answer_mode` 推断成 `string` 而无法满足枚举；生成 `as const` 的 TS 模块则可以，于是后端改 schema 时 `generated.ts` 变化会让镜像在 typecheck 阶段失败，比逐字节比对更早暴露。

Mock 模块经动态 `import()` 加载并由环境变量守卫，生产构建不包含。这一点由门禁检查 `dist/` 产物验证，不依赖对 tree-shaking 的信任。

## 数据流与状态机

### 消息状态

```text
                    ┌──────────── abort() ────────────→ cancelled
                    │
入列 → pending ──── 首个 step ──→ streaming ──── done ──→ complete
                    │                    │
                    └─ 响应头非 2xx ─┐    ├─ event: error ─┐
                                    └────┴─ 流无 done/error ┴──→ error
```

`cancelled` 与 `error` 分开：用户主动取消不是故障，UI 文案与是否提示重试都不同，混在一起会让每次取消都弹一次"出错了"。

助手消息在用户发送时即刻以 `pending` 入列，不等响应——阶段标签要在 1 秒内可见，靠的是真实 `step` 事件到达，不使用本地假进度。

### 幂等

`clientRequestId` 在消息**入列时**由 `crypto.randomUUID()` 生成并常驻消息对象，不在发请求时临时计算，否则重试路径拿不到原值。

| 场景 | 行为 |
| --- | --- |
| 首次发送 | 新 ID |
| 失败或流中断后重试 | 复用原 ID |
| 用户改写问题后发送 | 新消息、新 ID |
| 主动取消后重试 | 复用原 ID |

### 商家身份

Auth Store 持有演示商家列表、当前商家与 Token。Token 只进内存与请求头，不写 `localStorage`、URL 或日志。`sessionStorage` 只存非敏感标识 `selected_demo_merchant_key`。

刷新恢复顺序：拉商家列表 → 用标识选回同一商家 → Token 从响应取得并只进内存 → 加载该商家会话列表。标识在列表中找不到时回退默认商家并提示重新选择。

切换商家清空当前会话、消息与侧栏，避免跨商家串数据。前端不传 `merchant_id`。

### 侧栏

侧栏内容跟随**当前选中轮次**而非最新回答，切换轮次时整体重算，避免显示上一轮的残留数据。指标口径、建议、猜你想问按 `mode` 判空渲染；`METRIC` 以外的模式没有 `metric_*`，Adapter 返回 `undefined`，面板显示空状态而不是零值。

图表面板在 F2 只渲染占位说明，明确标注图表由 F4 呈现。DETAIL 表格同理。

## 错误处理

HTTP 层与流内错误分开：响应头阶段的非 2xx 走普通错误路径不进流；进入流之后的失败只会是 `event: error`。这与后端 §8.4 的约定一致。

流意外中断——既没有 `done` 也没有 `error`——视为错误，消息不得永久停在 `streaming`。

`cancelMessage` 调用 `AbortController.abort()` 真正中断底层流，不只是 UI 隐藏。

F2 不实现错误码分支（401/403/409/422 等），只区分"可重试"与"已取消"两类展示。错误码语义属于 F3。

## 测试策略

SSE 解析器是重点，用真实字节流测：随机边界切块、切断多字节 UTF-8 字符、切断事件中间、一次读取含多个事件、`: keep-alive` 心跳丢弃、缺 `event:` 行的容错。断言解码后中文不乱码。

Store 测试覆盖发送、SSE 事件流推进、五种状态迁移、幂等 ID 复用、取消、重试、新会话、切换商家、选中轮次、会话删除。

Mock 载荷全部来自 fixture 镜像并经 Adapter，不手写领域模型当 Mock——F0 的 zod 契约守卫在此第二次发挥作用，挡住后端不可能产生的载荷。

E2E 覆盖：每个快速问题可完成一轮问答、阶段标签 1 秒内出现、切换商家后会话与侧栏清空、跨 560px 断点选中商家不丢失、连续两轮后目录含两个节点、点击目录跳转、取消真正中断、删除会话后列表同步、刷新后选回同一商家。

快速问题直接采用 fixture 对应的六个原问题，否则点击无响应，"每个快速问题均可完成一轮问答"这条验收无法成立。

## 边界

不引入新运行时依赖。不改 `docs/api.json` 与 `src/api/generated.ts`。不建登录页。不调用真实 LLM 与真实数据库。`yshopping-prototype/` 与 `yshopping-merchant-ai 4/` 保持只读。

组件不直接引用 `generated.ts`，不做字段转换，转换点只有 `api/adapters/chat.ts`。

不把 DOM 节点、ECharts 实例或 `File` 对象存入 Store。
