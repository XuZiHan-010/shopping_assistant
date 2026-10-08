# 图表摘要格式化与 useEChart 时序 · 整改实施计划

> **给执行者（agentic worker）：** 必须配合 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实施。步骤使用 `- [ ]` 复选框语法便于跟踪。

**目标：** 修掉 2026-09-08 code review 在「图表摘要走 formatCell」与「useEChart 挂载时序」这组改动中确认的 1 个显示缺陷、2 处测试盲区和 1 处隐性耦合，并把 `ChartSummary.total` 的精度契约写进代码。

**架构：** 全部改动落在前端 `frontend/src` 的三个既有单元内——`utils/format.ts`（数字展示的唯一入口）、`utils/chart.ts`（摘要文案组织）、`composables/useEChart.ts`（图表实例生命周期）。不新增模块、不改后端契约、不改 `api/generated.ts` 和 `api/mock/fixtures.generated.ts`（两者均为生成产物）。修复策略是「把保障下沉到共享入口」：负零在 `formatCell` 里根治，容器存在性在 `useEChart` 里成为一等信号，而不是在每个调用点各打一个补丁。

**技术栈：** Vue 3.5 + TypeScript 5.9 + Vite 7 + Vitest 3（happy-dom 环境）+ ECharts 6。

**Spec：** 无独立 spec 文档。本计划的需求来源是 2026-09-08 对工作区未提交改动（`frontend/src/utils/chart.ts`、`frontend/src/composables/useEChart.ts` 及三个 spec 文件）所做的 `/code-review`，其 5 条经核实的发现原文记录在下方「一、背景：要修什么」。执行者读本文件即可，无需另找 spec。

---

## Global Constraints

以下约束来自 `AGENTS.md`，适用于本计划**每一个**任务：

- **R1 · 面向用户的内容使用中文。** 代码注释、测试用例名、提交信息一律中文；代码标识符保持英文。
- **R2 · 未经用户明确许可，不执行 Git 发布操作。** 每个任务末尾的「提交」步骤**必须先向用户口头确认**才能执行 `git commit`；未获许可时只把改动留在工作区并如实报告。禁止 `git reset --hard`、`git clean`、`git push`、`git tag`。
- **R3 · 真实 LLM 调用必须先说明成本。** 本计划全程不触碰 LLM、不启动后端、不联网，无费用。
- **R8 · 参考项目 `yshopping-merchant-ai 4/` 只读。** 本计划不读写该目录。
- **生成产物禁止手改：** `frontend/src/api/generated.ts`、`frontend/src/api/mock/fixtures.generated.ts`。本计划的测试改动**只改断言，不改 fixture**。
- **数字展示约定：** 全站数字统一走 `formatCell`，固定 `maximumFractionDigits: 2`。这是刻意的展示约定（与明细表一致），不是本次要推翻的东西。
- **测试命令：** 工作目录 `frontend/`，单文件 `npm run test -- <相对路径>`，全量 `npm run test`。类型检查 `npm run typecheck`，Lint `npm run lint`。

---

## 一、背景：要修什么

被审查的改动做了两件事，方向都对，但留下了下列问题：

| # | 严重度 | 问题 | 位置 |
| --- | --- | --- | --- |
| 1 | 中 | 为消除浮点尾数改用 `formatCell`，却引入了新的负零显示：`Intl.NumberFormat` 把 `-0` 和四舍五入后归零的小负数（如 `-0.001`）都输出成 `"-0"`，而旧的裸插值 `${-0}` 输出的是 `"0"` | `frontend/src/utils/format.ts:28`（经 `chart.ts:116/145` 暴露） |
| 2 | 低 | `ChartSummary.total` 仍是未格式化的原始浮点值，与已格式化的 `sentence` 构成两套精度语义，却没有任何类型或注释提示「展示前必须走 `formatCell`」 | `frontend/src/utils/chart.ts:21-24` |
| 3 | 中 | 摘要有三个分支都用 `totalText`，但只有 LINE 环比分支有能失败的测试；PIE 分支和默认分支的「合计」被还原成裸插值也不会有任何测试报警 | `frontend/src/utils/chart.spec.ts:55,95`、`frontend/src/components/insights/InsightPanels.spec.ts:89` |
| 4 | 中 | `TrendChart.vue` 与 `MetricChartPanel.vue` 用的是同一个「容器藏在 `v-if` 后、与 option 同批出现」模式，但 `TrendChart.spec.ts` 整体 mock 掉了 `useEChart`，这次 `flush: 'post'` 修复在该调用点零覆盖 | `frontend/src/components/analytics/TrendChart.spec.ts:6-10` |
| 5 | 低 | `useEChart` 把 `enabled` 当作「容器已挂载」的代理信号，没有独立校验容器是否存在。今天靠 `validateChartRows` 让两者恰好同步才安全，这个不变量没有任何地方记录；一旦解耦，`render()` 会走 `!element` 分支静默 `dispose()`，无报错无日志无重试 | `frontend/src/composables/useEChart.ts:40-43,63` |

**已验证的事实**（执行者不必重新验证，但改动后要靠测试守住）：

```text
node v24：
new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(-0)      // "-0"
new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(-0.001)  // "-0"
String(-0)                                                               // "0"   ← 旧行为
1234.5 + 0.1        // 1234.6            → formatCell → "1,234.6"
60000.1 + 40000.2   // 100000.29999999999 → formatCell → "100,000.3"
0.1 + 0.2           // 0.30000000000000004
```

**明确不做的事**（避免执行者顺手扩大范围）：

- 不取消 `maximumFractionDigits: 2` 的精度上限。摘要与明细表共用一套格式是这次改动的目的；是否为高精度指标放开小数位是独立的产品决策，不在本计划内，任务 2 只把它写成显式注释。
- 不给 `ChartSummary` 增加 `totalText` 字段。目前没有消费方（`MetricChartPanel` 只用 `sentence`），加了就是投机性 API；任务 2 用类型注释表达同一个约束。
- 不重构 `points()` 在 `toChartOption` / `summarizeChart` 里各算一遍的重复。finder 提过，但那是常数级开销、无正确性风险，改它会扩大 diff 且需要动 `MetricChartPanel` 的 computed 结构，收益不匹配。

---

## 二、文件结构

| 文件 | 本计划中的职责 | 任务 |
| --- | --- | --- |
| `frontend/src/utils/format.ts` | 数字/日期/布尔的展示唯一入口。负零在这里根治，明细表和图表摘要一并受益 | 1 |
| `frontend/src/utils/format.spec.ts` | `formatCell` 的行为契约测试，新增负零与负数用例 | 1 |
| `frontend/src/utils/chart.ts` | 摘要文案组织。只加 `ChartSummary` 的精度契约注释，不改逻辑 | 2 |
| `frontend/src/utils/chart.spec.ts` | 补齐 PIE 分支与默认分支「合计」的可失败断言 | 2 |
| `frontend/src/components/insights/InsightPanels.spec.ts` | 把单点 fixture 下无法区分的断言改成按子句断言 | 2 |
| `frontend/src/components/analytics/TrendChart.timing.spec.ts` | **新建。** 用真实 `useEChart` 覆盖 TrendChart 的 `v-if` 挂载时序 | 3 |
| `frontend/src/composables/useEChart.ts` | 把容器存在性提升为独立的渲染触发信号 | 4 |
| `frontend/src/composables/useEChart.spec.ts` | 覆盖「容器晚于 enabled 出现」的解耦场景 | 4 |

为什么任务 3 要新建文件而不是加进 `TrendChart.spec.ts`：该文件顶部的 `vi.mock('@/composables/useEChart', ...)` 是 hoisted 的，对整个文件生效，同一文件里拿不到真实实现。

---

## 三、任务

### Task 1：`formatCell` 不再输出负零

**Files:**
- Modify: `frontend/src/utils/format.ts:20-34`
- Test: `frontend/src/utils/format.spec.ts:15-30`

**Interfaces:**
- Consumes: 无（本计划第一个任务）。
- Produces: `formatCell(value: unknown, unit?: string): string` 的强化契约——对任何在 2 位小数精度下归零的值（`-0`、`-0.001`、`0`），输出恒为不带负号的 `"0"`（有 `unit` 时为 `"0 <unit>"`）；非零负数的负号保持不变。任务 2 的断言依赖这一点。

- [ ] **步骤 1：写会失败的测试**

在 `frontend/src/utils/format.spec.ts` 的 `describe('formatCell', ...)` 内、`it('不会让超长 JSON 撑破单元格', ...)` **之前**插入：

```ts
  it('不把负零或四舍五入归零的小负数显示成 -0', () => {
    // Intl.NumberFormat 对 -0 和 -0.001 都输出 "-0"，那是个业务上不存在、
    // 用户也读不懂的负零；旧的裸插值 `${-0}` 反而是对的（"0"）。
    expect(formatCell(-0)).toBe('0')
    expect(formatCell(-0.001, '元')).toBe('0 元')
  })

  it('保留真实负数的负号', () => {
    expect(formatCell(-1.5, '元')).toBe('-1.5 元')
    expect(formatCell(-1234.56)).toBe('-1,234.56')
  })
```

- [ ] **步骤 2：运行测试确认它失败**

```powershell
cd frontend
npm run test -- src/utils/format.spec.ts
```

预期：`不把负零...` 用例 FAIL，报 `expected '-0' to be '0'`；`保留真实负数的负号` 用例 PASS（它是防止过度修复的护栏，本来就该通过）。

- [ ] **步骤 3：写最小实现**

在 `frontend/src/utils/format.ts` 顶部常量区（`const MAX_CELL_LENGTH = 160` 之后）加：

```ts
// Intl 会把 -0 以及四舍五入后归零的小负数（-0.001）输出成 "-0"。
const NEGATIVE_ZERO = /^-0(?:\.0+)?$/
```

把 `formatCell` 中的数字分支（当前 27-30 行）替换为：

```ts
  if (numeric !== null) {
    const formatted = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numeric)
    // 去掉负零的符号，而不是改用 signDisplay: 'negative'——后者是 Intl.NumberFormat v3
    // 选项，在低于 Firefox 116 的浏览器上会直接抛 RangeError，而本函数是明细表每个
    // 数字单元格的必经之路，崩在这里等于整张表白屏。
    const safe = NEGATIVE_ZERO.test(formatted) ? formatted.slice(1) : formatted
    return unit ? `${safe} ${unit}` : safe
  }
```

- [ ] **步骤 4：运行测试确认通过**

```powershell
npm run test -- src/utils/format.spec.ts
```

预期：该文件全部 PASS。

- [ ] **步骤 5：跑全量测试，确认没有别处依赖旧的负零输出**

```powershell
npm run test
npm run typecheck
npm run lint
```

预期：全部 PASS。若有用例因此失败，先读那条用例判断它断言的是不是「负零」这个错误行为，**不要**为了让它变绿而回退本任务的修复。

- [ ] **步骤 6：提交（需先获得用户明确许可，见 Global Constraints R2）**

```bash
git add frontend/src/utils/format.ts frontend/src/utils/format.spec.ts
git commit -m "fix: 数字展示不再输出负零"
```

---

### Task 2：补齐摘要三个分支的「合计」回归覆盖，并写明 total 的精度契约

**Files:**
- Modify: `frontend/src/utils/chart.ts:21-24`（仅加注释）
- Modify: `frontend/src/utils/chart.spec.ts:54-111`
- Modify: `frontend/src/components/insights/InsightPanels.spec.ts:84-91`

**Interfaces:**
- Consumes: Task 1 的 `formatCell` 契约（负零已消除；`1234.6 → "1,234.6"`、`100000.29999999999 → "100,000.3"`、`128000.5 → "128,000.5"`）。
- Produces: 无新导出。`ChartSummary` 的字段与类型保持不变：`{ total: number; sentence: string }`。

**背景（执行者必读）：** `summarizeChart` 有三条返回路径，都用同一个 `totalText`：

- PIE 分支（`chart.ts:122-128`）
- LINE 环比分支（`chart.ts:130-140`）——**已有**能失败的测试（`合计不把浮点误差尾数写进摘要`），本任务不动它
- 默认分支（`chart.ts:142-147`）

现有测试对 PIE 与默认分支的「合计」都测不到：PIE 的 fixture 合计恰好是整数 `100`（无千分位、无浮点尾数，格式化前后一模一样），默认分支的用例只断言了「最高值」那一半。`InsightPanels` 的 fixture 只有一个数据点，导致 `total === top.value`，单个 `'128,000.5'` 子串同时能被两个调用点满足。**解法是按子句断言**（连「合计 」「为最高值 」前缀一起断言），这样即使两处数值相同也能分别失败。

- [ ] **步骤 1：改写 chart.spec.ts 的 PIE 用例，让它能测出「合计」被还原**

把 `frontend/src/utils/chart.spec.ts` 中 `it('饼图摘要只讲占比，不编造趋势或环比', ...)` 整段（当前 55-73 行）替换为：

```ts
  it('饼图摘要只讲占比，不编造趋势或环比', () => {
    const summary = summarizeChart(
      {
        ...trendChart,
        allowedTypes: ['BAR', 'PIE'],
        type: 'BAR',
        dimensionKey: 'category',
        // 取值刻意让合计同时带千分位和浮点尾数（60000.1 + 40000.2 =
        // 100000.29999999999）；整数合计看不出格式化有没有生效。
        data: [
          { category: '食品', gmv: '60000.1' },
          { category: '家居', gmv: '40000.2' },
        ],
      },
      'PIE',
    )

    // total 是未格式化的原始求和，展示精度只体现在 sentence 上。
    expect(summary.total).toBe(60000.1 + 40000.2)
    expect(summary.sentence).toContain('合计 100,000.3 元')
    expect(summary.sentence).not.toContain('100000.29999999999')
    expect(summary.sentence).toContain('食品')
    expect(summary.sentence).not.toMatch(/趋势|环比/)
  })
```

- [ ] **步骤 2：改写默认分支用例，让「合计」和「最高值」各自可失败**

把同文件中 `it('最高值与明细表用同一套数字格式', ...)` 整段（当前 95-110 行）替换为：

```ts
  it('合计与最高值都走明细表那套数字格式', () => {
    const summary = summarizeChart(
      {
        ...trendChart,
        allowedTypes: ['BAR'],
        type: 'BAR',
        data: [
          { business_date: '2026-08-01', gmv: '1234.5' },
          { business_date: '2026-08-02', gmv: '0.1' },
        ],
      },
      'BAR',
    )

    // 两个数值不同、且都带千分位：任一调用点被还原成裸插值都会让对应断言失败。
    expect(summary.sentence).toContain('合计 1,234.6 元')
    expect(summary.sentence).toContain('为最高值 1,234.5 元')
  })
```

- [ ] **步骤 3：运行这两条用例，确认它们此刻通过（当前实现是对的）**

```powershell
cd frontend
npm run test -- src/utils/chart.spec.ts
```

预期：全部 PASS。这两条是**回归护栏**，不是红灯用例——当前实现本来就正确，要验证的是「它们能在实现变坏时失败」，见步骤 4。

- [ ] **步骤 4：手工变异验证（关键步骤，不可跳过）**

依次把两处「合计」临时还原成裸插值，确认对应用例会红。先改 `frontend/src/utils/chart.ts:126`（PIE 分支）：

```ts
      sentence: top ? `合计 ${total} 元，${top.label} 占比 ${share}%。` : '没有可汇总的数据。',
```

重跑 `npm run test -- src/utils/chart.spec.ts`，确认 PIE 用例 **FAIL**（期望 `合计 100,000.3 元`，实际 `合计 100000.29999999999 元`），然后改回 `totalText` 那一版。

再对 `chart.ts:145`（默认分支）做同样的临时还原：

```ts
      ? `合计 ${total} 元，${top.label} 为最高值 ${formatCell(top.value, chart.unit)}。`
```

确认「合计与最高值都走明细表那套数字格式」用例 **FAIL**，然后改回。

若某次变异后测试仍然全绿，说明断言写得不够紧，回到步骤 1/2 修断言，**不要**继续往下走。

结束后确认两处临时改动都已还原：

```powershell
git diff -- src/utils/chart.ts
```

预期：只剩被审查那次改动本身（`formatCell` 的 import、`totalText` 及其注释、三个分支的插值），**没有**任何裸 `${total}` 残留。注意 `chart.ts` 本来就带着未提交的改动，这里不是期望空输出。

- [ ] **步骤 5：把 total 的精度契约写进类型定义**

把 `frontend/src/utils/chart.ts:21-24` 的 `ChartSummary` 替换为：

```ts
export interface ChartSummary {
  /**
   * 未格式化的原始求和值，可能带浮点误差尾数（0.1 + 0.2 = 0.30000000000000004）。
   * 它存在是为了参与计算（占比等），任何要展示给用户的地方都必须先过
   * `formatCell`，否则就会把误差尾数写回页面——`sentence` 已经这么做了。
   */
  total: number
  /** 已按明细表同一套格式（zh-CN 千分位、最多 2 位小数）渲染好的摘要文案。 */
  sentence: string
}
```

- [ ] **步骤 6：按子句断言 InsightPanels 的摘要**

把 `frontend/src/components/insights/InsightPanels.spec.ts` 中 `it('后端提供 visualization 时展示图表摘要', ...)` 整段（当前 84-91 行）替换为：

```ts
  it('后端提供 visualization 时展示图表摘要', () => {
    const wrapper = mount(MetricChartPanel, { props: { answer: metricAnswer } })
    const summary = wrapper.get('[data-testid="chart-summary"]').text()

    // fixture 只有一个数据点，合计与最高值数值相同，单断言一个 '128,000.5'
    // 分不清是哪个调用点产生的；连子句前缀一起断言才能各自失败。
    expect(summary).toContain('合计 128,000.5 元')
    expect(summary).toContain('为最高值 128,000.5 元')
    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(false)
  })
```

注意：`metricAnswer` 来自 `CHAT_FIXTURES.metricGmv`（生成产物），**不要修改 fixture**。

- [ ] **步骤 7：跑全量测试与静态检查**

```powershell
npm run test
npm run typecheck
npm run lint
```

预期：全部 PASS。

- [ ] **步骤 8：提交（需先获得用户明确许可）**

```bash
git add frontend/src/utils/chart.ts frontend/src/utils/chart.spec.ts frontend/src/components/insights/InsightPanels.spec.ts
git commit -m "test: 补齐图表摘要合计的回归覆盖并写明 total 精度契约"
```

---

### Task 3：TrendChart 用真实 useEChart 覆盖挂载时序

**Files:**
- Create: `frontend/src/components/analytics/TrendChart.timing.spec.ts`
- Test: 同上（本任务只加测试，不改产品代码）

**Interfaces:**
- Consumes: `useEChart(container, option, enabled)` 的现有行为（`flush: 'post'` 已在被审查的改动中就位）；`TrendChart.vue` 的 props 类型 `{ daily: ChatBiDailyPoint[] }`。
- Produces: 无导出。为 Task 4 提供一层保险——Task 4 改 `useEChart` 的 watch 源之后，这条用例必须仍然通过。

**背景：** `TrendChart.vue:52-56` 用 `enabled = computed(() => option.value !== undefined)`，模板 `v-if="option"`（第 66 行）——与 `MetricChartPanel` 完全相同的模式，即容器和 option 在同一次更新里出现。`TrendChart.spec.ts:6-10` 用 `vi.mock` 把 `useEChart` 整个替换掉了，所以这个调用点对时序问题完全无感。`vi.mock` 是 hoisted、文件级生效的，因此必须新建文件才能拿到真实实现。

- [ ] **步骤 1：写会失败的测试（新建文件）**

创建 `frontend/src/components/analytics/TrendChart.timing.spec.ts`：

```ts
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// 同目录的 TrendChart.spec.ts 用 vi.mock 顶掉了 useEChart，而 vi.mock 是文件级
// 生效的；要验证真实 composable 的挂载时序，只能另开一个文件。
const echartsMock = vi.hoisted(() => {
  const chartInstance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  return { chartInstance, init: vi.fn(() => chartInstance) }
})

vi.mock('echarts/core', () => ({ init: echartsMock.init, use: vi.fn() }))

import type { ChatBiDailyPoint } from '@/types/analytics'

import TrendChart from './TrendChart.vue'

class ResizeObserverStub {
  disconnect = vi.fn()
  observe = vi.fn()
}

const point: ChatBiDailyPoint = {
  statDate: '2026-08-20',
  answerTotal: 8,
  metrics: {
    adoptionRate: 0.4,
    userAccuracyRate: null,
    systemAccuracyRate: 0.8,
    avgThinkingMs: 2100,
    hitRate: 0.9,
    failureRate: 0,
  },
}

describe('TrendChart 与真实 useEChart 的挂载时序', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.chartInstance.setOption.mockClear()
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 320 })
  })

  it('daily 迟到时容器与 option 同批出现，仍会初始化图表', async () => {
    // TrendChart 的容器在 `v-if="option"` 后面，enabled 也由同一个 option 推导：
    // 首帧没有数据、随后接口返回，正是线上会走的那条路径。
    const wrapper = mount(TrendChart, { props: { daily: [] as ChatBiDailyPoint[] } })

    expect(echartsMock.init).not.toHaveBeenCalled()

    await wrapper.setProps({ daily: [point] })
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.chartInstance.setOption).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **步骤 2：确认它现在通过（修复已在工作区），并确认它真的能失败**

```powershell
cd frontend
npm run test -- src/components/analytics/TrendChart.timing.spec.ts
```

预期：PASS。

然后临时把 `frontend/src/composables/useEChart.ts:63` 的 `watch([option, enabled], render, { flush: 'post' })` 改回 `watch([option, enabled], render)`，重跑上面的命令，确认 **FAIL**（`init` 调用次数为 0）。确认后改回 `{ flush: 'post' }`。

若去掉 `flush: 'post'` 后测试仍然通过，说明这条用例没有真正复现时序问题，回到步骤 1 检查 harness，**不要**继续往下走。

- [ ] **步骤 3：确认 useEChart.ts 已还原**

```powershell
git diff -- src/composables/useEChart.ts
```

预期：仍是被审查改动的那一版（`{ flush: 'post' }` 在位），没有步骤 2 的临时改动残留。

- [ ] **步骤 4：跑全量测试与静态检查**

```powershell
npm run test
npm run typecheck
npm run lint
```

预期：全部 PASS。

- [ ] **步骤 5：提交（需先获得用户明确许可）**

```bash
git add frontend/src/components/analytics/TrendChart.timing.spec.ts
git commit -m "test: 覆盖 TrendChart 容器与 option 同批出现的挂载时序"
```

---

### Task 4：把容器存在性提升为 useEChart 的独立渲染信号

**Files:**
- Modify: `frontend/src/composables/useEChart.ts:58-64`
- Test: `frontend/src/composables/useEChart.spec.ts`（在文件末尾追加用例）

**Interfaces:**
- Consumes: Task 3 新建的 `TrendChart.timing.spec.ts`（改完必须仍然绿）。
- Produces: `useEChart(container, option, enabled)` 的强化契约——`container` 从「被动读取的引用」变成 watch 源之一。只要容器出现（无论 `option`/`enabled` 是否在同一批变化），`render()` 都会被重新触发；容器消失时同样会触发并走 `dispose()`。签名与返回值不变，调用方无需改动。

**背景：** 当前 `render()`（`useEChart.ts:40-46`）把 `enabled.value` 当作「容器已挂载」的代理信号。这在今天是安全的，因为 `MetricChartPanel` 的 `enabled`（`computed(() => validation.value.renderable)`）与容器的 `v-if="validation.renderable && chart"` 恒等——`validateChartRows` 在 `chart` 为空时一定返回 `renderable: false`，所以 `&& chart` 其实是冗余条件。但这个不变量没有任何地方记录，也没有测试守着。一旦哪天给 `v-if` 加一个与 `enabled` 无关的条件，`enabled` 会在容器仍为 `null` 的那一帧变成 `true`，`render()` 从 `!element` 处返回并 `dispose()`，此后**再无任何重试时机**（`ResizeObserver` 只在 `init` 成功的分支里才挂上），表现为图表永远不出现、无报错、无日志，和「本来就没有图表」完全无法区分。

把 `container` 加进 watch 源即可让容器自己说话，同时也让 `flush: 'post'` 不再是唯一的救命稻草。

- [ ] **步骤 1：写会失败的测试**

在 `frontend/src/composables/useEChart.spec.ts` 的 `describe('useEChart', ...)` 末尾（当前第 80 行的 `})` 之后、第 81 行的 `})` 之前）追加：

```ts

  it('容器晚于 enabled 出现时补上初始化，而不是静默放弃', async () => {
    // 这里刻意让容器由一个与 enabled 无关的条件控制：enabled 早已为 true，
    // 容器在后面的某一帧才挂上。今天 MetricChartPanel 两者恒等所以碰不到，
    // 但 composable 不该依赖调用方维持这个不变量——依赖一旦破，图表会永远
    // 不出现且没有任何报错。
    const chartOption = ref<ChartOption | undefined>(option)
    const enabled = ref(true)
    const containerReady = ref(false)

    const Harness = defineComponent({
      setup() {
        const element = ref<HTMLElement | null>(null)
        useEChart(element, chartOption, enabled)
        return () => (containerReady.value ? h('div', { ref: element }) : h('p', '容器还没到'))
      },
    })

    mount(Harness)
    await nextTick()
    expect(echartsMock.init).not.toHaveBeenCalled()

    containerReady.value = true
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.chartInstance.setOption).toHaveBeenCalledWith(option, { notMerge: true })
  })
```

- [ ] **步骤 2：运行测试确认它失败**

```powershell
cd frontend
npm run test -- src/composables/useEChart.spec.ts
```

预期：新用例 FAIL，报 `expected "spy" to be called 1 times, but got 0 times`。原因就是 `option` 和 `enabled` 都没变，没有任何东西再触发 `render()`。

- [ ] **步骤 3：写最小实现**

把 `frontend/src/composables/useEChart.ts:58-64` 替换为：

```ts
  onMounted(render)
  // 三个源都要盯：容器是 `v-if` 的子节点（见 MetricChartPanel、TrendChart），
  // 它自己出现或消失就是渲染时机，不能靠 enabled 代劳——两者只是在今天恰好同步。
  // flush 必须是 post：首个带图表的回答会让 option 和容器在同一次更新里出现，
  // 默认的 pre 会在 DOM 打补丁之前触发，此时 container.value 还是 null。
  watch([option, enabled, container], render, { flush: 'post' })
  onBeforeUnmount(dispose)
```

- [ ] **步骤 4：运行测试确认通过**

```powershell
npm run test -- src/composables/useEChart.spec.ts
```

预期：该文件全部 PASS，包括原有的「用 notMerge 更新图表，并在卸载时释放实例」（该用例断言 `dispose` 恰好被调用 1 次——组件卸载时 setup 作用域内的 watcher 会先被停止，容器置空不会额外触发 `render()`，所以计数不变）。

- [ ] **步骤 5：跑全量测试与静态检查**

```powershell
npm run test
npm run typecheck
npm run lint
```

预期：全部 PASS，Task 3 新建的 `TrendChart.timing.spec.ts` 仍然绿。

- [ ] **步骤 6：提交（需先获得用户明确许可）**

```bash
git add frontend/src/composables/useEChart.ts frontend/src/composables/useEChart.spec.ts
git commit -m "fix: useEChart 把容器出现本身作为渲染时机"
```

---

## 四、完成标准（Definition of Done）

四个任务全部完成后，逐条确认并**贴出实际命令输出**，不允许仅凭印象声明通过：

- [ ] `cd frontend && npm run test` 全绿
- [ ] `npm run typecheck` 无错误
- [ ] `npm run lint` 无错误
- [ ] `npm run format:check` 通过（若失败，跑 `npm run format` 后重跑测试）
- [ ] `git status` 中没有对 `frontend/src/api/generated.ts`、`frontend/src/api/mock/fixtures.generated.ts` 的改动
- [ ] Task 2 步骤 4、Task 3 步骤 2 的变异验证都做过，且临时改动均已还原（`git diff` 复核）
- [ ] 按 `AGENTS.md` §十七 更新 `docs/project-progress.md` 的日期、最近验证结果与下一步

**不需要**改动的东西（若发现自己在改，说明跑偏了）：后端任何文件、`docs/api.md`、OpenAPI 契约、`AGENTS.md`、`docs/PRD.md`。本计划纯前端展示层与测试，不触碰任何接口契约。

---

## 五、自查记录

按 `superpowers:writing-plans` 的要求，计划写完后对照来源做了三项自查：

**1. 需求覆盖** —— 背景表 5 条发现对应：#1 → Task 1；#2 → Task 2 步骤 5；#3 → Task 2 步骤 1/2/6；#4 → Task 3；#5 → Task 4。无遗漏。另有 3 条 finder 提出但经核实判定不做的项（精度上限、`ChartSummary.totalText`、`points()` 重复计算），已在「一、背景」末尾写明理由，不留悬念。

**2. 占位符扫描** —— 无 TBD / TODO / 「类似 Task N」/「补充适当的错误处理」。每个代码步骤都给了可直接粘贴的完整代码块，每个运行步骤都给了确切命令与预期输出。

**3. 类型一致性** —— 全程未引入新类型或新函数签名。`ChartSummary` 字段仍为 `total: number` / `sentence: string`（Task 2 只加 JSDoc）；`useEChart(container, option, enabled)` 参数与返回值不变（Task 4 只改 watch 源）；`ChatBiDailyPoint` 的字段取自 `TrendChart.spec.ts` 现有 fixture，与 `@/types/analytics` 一致。Task 2 断言里的期望字符串（`1,234.6`、`100,000.3`、`128,000.5`）均已用 node 实测 `Intl.NumberFormat` 输出核对过，非推算。
