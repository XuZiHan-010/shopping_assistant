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
  console.error('检查 AssistantView.vue 是否把 MetricChartPanel 改回了无条件渲染。')
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
  console.error('检查 AssistantView.vue 是否把 MetricChartPanel 改回了无条件渲染。')
  process.exit(1)
}

const assistantView = readFileSync(join(frontendRoot, 'src', 'views', 'AssistantView.vue'), 'utf8')
if (!/<MetricChartPanel\b[^>]*\bv-if\s*=\s*["']chartMountable["']/.test(assistantView)) {
  console.error('首屏图表未使用 chartMountable 控制挂载，ECharts loader 会在首次渲染时执行。')
  console.error('检查 AssistantView.vue 是否把 MetricChartPanel 改回了无条件渲染。')
  process.exit(1)
}

console.log('入口 chunk 未通过静态 import 链加载 ECharts')
