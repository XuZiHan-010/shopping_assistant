#!/usr/bin/env node
/**
 * fixture 镜像生成。
 *
 * 源是 docs/fixtures/chat/*.json（后端 scripts/export_chat_fixtures.py 产出）。
 * Railway 的 frontend service Root Directory 是 /frontend，Docker 构建上下文没有
 * docs/，所以应用代码不能用 @fixtures 别名直接导入源文件，只能消费提交进仓库的镜像。
 *
 * 生成 as const satisfies ChatResponse：JSON 导入会把 answer_mode 推断成 string
 * 而无法满足枚举，as const 可以。于是后端改 schema 时 generated.ts 跟着变，
 * 镜像会在 typecheck 阶段失败，比逐字节比对更早暴露。
 *
 * 拼出来的对象字面量再经 prettier 格式化一遍：手写缩进无法逐字节匹配
 * `npm run format:check`（引号风格、quoteProps、数组折行都由 prettier 决定），
 * 直接复用仓库已有的 prettier devDependency 走一遍最省事，也让生成脚本与
 * 漂移检查脚本共用同一个 renderModule()，两边天然自洽。
 */
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { format, resolveConfig } from 'prettier'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const sourceDir = resolve(frontendRoot, '..', 'docs', 'fixtures', 'chat')
const outPath = resolve(frontendRoot, 'src', 'api', 'mock', 'fixtures.generated.ts')

function toCamel(fileName) {
  return fileName.replace(/\.json$/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase())
}

export async function renderModule() {
  const files = readdirSync(sourceDir)
    .filter((f) => f.endsWith('.json'))
    .sort()
  const entries = files.map((file) => {
    const raw = JSON.parse(readFileSync(resolve(sourceDir, file), 'utf8'))
    return `  ${toCamel(file)}: ${JSON.stringify(raw)},`
  })

  const source = [
    '/**',
    ' * 本文件由 npm run fixtures 生成，请勿手改。',
    ' * 源：docs/fixtures/chat/*.json（后端 FakeAgent 真实输出）。',
    ' * 漂移检查：npm run fixtures:check。',
    ' */',
    "import type { components } from '@/api/generated'",
    '',
    "type ChatResponse = components['schemas']['ChatResponse']",
    '',
    'export const CHAT_FIXTURES = {',
    ...entries,
    '} as const satisfies Record<string, ChatResponse>',
    '',
    'export type ChatFixtureKey = keyof typeof CHAT_FIXTURES',
    '',
  ].join('\n')

  const config = (await resolveConfig(outPath)) ?? {}
  return format(source, { ...config, filepath: outPath })
}

async function main() {
  writeFileSync(outPath, await renderModule(), 'utf8')
  console.log(`已生成 ${outPath}`)
}

// Windows 上 `file://${process.argv[1]}` 拼不出合法的 file URL（盘符、反斜杠），
// import.meta.url 与之比较必然为 false，"是否作为主模块运行" 的判断会失效。
// 改成两边都转成普通文件系统路径再比较，跨平台稳定。
const isMainModule = fileURLToPath(import.meta.url) === resolve(process.argv[1] ?? '')
if (isMainModule) {
  await main()
}
