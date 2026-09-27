# Vue 与 Python 面试题 · 结合 Borough 项目

> 岗位：泡泡玛特 · AI 全栈工程师
> 项目：Borough 商家 AI 助手（Vue 3 + TypeScript / Python 3.12 + FastAPI）
> 配套：`泡泡玛特-AI全栈工程师-面试准备.md`（总纲）、`JD对照-题库筛选与追问预测.md`（题库筛选）

---

## 使用说明

**每题两段结构：**

- **答**：通用原理，这是面试官想听的第一层
- **🔗 接项目**：把原理拐到 Borough 的真实代码上，这是拉开差距的第二层

**所有「接项目」的内容都已核实**，文件路径和行为都对得上。没写的东西项目里就是没有——
被问到 `provide/inject`、`Teleport`、`shallowRef` 时，**直接说没用过，不要编**。

> ⚠️ JD 资格 2 写的是「React、**Vue3** 等主流前端框架**及背后原理**」，
> 资格 4 写的是「**MySQL** 等关系型数据库」。
> 本文 Vue 部分是你的主场；React 和 MySQL 的缺口话术见 `JD对照` §3.5 / §3.6。

---

# 第一部分 · Vue

## A. 响应式原理（必考）

### V1. Vue3 的响应式是怎么实现的？和 Vue2 有什么区别？

**答：**

Vue3 用 `Proxy` 代理整个对象，拦截 `get` / `set` / `deleteProperty` 等 13 种操作：

- `get` 时调用 `track()`，把当前正在运行的副作用函数（`effect`）收集进这个 key 的依赖集合
- `set` 时调用 `trigger()`，取出依赖集合逐个重新执行

Vue2 用 `Object.defineProperty` 逐个属性劫持，三个硬伤：

| 问题 | Vue2 | Vue3 |
| --- | --- | --- |
| 新增属性 | 监听不到，要 `Vue.set` | Proxy 拦截整个对象，天然支持 |
| 删除属性 | 监听不到，要 `Vue.delete` | `deleteProperty` 拦截 |
| 数组索引/length | 监听不到，靠重写 7 个数组方法 | 天然支持 |
| 初始化开销 | 递归遍历所有属性 | **懒代理**，访问到嵌套对象才代理下一层 |

最后一条常被忽略但很重要：Vue3 的深层代理是**惰性**的，大对象不会在初始化时被整棵树递归遍历。

**🔗 接项目：**

Borough 的 Pinia store 全是 setup 风格（`frontend/src/stores/chat.ts` 等 5 个），
内部就是 `ref` + `computed` + `watch` 的组合，**不是 Options 风格的 `state/getters/actions`**。
这样写的好处是和组件里的 composable 是同一套心智模型，类型推断也不用靠 Pinia 的辅助类型。

---

### V2. `ref` 和 `reactive` 有什么区别？什么时候用哪个？

**答：**

- `reactive` 只能代理对象，用 Proxy；原始值没法代理
- `ref` 用一个 `{ value }` 包装对象绕开这个限制，内部对 `.value` 做 getter/setter 拦截；
  如果传进去的是对象，`ref` 内部会再调 `reactive`
- `reactive` 解构会丢响应性（拿到的是普通值），`ref` 不会——所以 composable 的返回值一律用 `ref`
- 模板里 `ref` 自动解包，`script` 里必须写 `.value`

实践上的默认选择：**统一用 `ref`**。少一个"这里该用哪个"的决策点，也不会踩解构陷阱。

**🔗 接项目：**

Borough 全项目统一 `ref`，没有出现过 `reactive`。
`useEChart(container, option, enabled)` 三个参数全是 `Ref<T>` 而不是裸值——
因为 composable 必须拿到**引用**才能 `watch`，传裸值进去就只是一个快照。

---

### V3. `computed` 和 `watch` 怎么选？`watch` 的 `flush` 是干什么的？

**答：**

- `computed` 是**派生状态**：有缓存，依赖不变就不重算，必须同步且无副作用
- `watch` 是**副作用**：依赖变了要去做点别的事（请求、DOM 操作、日志）

`flush` 控制回调在更新周期的哪个阶段跑：

| flush | 时机 | 用途 |
| --- | --- | --- |
| `pre`（默认） | 组件更新**之前** | 拿到的是旧 DOM |
| `post` | 组件更新**之后** | 需要访问更新后的 DOM |
| `sync` | 同步立即 | 很少用，容易触发多次 |

**🔗 接项目（这题是你的加分位）：**

`frontend/src/composables/useEChart.ts` 最后三行：

```ts
onMounted(render)
// 容器是 v-if 控制的子节点；它本身出现或消失就是渲染时机，不能只靠 enabled 代替。
// flush 必须是 post：option 与容器可能在同一次更新中出现，默认 pre 会早于 DOM 打补丁。
watch([option, enabled, container], render, { flush: 'post' })
onBeforeUnmount(dispose)
```

**这里踩过真坑**：图表容器由 `v-if` 控制。当"有图表数据"和"容器出现"发生在**同一次更新**里时，
默认的 `flush: 'pre'` 会在 DOM 打补丁**之前**触发 `render()`，此时 `container.value` 还是 `null`，
或者 `clientWidth === 0`，`echarts.init()` 拿到一个零宽容器，图表渲染不出来。

改成 `flush: 'post'` 之后，回调保证跑在 DOM 更新完成之后。
**并且把 `container` 本身也放进了依赖数组**——容器的出现和消失本身就是渲染时机，
只 watch `enabled` 是不够的。

> 这个答案证明你不是背 API，是真的被这个时序坑过。

---

### V4. `watch` 和 `watchEffect` 的区别？

**答：**

- `watch`：显式声明依赖源，惰性（默认不立即执行），能拿到 `oldValue`
- `watchEffect`：自动收集回调里用到的响应式依赖，**立即执行一次**，拿不到旧值

`watchEffect` 的坑是依赖是隐式的——回调里加一行代码可能就多了一个依赖源。
代码量大了之后，`watch` 的显式依赖更好维护。

**🔗 接项目：**

Borough 全部用 `watch`，一处 `watchEffect` 都没有。原因就是上面那条：
显式依赖在 code review 和改动时能一眼看清触发条件。

`frontend/src/App.vue` 有个典型写法：

```ts
watch(i18n.global.locale, syncFavicon, { immediate: true })
```

`immediate: true` 让它兼具"初始化执行一次"和"后续变化时执行"，不用在 `onMounted` 里再写一遍。

---

### V5. `nextTick` 是干什么的？为什么需要它？

**答：**

Vue 的 DOM 更新是**异步批量**的：同一个 tick 内多次修改响应式数据，只会触发一次渲染。
所以改完数据立刻读 DOM，读到的还是旧的。`nextTick` 把回调推到 DOM 更新之后。

底层是微任务队列（`Promise.then`）。

**🔗 接项目：**

`frontend/src/components/chat/ChatComposer.vue`：

```ts
watch(message, () => void nextTick(resizeTextarea))
```

输入框要根据内容自动撑高。必须等文本真的渲染进 `<textarea>` 之后才能读 `scrollHeight`，
否则算出来的是上一次的高度。

前面的 `void` 是 TypeScript 的写法——明确表示"我不关心这个 Promise 的结果"，
避免 ESLint 的 `no-floating-promises` 报错。

---

## B. 组件与性能

### V6. `defineAsyncComponent` 是怎么工作的？你什么时候用它？

**答：**

它接收一个返回 Promise 的 loader，把组件变成异步组件。配合 Vite 的动态 `import()`，
构建时会把这个组件拆成独立 chunk，用到时才发请求。

**关键细节（很多人不知道）：loader 在组件第一次「要渲染」时就执行**，
不是在"用户看到它"时执行。所以单靠 `defineAsyncComponent` **并不能**把它排除出首屏。

**🔗 接项目（强烈建议主讲这段）：**

Borough 有一条硬约束：**ECharts 不允许进入首屏关键路径**。ECharts 打包后体积很大，
但用户第一眼看到的是聊天界面，图表要等他问出一个指标问题才出现。

三层措施：

**第一层 · 构建拆分**
`vite.config.ts` 的 `manualChunks` 把 ECharts 拆成独立 chunk，
并且 `useEChart.ts` 里用的是按需注册而不是全量引入：

```ts
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([BarChart, LineChart, PieChart, /* ...components */, CanvasRenderer])
```

**第二层 · 挂载时机**
`AssistantView.vue` 里，光有 `defineAsyncComponent` 不够，必须用 `v-if` 卡住挂载：

```ts
const MetricChartPanel = defineAsyncComponent(
  () => import('@/components/insights/MetricChartPanel.vue'),
)

// defineAsyncComponent 的 loader 在组件首次渲染时就会执行，所以单靠它无法延迟
// 请求——必须用 v-if 控制挂载时机。首屏先渲染静态占位，等空闲时段或真的来了
// 带图表的回答再挂载，让 ECharts 退出首屏网络路径。
const chartMountable = ref(false)
```

触发条件是 `requestIdleCallback` **或** 真的来了带图表的回答，
并且用 `setTimeout` 兜底（有些浏览器没有 `requestIdleCallback`），
卸载时 `cancelIdleCallback` + `clearTimeout` 一起清。

**第三层 · 双重门禁**
- `frontend/scripts/check-first-paint.mjs`：静态扫 `dist/`，
  确认存在独立的 `echarts-*.js` chunk，且 `index.html` 没有预加载它
- `frontend/e2e/first-paint.spec.ts`：真浏览器**网络观测**，证明首屏没请求这个 chunk

脚本里的注释写得很清楚：

```
// 这是静态兜底：真正的证据是 e2e/first-paint.spec.ts 的网络观测。
// 两层都留着——e2e 证明行为，本脚本在不跑浏览器的门禁里快速拦回归。
```

> **为什么这个故事值钱**：它同时展示了「知道 API 的隐藏行为」「会做性能预算」
> 「把约束固化成 CI 门禁而不是靠自觉」三件事。

---

### V7. 组件卸载时要注意什么？内存泄漏怎么防？

**答：**

`onBeforeUnmount` / `onUnmounted` 里必须清理**不受 Vue 管理**的资源：

- `addEventListener` → `removeEventListener`
- `setTimeout` / `setInterval` → `clearTimeout` / `clearInterval`
- `ResizeObserver` / `IntersectionObserver` → `disconnect()`
- 第三方库实例 → 它自己的 `dispose()` / `destroy()`
- `requestIdleCallback` → `cancelIdleCallback`

`watch` 和 `computed` 在组件 scope 内会自动停止，**不用手动清**；
但如果是在组件外创建的（比如模块级），就要自己 `stop()`。

**🔗 接项目：**

`useEChart.ts` 的 `dispose()` 把三样一起清：

```ts
function dispose(): void {
  observer?.disconnect()
  observer = undefined
  instance?.dispose()
  instance = undefined
}
```

注意两个设计选择：

1. **ECharts 实例用 `let instance` 局部变量持有，不放 `ref`**。
   因为它不需要被模板消费，放进响应式系统只会带来被代理的风险和没必要的开销。
2. **`dispose()` 在两处被调用**：`onBeforeUnmount` 时，以及 `render()` 里发现
   "容器没了 / 宽度为 0 / 没数据"时。后者让图表可以反复销毁重建而不泄漏。

`ResizeObserver` 的回调还包了一层 `requestAnimationFrame`：

```ts
observer = new ResizeObserver(() => {
  window.requestAnimationFrame(() => instance?.resize())
})
```

防止尺寸连续变化时高频触发 `resize()` 造成抖动。

---

### V8. Vue 的 diff 算法 / `key` 的作用？

**答：**

Vue3 用**双端 + 最长递增子序列（LIS）**做同层比较：

1. 先从头部同步扫描相同节点，再从尾部同步扫描
2. 处理只新增或只删除的简单情况
3. 剩下的乱序部分，建立 `key → 新索引` 的映射，求 LIS，
   **不在 LIS 里的节点才需要移动** —— 这样移动次数最少

`key` 是节点身份标识。不写或用 index 做 key，会导致 Vue 按位置而不是按身份复用节点：
列表中间插入一项时，后面所有节点的内部状态（输入框的值、组件的 `ref`）会串位。

Vue3 还有编译期优化，这部分比 diff 本身收益更大：

- **静态提升**：静态节点提到渲染函数外，只创建一次
- **PatchFlag**：编译时标记这个节点哪些属性是动态的，运行时只比对被标记的部分
- **Block Tree**：把动态节点拍平成数组，diff 时跳过整棵静态子树

**🔗 接项目：**

Borough 的消息流、对话列表、明细表都用业务 ID 做 key，不用 index。
明细表尤其重要——它带分页和 CSV 下载，用 index 做 key 会在翻页时复用错行。

---

## C. 工程化（这部分最能体现"全栈"）

### V9. 前后端类型怎么保持一致？

**答：**

手写 TS 接口去对后端字段，是必然会漂移的。正确做法是**契约驱动、单向生成**。

**🔗 接项目（这是 Borough 前端最值得讲的架构决策）：**

Borough 定了一条单向数据流，**组件不允许直接消费生成类型**：

```
FastAPI → OpenAPI → docs/api.json
                      ↓ openapi-typescript
              api/generated.ts        ← 禁止手改
                      ↓
              api/adapters/*.ts       ← 唯一转换点，每个配契约测试
                      ↓
              types/*.ts              ← 前端领域模型
                      ↓
              Store → 组件
```

四个配套机制：

1. **`generated.ts` 提交进仓库**，不在构建期生成。
   因为 Railway 的 frontend 构建上下文只有 `/frontend`，读不到仓库根的 `docs/api.json`。
2. **`npm run codegen:check`** 重新生成到临时文件再逐字节比对，防止它过期。
   `.gitattributes` 把它钉成 `eol=lf`，否则 Windows 的 `core.autocrlf` 会让比对假失败。
3. **Adapter 契约测试**：后端改字段时，Adapter 的测试立刻红，而不是等到运行时白屏。
4. **分级同步规则**：传输字段变了但领域语义没变 → 只改 `generated.ts` + Adapter；
   领域语义变了 → 才需要动 types / Store / 组件 / 测试。

> 被追问"为什么不让组件直接用生成类型"：因为生成类型是**传输结构**，
> 组件要的是**领域模型**。中间没有转换层的话，后端一次改名就要全项目搜索替换。

---

### V10. SSE 流式响应前端怎么处理？为什么不用 `EventSource`？

**答：**

`EventSource` 是浏览器原生 SSE 客户端，但有两个硬限制：

1. **不能带自定义请求头** —— 没法传 `Authorization: Bearer <token>`
2. 只支持 GET —— 没法用 POST 提交请求体

所以带鉴权的 SSE 必须手写：`fetch` 拿到 `response.body`（一个 `ReadableStream`），
`getReader()` 逐块读，自己按 SSE 协议切帧（`\n\n` 分隔事件，`event:` / `data:` 前缀）。

**🔗 接项目：**

`frontend/src/api/sse.ts` 就是这个实现：

```ts
body: ReadableStream<Uint8Array>,
const reader = body.getReader()
```

后端 `POST /api/chat` 默认返回 SSE，三种事件：`step` / `done` / `error`。

**一个刻意的契约设计**：`done` 事件的载荷和非流式 `ChatResponse` **完全一致**。
客户端发 `Accept: application/json` 就走普通 JSON 路径。
这样前端**不为两条路径维护两套解析** —— 同一个 Adapter 吃两种传输方式。

---

### V11. 国际化怎么保证中英文 key 不漏？

**答：**

运行时发现"某个 key 没翻译"太晚了。要在**编译期**锁住。

**🔗 接项目：**

- `frontend/src/i18n/locales/zh-CN.ts` 是**事实源**
- `keys.ts` 从它派生出 `MessageSchema` 类型形状
- `en-US.ts` 用 `satisfies MessageSchema` 校验 —— key 集合不一致直接编译失败
- 约定**禁止 `t(key as any)`**，因为那会绕过整套 key 校验

后端也有一套：`backend/app/localization/locales.py` 的 `SupportedLocale`
和前端 `i18n/index.ts` 的字面量**严格一致**，作为 `Accept-Language` 的派生值直发后端。

后端还刻意区分了两个枚举，**这个区分常被问到**：

| 枚举 | 含义 | 取值 |
| --- | --- | --- |
| `SupportedLocale` | 响应**显示**语言 | `zh-CN` / `en-US` |
| `SourceLanguage` | 内容**源**语言探测 | 多出 `mixed` / `und` |

混用这两个就会出现"检测到 mixed 就去渲染 mixed 语言"这种错。

---

### V12. 前端测试你怎么写？

**答（🔗 直接接项目）：**

- **Vitest 单测 535 条 / 51 个文件**，测试代码 9616 行 > 生产代码 9218 行
- **Playwright e2e**：assistant / conversation / isolation / knowledge-base / localization /
  ops-dashboard / responsive / first-paint，另有 `real-api/` 子目录需要真实后端

三个值得讲的细节：

1. **e2e 进程管理是自己写的**。Windows 下 Playwright 自带的 `webServer` 启动的是 shell 进程树，
   `child.kill()` 只终止 Node 自身，Vite 派生的子进程会残留占用端口，测试跑完不退出。
   抽了 `frontend/scripts/e2e-process.mjs` 统一按真实 PID 收尾（Windows 走 `taskkill /T`）。
2. **测试里冻结时钟**。有两条导出测试因为真实挂钟超过 fixture 硬编码的 `expires_at` 而随机失败，
   改成冻结时钟后稳定。
3. **构建产物门禁**：`check-no-secrets.mjs` 递归扫 `dist/` 的 JS/CSS/HTML/JSON 和 source map，
   阻止密钥形态字符串进入构建产物。

**诚实缺口**：`npm run typecheck` 目前还有 **7 个错误**，
全是测试辅助函数 `mountX` 的泛型推断问题，已登记但未处理。**被问到不要说"全绿"。**

---

## D. React 缺口（JD 把 React 写在 Vue3 前面）

### V13. React 你写过吗？

**答（照这个结构说）：**

> "Vue3 是我的生产栈，React 我理解模型但没有项目级实践。"

然后立刻接住，讲清核心差异（证明你不是不懂，是没写过）：

| 维度 | Vue3 | React |
| --- | --- | --- |
| 更新粒度 | Proxy 依赖收集，**精确到组件** | 默认整棵子树重渲染 |
| 优化方式 | 框架自动 + 编译期 PatchFlag | 手动 `memo` / `useMemo` / `useCallback` |
| 心智负担 | 响应式是"魔法"，要理解依赖收集 | 显式但啰嗦，要管依赖数组 |
| 状态 | `ref` 可变 | `useState` 不可变，闭包陷阱 |
| 模板 | 编译期可静态分析 | JSX 是运行时表达式，优化空间小 |

收尾一句：

> "这个项目是我全栈独立做的，从 Prototype 到工程实现、从契约到测试门禁都是自己搭的。
> 切框架的成本主要在心智模型，不在语法——而心智模型这层我是清楚的。"

**不要**说"React 和 Vue 差不多"，那会显得你两个都不深。

---

# 第二部分 · Python

## E. 语言特性（JD 资格 1「计算机基础扎实」）

### P1. 你用了 Python 3.12 的哪些新特性？

**答（🔗 全部接项目）：**

| 特性 | 版本 | 项目里的用法 |
| --- | --- | --- |
| `StrEnum` | 3.11 | `ErrorCode`、`ComparisonMode`、`KnowledgeSource`、`LlmFailureKind` |
| `X \| None` 联合语法 | 3.10 | 全项目取代 `Optional[X]` |
| `match` 语句 | 3.10 | 意图路由分支 |
| `Self` / `TypeVar` 语法改进 | 3.11/3.12 | `repositories/protocols.py` |
| `asyncio.TaskGroup` | 3.11 | **没用** —— 项目里是单任务 + `asyncio.wait` |

`StrEnum` 的实际价值：它同时是 `str` 的子类，所以能直接 JSON 序列化、直接和字符串比较、
直接做字典 key，不用到处写 `.value`。

```python
class ErrorCode(StrEnum):
    ...
```

全项目还统一写了 `from __future__ import annotations`，
让类型注解延迟求值 —— 避免循环导入，也让前向引用不用加引号。

---

### P2. `Protocol` 是什么？和抽象基类（ABC）有什么区别？

**答：**

`Protocol` 是**结构化子类型**（鸭子类型的静态版本）：
只要一个类"长得像"，就满足这个协议，**不需要显式继承**。

| | ABC | Protocol |
| --- | --- | --- |
| 关系 | 名义子类型，必须 `class X(Base)` | 结构子类型，长得像就行 |
| 侵入性 | 实现方必须知道接口的存在 | 实现方完全不知道 |
| 检查时机 | 运行时 | mypy 静态检查 |
| 适用 | 你控制两边代码 | **定义方和实现方解耦** |

**🔗 接项目（这题答得好能直接体现架构能力）：**

Borough 用 `Protocol` 做**依赖倒置**，`backend/app/agent/graph.py` 里定义了一批：

```python
class QueryServiceLike(Protocol): ...
class NodeTimerLike(Protocol): ...
class HistoryQuestionsLike(Protocol): ...
class SessionHistoryLike(Protocol): ...
```

**为什么重要**：Agent 图不 import 具体的 `SafeQueryService`，只 import 协议。
带来三个直接好处：

1. **测试不用 mock 框架** —— 写个满足协议的小类塞进去就行，类型检查还能保证它没写错
2. **没有循环导入** —— `graph.py` 不依赖 `services/`
3. **替换实现零成本** —— 比如把 `FakeLlmClient` 换成 `DeepSeekLlmClient`

还有一个泛型协议，`backend/app/repositories/protocols.py`：

```python
ConversationT = TypeVar("ConversationT", covariant=True)

class ConversationLookupProtocol(Protocol[ConversationT]):
    async def get_for_merchant(
        self, conversation_id: UUID, merchant_id: UUID
    ) -> ConversationT | None: ...
```

**`covariant=True` 会被追问**：因为 `ConversationT` 只出现在**返回位置**，
所以协议在它上面是协变的 —— 返回子类型的实现可以替代返回父类型的协议。
如果它出现在参数位置，就必须是逆变或不变，否则类型不安全。

---

### P3. `@dataclass` 和 Pydantic `BaseModel` 怎么选？

**答：**

| | `@dataclass` | Pydantic `BaseModel` |
| --- | --- | --- |
| 运行时校验 | 无（注解只给类型检查器看） | **有**，按注解强制校验并转换 |
| 性能 | 快，纯标准库 | 有校验开销 |
| 序列化 | 要自己写 | 内置 |
| 用途 | **内部数据传递** | **边界数据校验** |

判断标准很简单：**数据来自外部（HTTP 请求、LLM 输出、配置）就用 Pydantic；
内部计算结果传递就用 dataclass。**

**🔗 接项目：**

Borough 严格按这条边界分：

- **Pydantic**：`app/schemas/`（API 契约）、`app/intent/models.py`（**LLM 输出**）、
  `app/core/config.py`（环境变量）
- **dataclass**：`agent/graph.py`、`agent/prefilter.py`、`analytics/chatbi_metrics.py`、
  `core/metrics.py`、`core/security.py`、`intent/service.py` 等内部结果对象

内部 dataclass 大量用 `@dataclass(frozen=True)` —— 不可变，能当字典 key，
也杜绝了"某个节点偷偷改了上游结果"这类 bug。

**LLM 输出用 Pydantic 是安全设计的一环**（对应项目硬规则 R4）：
模型只能输出经 Pydantic 校验的结构化意图，**永远碰不到 SQL**。
校验不过就直接拒绝，不会有半结构化的脏数据流进查询层。

---

### P4. Pydantic v2 的 `model_validator` 你怎么用的？`mode` 的区别？

**答：**

- `mode="before"`：字段校验**之前**跑，拿到的是原始输入（通常是 dict），
  用来做**数据规整** —— 兼容旧字段名、填默认值、清洗格式
- `mode="after"`：所有字段校验**之后**跑，拿到的是模型实例，
  用来做**跨字段一致性校验**

**🔗 接项目：**

`backend/app/intent/models.py` 两种都用了：

```python
@model_validator(mode="before")   # 规整 LLM 返回的原始 JSON
@model_validator(mode="after")    # 跨字段约束
```

还有两个值得讲的细节：

**1. `Field(default_factory=list)` 而不是 `= []`**

```python
dimensions: list[str] = Field(default_factory=list)
filters: dict[str, str] = Field(default_factory=dict)
```

这是 Python 的经典陷阱：可变默认值会在所有实例间共享。
Pydantic 其实会帮你深拷贝，但 `default_factory` 是显式且通用的写法。

**2. `SkipJsonSchema`**

```python
cross_business_plan_rejected: SkipJsonSchema[bool] = Field(...)
generated_metric_plan_rejected: SkipJsonSchema[bool] = Field(...)
```

这两个字段是**后端内部的拒绝标记**，不能出现在给 LLM 看的 JSON Schema 里 ——
否则模型会以为自己该填这个字段，甚至自己宣称"我被拒绝了"。
`SkipJsonSchema` 让它留在模型里但不进 Schema。

> 这个细节很能打：它说明你考虑过"**给模型看的契约**和**内部数据结构**不是一回事"。

---

## F. 异步编程（Python 后端高频）

### P5. `async` / `await` 的本质是什么？什么时候用它反而更慢？

**答：**

`async def` 定义协程函数，调用返回协程对象但不执行。
事件循环驱动它，遇到 `await` 就**让出控制权**，去跑别的任务，I/O 就绪后再回来。

本质是**单线程内的协作式多任务** —— 没有线程切换开销，也没有 GIL 争抢，
但**一旦有任务不让出，整个循环就卡住**。

什么时候更慢或更糟：

- **CPU 密集**：协程不会让出，整个事件循环被阻塞。要用 `asyncio.to_thread` 或进程池
- **调用了同步阻塞库**：比如同步的 `requests`、同步的 DB 驱动 —— 这是最常见的事故，
  表面在用 async 框架，实际把事件循环卡死
- **本身没有 I/O 等待**：纯计算包一层 async 只是徒增开销

**🔗 接项目：**

Borough 后端**全链路异步**：FastAPI + SQLAlchemy Async + psycopg(async) + httpx。
中间没有任何一处同步阻塞调用 —— 这是刻意保证的，
因为 LLM 调用的等待时间很长（一次几百毫秒到几秒），
如果这段时间卡住事件循环，并发能力会直接归零。

---

### P6. SSE 长响应里，请求处理很慢会发生什么？你怎么解决的？

**答（🔗 这是项目里最有含金量的异步细节）：**

问题：SSE 连接建立后，如果后端一直不发数据，中间的代理、网关、浏览器可能判定超时断开。
Agent 跑 12 个节点、要调好几次 LLM，中间确实会有长时间沉默。

解决办法是**把业务处理放进独立 task，主循环负责发心跳**：

```python
task = asyncio.create_task(
    service.submit(context, payload, request_id=request_id, locale=locale)
)
try:
    while True:
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
        if done:
            break
        yield _HEARTBEAT_FRAME

    execution = task.result()
```

三个关键点：

1. **`asyncio.wait` 带 `timeout` 不会取消任务** —— 超时只是返回，任务继续跑。
   这和 `asyncio.wait_for` 不同，后者超时会**取消**任务。用错就把业务给杀了。
2. **`task.result()` 会把任务里的异常重新抛出来**，所以外面能正常 `except`。
3. **响应头已经发出去了，所以之后的任何失败只能走 `event: error`**，
   不能再返回 HTTP 4xx/5xx —— 状态码那一刻已经写死了。

代码注释里明确写了这个约束：

```
响应头在第一个字节之前就已发出，所以进入这里之后的任何失败都只能走
`event: error`（§8.4）。认证和请求体校验发生在依赖与 FastAPI 校验阶段，
仍由全局处理器返回普通 JSON 错误，不会进到这里。
```

**顺带的设计推论**：所有可能失败的校验（鉴权、请求体）必须放在**依赖注入阶段**，
在流开始之前就失败掉，这样才能返回正常的 JSON 错误。

还有一个本地化细节：流内的 `error.message` 必须按当前请求的 `locale` 渲染
（`localize_error_message(exc.code, exc.message_params, locale)`），
不能直接透出 `exc.message` —— 那是异常**构造时**写入的整句，
可能来自别的请求、别的语言。

---

### P7. FastAPI 的依赖注入是怎么工作的？`yield` 依赖有什么用？

**答：**

`Depends()` 声明依赖，FastAPI 在请求进来时按依赖图求值，同一请求内**同一依赖只算一次**（自动缓存）。

`yield` 依赖相当于一个请求作用域的上下文管理器：
`yield` 之前是 setup，之后是 teardown，**即使路由抛异常也会执行**。
用来管数据库会话、文件句柄这类需要收尾的资源。

**🔗 接项目：**

`backend/app/api/dependencies.py` 用的是 `Annotated` 写法（Pydantic v2 / FastAPI 推荐）：

```python
session: Annotated[AsyncSession, Depends(get_db_session)]
credentials: Annotated[..., Depends(_bearer)]
settings: Annotated[Settings, Depends(get_app_settings)]
context: Annotated[MerchantContext, Depends(get_merchant_context)]
```

比老式的 `session = Depends(get_db_session)` 好在：类型信息和依赖声明分离，
可以被 mypy 正确推断，也能复用成类型别名。

**依赖链是有层次的**，这一点很重要：

```
get_app_settings → get_db_session → get_merchant_context → 业务依赖
```

`get_merchant_context` 是**安全边界** —— 它从 Bearer Token 解析出可信的 `merchant_id`。
后面所有查询用的都是它，**不是**前端传来的商家编号（项目硬规则 R5）。

`get_app_settings` 上挂了 `@lru_cache`（`core/config.py:230`）——
配置解析只跑一次，后续请求直接命中缓存。

---

## G. 数据库（JD 资格 4）

### P8. SQLAlchemy 2.0 的 async 怎么用？连接池怎么配？

**答（🔗 接项目）：**

`backend/app/db/session.py`：

```python
self.engine: AsyncEngine = create_async_engine(
    ...,
    pool_pre_ping=True,
    pool_size=5,
)
```

两个参数的理由：

- **`pool_pre_ping=True`**：每次从池里取连接先发一个轻量探测。
  云数据库（项目用的是 Neon）会主动断开空闲连接，没有 pre_ping 就会拿到死连接、报
  "server closed the connection unexpectedly"。**代价是每次取连接多一次 round trip**，
  换来的是不用在业务层写重试。
- **`pool_size=5`**：Railway 容器规格小，且 Neon 有连接数上限。
  异步场景下连接数不需要等于并发数 —— 协程在 `await` 时会归还连接。

会话用 `@asynccontextmanager` 包装：

```python
@asynccontextmanager
async def ...:
    ...
    yield session
```

保证异常时也能正确关闭。

---

### P9. 你做过哪些数据库优化？

**答（🔗 全部是项目里的真实做法）：**

**1. 复合索引前缀对齐多租户**

所有经营表的索引都以 `merchant_id` 开头：

```python
Index("ix_orders_merchant_business_date", "merchant_id", "business_date")
Index("ix_orders_merchant_status", "merchant_id", "order_status")
Index("ix_orders_merchant_address_city", "merchant_id", "address_city_name")
Index("ix_refunds_merchant_business_date", "merchant_id", "business_date")
Index("ix_support_tickets_merchant_business_date", "merchant_id", "business_date")
```

**为什么能这么设计**：因为查询层**强制注入** `merchant_id`，
每一条查询都必然带这个条件，最左前缀天然可用。
安全约束和性能设计在这里是同一件事。

**2. 约束下推到 SQL**

日期范围（最长 180 天）、最大行数、`statement_timeout` 全部在 SQL 层限制，
**不是**拉回应用层再过滤。这既是性能，也是安全 —— 防止一次查询拖垮库。

**3. 聚合下推**

"猜你想问"要按同商家同分类的历史**高频**问题排序。
`AnswerRepository.top_category_questions()` 把 `GROUP BY` + `ORDER BY` + `LIMIT`
**全部下推到 SQL**，不拉全量数据回内存排序。

**4. 慢查询定位**

`EXPLAIN ANALYZE` 看是否走索引、有没有 Seq Scan；PostgreSQL 用 `pg_stat_statements`。
**（对应 MySQL：慢查询日志 + `EXPLAIN`，看 `type` / `key` / `rows` / `Extra`）**

> ⚠️ JD 写的是 MySQL。主动把 PG 的做法翻译成 MySQL 术语，证明你不是只会一种。
> 最左前缀、覆盖索引、回表这些概念两边是通的。

---

### P10. 事务怎么用的？savepoint 是干什么的？

**答：**

`SAVEPOINT` 是事务内的检查点，可以只回滚到某个点，而不是整个事务。
SQLAlchemy 里是 `session.begin_nested()`。

典型场景：主流程必须成功，但其中某个**可选**步骤失败了不应该拖垮主流程。
如果不用 savepoint，子操作抛的 SQL 错误会让整个事务进入 aborted 状态，
后续所有语句都会报 `current transaction is aborted`。

**🔗 接项目（两处真实用法）：**

**1. `repositories/answer.py:120`** —— 推荐问题查询

```python
# 推荐问题是主回答之外的可选能力。SQL 错误必须仅回滚这里的 savepoint，
async with self._session.begin_nested():
```

"猜你想问"的统计查询挂了，只回落静态推荐，**不能污染主聊天事务** ——
用户的问题已经答出来了，不该因为一个推荐列表失败而整轮失败。

**2. `repositories/conversation.py:139`** —— 并发首建

```python
# 并发首建时，条件唯一索引才是最终裁决；savepoint 让输家可以继续在
async with self._session.begin_nested():
```

两个请求同时创建同一个会话，靠**条件唯一索引**做最终裁决。
输的那个请求捕获唯一约束冲突后回滚 savepoint，然后回读赢家写入的那条记录，
**继续在同一个事务里完成后续工作**。

> 这两处都体现同一个原则：**先想清楚哪些失败是可容忍的，再决定事务边界画在哪。**

---

### P11. 幂等怎么做的？

**答（🔗 接项目）：**

两处，用的是同一个思路：**业务唯一键 + 数据库唯一约束 + 冲突时回读**。

1. **聊天请求**：`answers` 表上 `client_request_id` 唯一约束。
   前端重发（网络抖动、用户连点）时，后端不会产生第二条回答，而是回读同一份结果。
2. **每日报告**：用 `daily-report:{report_date}` 做答案幂等键。
   并发首次请求时，只有一个真的去生成，其余回读同一份已完成报告。

**关键是把幂等放在数据库约束上，不是在应用层"先查再写"** ——
后者在并发下必然有竞态窗口。

---

## H. 工程实践

### P12. 你的测试是怎么组织的？

**答（🔗 接项目）：**

```
backend/tests/unit/          纯逻辑，Fake 依赖
backend/tests/integration/   需要真实 PostgreSQL，无 Docker 时自动 skip
backend/tests/api/           HTTP 契约
backend/tests/support/       共享测试替身与 fixture
```

当前：**1128 passed / 261 skipped**（跳过的是需要真实 PG 的集成测试）；
最近一次真实数据库全量是 **1049 passed / 0 skipped / 0 failed**。
`ruff check` 和 `mypy app` 全绿。

**三个值得讲的教训（比数字更有说服力）：**

**1. 门禁全绿不等于行为正确**

`memory_agent.py` 里有个 `history=[]` 的 bug —— 记忆沉淀时不读历史问答，导致记忆无法累积。
它在 **899 个测试全绿**的前提下活了很久才被发现。
结论固化成了规则：凡是"参考实现传了值、我方传空值"的形参，
必须有一条**断言输入内容**的测试，不能只断言不抛异常。

**2. `FakeLlmClient` 会掩盖整类缺陷**

它返回预写好的合法 JSON，所以"**提示词有没有告诉模型该输出什么**"这件事
在自动化测试里完全不可见 —— Fake 全绿，线上必挂。

解决办法：新增或修改任何 LLM 提示词时，必须同时加一条
**从 Pydantic 模型推导期望值的提示词契约测试**
（范式见 `backend/tests/unit/intent/test_prompts.py`）。
模型新增字段而提示词没同步，测试立刻红。

**3. 测试要能证明自己有效**

改知识检索评分时做过**反转验证**：临时去掉动作/规则词门槛，
确认干扰文档的测试会变红，再恢复后转绿 —— 证明这条测试真的能抓住误召回，不是摆设。

---

### P13. 成本怎么控？这个"最多 10 次调用"是怎么算出来的？

**答（🔗 接项目，这题答得好显得很扎实）：**

三道闸：

| 闸门 | 值 | 作用域 |
| --- | --- | --- |
| 单请求 LLM 调用数 | 10 | 每请求 |
| 单请求 token | 25000 | 每请求 |
| 每日预算熔断 | 500000 | 全局 |

**10 不是拍脑袋，是推导出来的最坏路径：**

```
classify 2 + understand 3 + metric catalog 1 + (answer + reviewer) × 2 = 10
```

**最需要强调的一点**：两套重试是**乘加关系**，且**共用同一个 `LlmBudget`**：

- `app/intent/service.py` 的 `MAX_INTENT_RETRIES = 2` → understand 最坏跑 3 次
- `QUALITY_MAX_ATTEMPTS` → 质量循环每轮最多 2 次模型请求

**任何一边加码都要重算这条路径**，否则预算会先耗尽，
然后以"预算耗尽"的面目暴露成一个看起来像意图识别的问题 —— 排查方向会完全跑偏。

另外，**本地化调用走独立预算**，不挤占问答额度，
`llm_usage.purpose` 分 `AGENT` / `LOCALIZATION` 两条费用曲线分别观测。

---

### P14. 降级怎么设计的？

**答（🔗 项目硬规则 R7）：**

原则一句话：**宁可响亮地崩溃，也不要安静地走错。**

数据库 / 知识库 / LLM / 对象存储不可用时可以降级，但必须在 API 字段和页面上**明确可见**：

```
analysis_sources    分析来源（有序数组，主要来源在前）
thinking_steps      每个节点的处理阶段与耗时
quality_status      PASSED / DEGRADED / FAILED / NOT_RUN
quality_notes       Reviewer 备注（字符串数组，无备注是 [] 不是 null）
degraded            是否降级
degraded_reason     降级原因，分 UPSTREAM / VALIDATION / BUDGET 三类
```

**绝对禁止**：把模拟数据或规则兜底包装成真实模型分析。

配套的设计约束也值得提：

- `analysis_sources` 是**有序数组**而不是单值，`CHAT` / `INVALID` 模式返回 `["NONE"]` ——
  **不为了凑"至少一项"而编造来源**
- `quality_status` 没有 `RETRIED` 状态，重试次数由 `quality_attempts` 单独表达 ——
  状态和计数是两个维度，不该混在一个枚举里

---

# 附：预计会被追问的软性问题

| 问题 | 答法要点 |
| --- | --- |
| 「这个项目是你一个人做的？」 | 是。并且**主动说**这是 AI 协作产出（对应 JD 资格 6 vibe coding）——把项目约束写成 `AGENTS.md` 的 9 条硬规则让 AI 每次读到，规划和实施分离，约束用测试固化 |
| 「你觉得这个项目最大的问题是什么？」 | 挑一个**真问题**：没有真实用户，衡量体系建好了但没有业务数据验证。别说"代码不够优雅"这种虚的 |
| 「如果重做一次，你会改什么？」 | 一开始就接分布式 Trace。现在只有节点耗时和运维端点，跨节点的单请求全链路还原不了 |
| 「你怎么学新东西？」 | 用这个项目举例：从 Java + Vue 的参考实现 1:1 还原成 Python + TypeScript，
先读旧实现和测试理解行为，再在新架构里重写，**不做逐行翻译** |

---

## 最后的提醒

1. **`npm run typecheck` 还有 7 个错误**，别说"全绿"。说"单测和 lint 全绿，typecheck 还有 7 个
   测试辅助函数的泛型推断问题没清"。
2. **B7 九题验收的出口判据尚未达成**（6 条 METRIC 全部零降级）。
   正确说法：「首次零降级的端到端回答 2026-08-18 拿到了，完整验收还差最后一轮复测。」
3. **项目里没有的东西不要编**：`shallowRef`、`provide/inject`、`Teleport`、`watchEffect`、
   `asyncio.TaskGroup`、向量数据库、React —— 这些都是项目里确实没有的。
   被问到就说"没用到，但我知道它解决什么问题"，然后讲原理。
