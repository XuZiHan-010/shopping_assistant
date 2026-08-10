# F4 指标、图表、明细和建议设计

## 目标

把 F3 已经取到但没人渲染的分析数据变成界面：ECharts 图表与无障碍降级、明细表格与 CSV 导出入口、建议面板的换一换，以及至今无人渲染的查询计划摘要。

**阶段契约：F4 只渲染 `ChatAnswer` 里已有的字段，不新增接口调用。** 唯一的例外是 CSV 导出——它走浏览器原生下载，根本不经过 `api/client.ts`。

跨阶段决策见 `docs/superpowers/specs/2026-08-06-frontend-f3-f9-roadmap.md`，本文引用其 A5–A7 编号。

## 范围

渲染 `ChatAnswer` 的四组字段：`chart`（`Visualization`）、`data`（`data_rows` / `total_rows` / `truncated` / `queryPlan`）、`export`（`ExportInfo`）、`suggestions.alternates`。

不做：`GET /api/metrics/{code}` 的调用（理由见 A6）、质量轨迹面板、反馈按钮、附件。后两项属于 F5，附件属于 F7。

已完成不重做：`MetricDefinitionPanel.vue` 与 `RecommendationPanel.vue` 的主体由 F2 交付，F4 只补它们缺的部分——前者补查询计划摘要，后者补换一换。`MetricChartPanel.vue` 是 F2 留的占位，F4 重写。

## 架构

### 三层拆分

```text
src/utils/format.ts     数值、金额、日期、单元格的纯格式化
src/utils/chart.ts      validateChartRows / toChartOption / summarizeChart（纯函数）
src/utils/download.ts   buildExportHref / exportExpiry（纯函数）
        ↑ 全部数据逻辑测试落在这一层
src/composables/useEChart.ts   ECharts 实例生命周期
        ↑ vi.mock('echarts/core')，只断言调用
src/components/insights/   MetricChartPanel / DetailTable / RecommendationPanel
        ↑ 真实渲染只在 Playwright 里断言 <canvas> 存在
```

`happy-dom` 没有 canvas，ECharts 真实渲染在 Vitest 里跑不了。把数据逻辑全部推进纯函数层，是为了让「图表画的对不对」这个问题能被单元测试回答——组件测试只能回答「有没有调用画图」。

### 组件挂载位置

| 组件 | 位置 | 理由 |
| --- | --- | --- |
| `MetricChartPanel.vue` | 左侧栏 | F1/F2 既定 |
| `MetricDefinitionPanel.vue` | 左侧栏 | F1/F2 既定 |
| `RecommendationPanel.vue` | 右侧栏 | F1/F2 既定 |
| `DetailTable.vue` | **中间对话列的助手消息内** | 侧栏只有 230–280px，放不下表格 |

明细表文件仍归 `src/components/insights/`（前端方案 §4 的目录不变），但挂载点在 `ChatMessage.vue`。目录归属反映的是「它属于分析结果这一族」，不是渲染位置。

### ECharts 按需引入

```ts
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([LineChart, BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])
```

`echarts.use()` 写在模块作用域，只执行一次，不放 `onMounted`。

按需引入放在 F4 而非 F6：现在 `echarts` 装了但零 import，一旦有人写 `import * as echarts from 'echarts'`，产物直接多约 1MB，F6 再回头拆是返工，而且那时拆分会牵动所有 e2e 的加载时序。`manualChunks` 也在本阶段配好。

### 实例生命周期

实例存 composable 闭包的 `let` 里，**不用 `ref()`**——Vue 的深代理会污染 ECharts 内部状态；更不进 Pinia（前端方案 §6.1 明令 Store 不存 DOM 与 ECharts 实例）。

- `onMounted` init，容器宽度为 0 时不 init（happy-dom 保护）；
- `watch([answer, currentType])` → `setOption(option, { notMerge: true })`。`notMerge` 是必须的：BAR→PIE 合并会留下上一种图的 series 残骸；
- `onBeforeUnmount` → `ResizeObserver.disconnect()` → `dispose()` → 置空。图表从 `enabled: true` 变 `false` 时同样 dispose，不留隐形实例；
- Resize 用 `ResizeObserver` 观察容器，**不用 `window.resize`**——右侧栏宽度会因抽屉开合和断点变化而变，窗口尺寸不变；回调裹一层 `requestAnimationFrame` 去抖；
- `prefers-reduced-motion: reduce` 时 `option.animation = false`。

## 数据流与状态机

### 后端序列化的两个坑

后端把 Decimal 序列化成**字符串**，日期序列化成 ISO **字符串**。

`toNumber(v): number | null` 解析失败返回 `null`，**绝不返回 0**——0 是合法业务值，把「解析不出来」显示成 0 就是编造数据（AGENTS.md R7）。`null` 点在折线上留断口（`connectNulls: false`），数据表里显示 `—`。

维度轴一律用 `category`，不用 `time`。后端已给出有序的 ISO 字符串，改用 time 轴等于前端重建时区语义，是新增一个出错来源。日期维度只做展示层截断（`MM-DD`），tooltip 给完整值。

### 图表可渲染性

```text
chart.enabled === false                    → 空状态：「本次回答没有可视化数据」
enabled 但 dimensionKey/metricKey 缺失      → 说明：「图表字段缺失，无法绘制」
enabled 但 data 为空                        → 空状态
enabled 且字段齐全                          → 渲染，并始终附 a11y 降级块
```

四条分支都不抛异常（前端方案 §4.2 要求）。`validateChartRows` 返回
`{ renderable: boolean; reason?: string }`，组件据此分支。

后端的类型规则：日期维度 → `type: 'LINE'`、`allowed_types: ['LINE']`；非日期维度 →
`type: 'BAR'`、`allowed_types: ['BAR', 'PIE']`。前端**只在 `allowedTypes` 内提供切换**，
`allowedTypes.length <= 1` 时不渲染切换器。Adapter 过滤未知取值——后端将来加 `SCATTER` 时，
前端应当降级为不可切换而不是崩溃。

### 无障碍降级块

```html
<figure role="group" aria-labelledby="chart-title-x">
  <figcaption id="chart-title-x">{{ chart.title }}</figcaption>
  <div ref="container" aria-hidden="true"></div>
  <p class="chart-summary">{{ summary.sentence }}</p>
  <details><summary>查看数据表</summary><table>…</table></details>
</figure>
```

四项缺一不可（前端方案 §4.2）：标题、汇总数字、趋势文字、可键盘到达的数据表。
`<details>` 原生可键盘到达，不必自己实现折叠。canvas 对辅助技术没有意义，`aria-hidden`。

**降级块的存在不依赖渲染成功**——即使 ECharts 没画出来，摘要和数据表仍在 DOM 里。
组件测试专门断言这一点。

`summarizeChart` 的分支：日期维度且点数 ≥2 → 产出环比句；分类维度 → 产出极值与占比句；
**饼图永不产出趋势句**——饼图没有趋势，硬写就是胡说。首点为 0 时不计算环比，避免 Infinity。

颜色不作为唯一编码：折线配 `symbol` 与区分的 `lineStyle.type`，饼图用
`label.formatter: '{b}: {d}%'` 带引导线，柱图单 series 时颜色本就不编码任何东西。

### 明细表

中文列名由 `src/constants/columnLabels.ts` 映射，**未命中时原样显示后端列名，绝不编造中文**。
编一个看起来合理的中文列名，比显示英文列名危险得多——用户会当真。

截断说明按 `total_rows` 与 `data_rows.length` 渲染：「共 1284 行，已展示前 200 行，
完整数据请下载 CSV」。表内横向滚动（`overflow-x: auto`），页面级不横向滚动。
`<caption>` + `scope="col"` 满足「表格有表头」。

### 导出下载

`ExportInfo.url` 是相对路径且已自带查询串，前端只需前缀 API base。
`buildExportHref` **必须断言 `url` 以 `/api/exports/` 开头**——这是唯一一处把服务端字符串
直接放进 `href` 的地方，不校验就是一个开放重定向面。

410 的解法是**不让它发生**：渲染时算剩余 TTL，未过期显示「下载明细 CSV（链接 12 分钟后过期）」，
已过期换成禁用态 + 「下载链接已过期，重新提问可生成新的导出」。原生下载的状态码本来也拦不住，
而 `expiresAt` 前端已经有。预留 30 秒时钟偏移余量。

没有重签接口，`export_id` 无法单独续期，所以恢复动作是「重新提问」而非「重新生成」。

**跨域时 `download` 属性会被浏览器忽略**，能否触发下载完全取决于后端是否返回
`Content-Disposition: attachment`。F4 开工前先验证。仍然写 `download`（本地 dev 同源时有用），
并加 `target="_blank" rel="noopener"`，这样万一后端返回 410 的 JSON，失败落在新标签页，
不会冲掉 SPA 状态。

### 换一换

在响应携带的 `suggestions.alternates` 内本地轮换，**不发额外请求**（前端方案 §11 明令）。
轮换顺序 `current → alternates[0] → … → current` 循环；`alternates` 为空时不渲染按钮。

**切换 `selectedRoundId` 后轮换下标必须重置**，否则会出现「第 2 轮显示第 1 轮的第 3 组建议」
这种脏状态——侧栏内容跟随当前选中轮次，轮换下标是轮次的局部状态。

## 错误处理

F4 不新增错误码分支。三类失败各自就地降级：

- 图表字段缺失或数据为空 → 空状态与解释，不抛异常；
- 导出链接过期 → 禁用入口 + 重新提问；
- `ChatAnswer.contractWarnings`（F3 Task 4 引入）非空 → 对应面板显示「该回答未提供指标口径」，
  而不是显示零值或空白。

历史消息（`origin === 'history'`）的侧栏显示「历史会话仅保存回答正文，图表、明细与导出需重新
提问获取」，与「这轮回答本来就没有图表」区分开（A8）。

## 测试策略

纯函数层是重点，因为它能回答「画的对不对」：

- `format.ts` 表驱动，必测 `'0'`（必须是 0 不是 `—`）、`''`、`'abc'`、`null`、超长 JSON；
- `chart.ts` 必测字符串 Decimal 转数字、不可解析值保持 `null`、PIE 的摘要不含「趋势」「环比」
  字样、LINE 首点为 0 时不产生 Infinity、未知图表类型被丢弃且不抛；
- `download.ts` 必测相对 URL 拼接、非 `/api/exports/` 前缀被拒、过期判定随 `now` 变化。

组件测试 `vi.mock('echarts/core')`，断言 init 只调一次、类型切换的 `setOption` 第二参含
`notMerge: true`、unmount 触发 `dispose` 与 `disconnect`、**a11y 降级块在 echarts 被 mock 的
情况下仍然存在**。

换一换测试必须断言 transport spy **零调用**——这是「不为换一换发额外请求」的唯一可执行验证。

Mock 传输层需补 `GET /api/exports/{id}` 路由（返回一小段 CSV），否则导出的 e2e 在 Mock 下
无法运行，而 Playwright 强制 `VITE_USE_MOCK=true`。

E2E 覆盖：METRIC 回答出现 `<canvas>` 与数据表、切换图表类型、DETAIL 回答出现表格与截断说明、
下载入口的 `href` 以 API base 开头且含 `signature=`、换一换在本地轮换。

## 边界

不新增运行时依赖（`echarts` 已在 `package.json`）。不调用 `GET /api/metrics/{code}`，
不建 `api/metrics.ts` 与 `adapters/metric.ts`。不做万/亿单位改写——后端声明了 `unit`，
把 `12345.67 元` 显示成 `1.23 万元` 是改写后端给的口径。

不把 ECharts 实例存入 Pinia 或 `ref()`。不在组件里直接消费 `generated.ts`。

不展示「报表」——契约中没有对应字段。查询计划摘要要明确标注为「查询计划摘要」，
**不得把业务口径伪装成 SQL 口径**。
