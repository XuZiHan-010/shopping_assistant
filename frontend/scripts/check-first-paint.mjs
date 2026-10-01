// F6：ECharts 必须留在首屏关键路径之外。
// 这是静态兜底：真正的证据是 e2e/first-paint.spec.ts 的网络观测。
// 两层都留着——e2e 证明行为，本脚本在不跑浏览器的门禁里快速拦回归。
import { readFileSync, readdirSync } from 'node:fs'
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const distDir = join(frontendRoot, 'dist')
const html = readFileSync(join(distDir, 'index.html'), 'utf8')

const echartsChunks = readdirSync(join(distDir, 'assets')).filter(
  (name) => name.startsWith('echarts-') && name.endsWith('.js'),
)

if (echartsChunks.length === 0) {
  console.error('未找到独立的 echarts chunk，manualChunks 配置可能已失效。')
  process.exit(1)
}

const preloaded = echartsChunks.filter((name) => html.includes(name))

if (preloaded.length > 0) {
  console.error(`index.html 仍在首屏预加载 ECharts：${preloaded.join(', ')}`)
  console.error('检查渲染 MetricChartPanel 的组件是否改回了静态导入或无条件渲染。')
  process.exit(1)
}

function findEntryModuleSrc(documentHtml) {
  for (const match of documentHtml.matchAll(/<script\b[^>]*>/gi)) {
    const tag = match[0]
    if (!/\btype\s*=\s*["']module["']/i.test(tag)) continue

    const src = tag.match(/\bsrc\s*=\s*["']([^"']+)["']/i)?.[1]
    if (src) return src
  }

  throw new Error('未在 index.html 中找到入口 module script，无法检查首屏依赖。')
}

function resolveDistModule(pathname) {
  const modulePath = resolve(distDir, pathname)
  const pathFromDist = relative(distDir, modulePath)
  if (pathFromDist.startsWith('..') || isAbsolute(pathFromDist)) {
    throw new Error(`入口依赖越出 dist 目录：${pathname}`)
  }
  return modulePath
}

function staticDependencies(modulePath) {
  const source = readFileSync(modulePath, 'utf8')
  const dependencies = []
  const staticImport = /\b(?:import|export)\s*(?:[\w*$,{}\s]+from\s*)?["']([^"']+)["']/g

  for (const match of source.matchAll(staticImport)) {
    const specifier = match[1]
    if (!specifier.startsWith('.')) continue
    dependencies.push(resolveDistModule(join(dirname(modulePath), specifier.split(/[?#]/, 1)[0])))
  }

  return dependencies
}

function findStaticallyReachableEcharts(entryModule) {
  const pending = [entryModule]
  const visited = new Set()

  while (pending.length > 0) {
    const modulePath = pending.pop()
    if (!modulePath || visited.has(modulePath)) continue
    visited.add(modulePath)

    if (echartsChunks.includes(basename(modulePath))) return modulePath
    pending.push(...staticDependencies(modulePath))
  }

  return undefined
}

const entrySrc = findEntryModuleSrc(html)
const entryModule = resolveDistModule(entrySrc.replace(/^\//, ''))
const staticallyReachableEcharts = findStaticallyReachableEcharts(entryModule)

if (staticallyReachableEcharts) {
  console.error(
    `入口 chunk 通过静态 import 链在首屏加载 ECharts：${basename(staticallyReachableEcharts)}`,
  )
  console.error('检查渲染 MetricChartPanel 的组件是否改回了静态导入或无条件渲染。')
  process.exit(1)
}

// 图表宿主不再固定为某一个页面（v1 `AssistantView` 已下线；W 阶段图表先后出现在
// 运营助手与首页）。逐个检查所有渲染 `MetricChartPanel` 的组件：必须经
// `defineAsyncComponent` 懒加载，且只在 `v-if` 条件满足时挂载。
function listVueFiles(dir) {
  const files = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...listVueFiles(full))
    else if (entry.name.endsWith('.vue')) files.push(full)
  }
  return files
}

const chartHosts = listVueFiles(join(frontendRoot, 'src')).filter((file) =>
  /<MetricChartPanel\b/.test(readFileSync(file, 'utf8')),
)

for (const host of chartHosts) {
  const source = readFileSync(host, 'utf8')
  const label = relative(frontendRoot, host)
  if (/import\s+MetricChartPanel\s+from/.test(source)) {
    console.error(`${label} 静态导入了 MetricChartPanel，ECharts 会进入首屏依赖。`)
    console.error('改用 defineAsyncComponent(() => import(...MetricChartPanel.vue))。')
    process.exit(1)
  }
  const tags = [...source.matchAll(/<MetricChartPanel\b[^>]*>/g)].map((match) => match[0])
  const unguarded = tags.filter((tag) => !/\bv-if\s*=/.test(tag))
  if (unguarded.length > 0) {
    console.error(`${label} 无条件渲染 MetricChartPanel，ECharts loader 会在首次渲染时执行。`)
    process.exit(1)
  }
}

// W Task 8：首页趋势图（`HomeTrendChart`）必须**正向**满足懒加载约定，缺了宿主也算失败——
// 首页是 `/`，它的图表一旦进了首屏，每个商家打开工作台都要先下载 ECharts。
// 约定：宿主用 `defineAsyncComponent(() => import('…/HomeTrendChart.vue'))` 声明组件，
// 挂载条件引用 `useIdleVisible()` 的返回值（浏览器空闲且进入视口之后才为真）。
function fail(message, hint) {
  console.error(message)
  if (hint) console.error(hint)
  process.exit(1)
}

const srcRoot = join(frontendRoot, 'src')
const allVueFiles = listVueFiles(srcRoot)
const trendChartPath = join(srcRoot, 'components', 'home', 'HomeTrendChart.vue')
const idleVisiblePath = join(srcRoot, 'composables', 'useIdleVisible.ts')

let trendChartSource
try {
  trendChartSource = readFileSync(trendChartPath, 'utf8')
} catch {
  fail('未找到 src/components/home/HomeTrendChart.vue：首页趋势图约定的组件不存在。')
}
if (!/from\s+['"]@\/composables\/useEChart['"]/.test(trendChartSource)) {
  fail('HomeTrendChart.vue 没有经 useEChart 渲染，首页趋势图的懒加载检查失去意义。')
}

const idleVisibleSource = readFileSync(idleVisiblePath, 'utf8')
if (!/\bwhenIdle\(/.test(idleVisibleSource) || !/IntersectionObserver/.test(idleVisibleSource)) {
  fail('useIdleVisible 必须同时等待浏览器空闲（whenIdle）与进入视口（IntersectionObserver）。')
}

const trendHosts = allVueFiles.filter((file) =>
  /<HomeTrendChart\b/.test(readFileSync(file, 'utf8')),
)
if (trendHosts.length === 0) {
  fail('没有任何组件渲染 <HomeTrendChart>：首页趋势图的宿主缺失或被改名，门禁拒绝放行。')
}

for (const host of trendHosts) {
  const source = readFileSync(host, 'utf8')
  const label = relative(frontendRoot, host)
  if (/import\s+HomeTrendChart\s+from/.test(source)) {
    fail(
      `${label} 静态导入了 HomeTrendChart，ECharts 会进入首页首屏依赖。`,
      '改用 defineAsyncComponent(() => import(...HomeTrendChart.vue))。',
    )
  }
  const asyncDeclaration =
    /const\s+HomeTrendChart\s*=\s*defineAsyncComponent\(\s*\(\)\s*=>\s*import\(\s*['"][^'"]*HomeTrendChart\.vue['"]\s*\)\s*,?\s*\)/
  if (!asyncDeclaration.test(source)) {
    fail(
      `${label} 没有用 defineAsyncComponent(() => import('…/HomeTrendChart.vue')) 声明首页趋势图。`,
    )
  }
  const gate = source.match(/const\s+(\w+)\s*=\s*useIdleVisible\(/)?.[1]
  if (!gate) {
    fail(`${label} 没有用 useIdleVisible() 推迟首页趋势图的挂载（空闲且进入视口之后）。`)
  }
  const tags = [...source.matchAll(/<HomeTrendChart\b[^>]*>/g)].map((match) => match[0])
  const gated = new RegExp(String.raw`\bv-if\s*=\s*"[^"]*\b${gate}\b[^"]*"`)
  const ungated = tags.filter((tag) => !gated.test(tag))
  if (ungated.length > 0) {
    fail(`${label} 的 <HomeTrendChart> 挂载条件没有引用 ${gate}（useIdleVisible 的返回值）。`)
  }
}

// ECharts 的使用面只允许出现在懒加载的图表组件里：新增的静态使用者会绕过上面的检查。
const echartsUsers = allVueFiles.filter((file) =>
  /from\s+['"]@\/composables\/useEChart['"]|from\s+['"]echarts/.test(readFileSync(file, 'utf8')),
)
const allowedEchartsUsers = new Set([
  trendChartPath,
  join(srcRoot, 'components', 'insights', 'MetricChartPanel.vue'),
])
const unexpectedUsers = echartsUsers.filter((file) => !allowedEchartsUsers.has(file))
if (unexpectedUsers.length > 0) {
  fail(
    `以下组件直接使用 ECharts，未经懒加载约定检查：${unexpectedUsers.map((file) => relative(frontendRoot, file)).join(', ')}`,
    '把图表放进 HomeTrendChart / MetricChartPanel 这类懒加载组件，或同步扩展本脚本的检查。',
  )
}

console.log('入口 chunk 未通过静态 import 链加载 ECharts')
console.log(
  `首页趋势图懒加载且空闲、可见后才挂载：${trendHosts.map((file) => relative(frontendRoot, file)).join(', ')}`,
)
