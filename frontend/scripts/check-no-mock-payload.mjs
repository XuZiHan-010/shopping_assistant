#!/usr/bin/env node
/**
 * 生产产物不得包含 fixture 载荷。
 *
 * resolveTransport 用动态 import 加环境变量守卫把 Mock 挡在生产之外，这个脚本
 * 是那道守卫的验收：守卫一旦失效（比如有人把 mock/transport 改成静态 import），
 * 整包演示数据就会进产物。
 *
 * 为什么不是一句 grep「昨天总 GMV」：快速问题现在是 src/constants/ 的产品文案，
 * Mock 场景反向消费它，因此该文本可以合法进入生产包。用它当判据只会稳定误报，
 * 然后被人当噪音关掉。改为从 fixture 的 answer 正文里取判据——那些字符串只可能
 * 来自 fixtures.generated.ts。
 *
 * 与 fixtures:check 一样只进本地门禁与 CI：Railway 的 Docker 构建上下文没有 docs/。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const fixtureDir = resolve(frontendRoot, '..', 'docs', 'fixtures', 'chat')
const distDir = resolve(frontendRoot, 'dist')

/** 取 answer 正文的一小段当判据：足够长到不会与应用文案偶然相同。 */
function markers() {
  return readdirSync(fixtureDir)
    .filter((file) => file.endsWith('.json'))
    .map((file) => {
      const payload = JSON.parse(readFileSync(join(fixtureDir, file), 'utf8'))
      return { file, marker: String(payload.answer).slice(0, 24) }
    })
}

function assetFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return assetFiles(full)
    return /\.(js|css|html)$/.test(entry) ? [full] : []
  })
}

let leaked = false

for (const file of assetFiles(distDir)) {
  const content = readFileSync(file, 'utf8')
  for (const { file: fixture, marker } of markers()) {
    if (!content.includes(marker)) continue
    console.error(`${file} 含 ${fixture} 的回答正文：${marker}`)
    leaked = true
  }
}

if (leaked) {
  console.error(
    '\n生产产物包含 fixture 载荷。\n' +
      '说明 resolveTransport 的动态 import 守卫失效了，请修守卫而不是删这个检查。\n',
  )
  process.exit(1)
}

console.log('生产产物不含 fixture 载荷')
