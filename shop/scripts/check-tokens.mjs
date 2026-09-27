#!/usr/bin/env node
/**
 * 设计 token / logo 副本漂移检查。
 *
 * Railway 的 shop Root Directory 是 /shop，构建上下文里没有 ../frontend，所以副本必须提交进仓库；
 * 代价是它可能与商家端脱节而无人察觉。本脚本逐字节（忽略换行风格）比对副本与来源。
 * 纳入本地门禁与 CI，**不要**纳入 Docker 构建。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const pairs = [
  ['frontend/src/assets/tokens.css', '../frontend/src/assets/tokens.css', 'src/styles/tokens.css'],
  ['frontend/public/borough-logo.svg', '../frontend/public/borough-logo.svg', 'public/borough-logo.svg'],
]

const normalize = (text) => text.replace(/\r\n/g, '\n')
let stale = false

for (const [label, upstreamPath, copyPath] of pairs) {
  const upstream = normalize(readFileSync(resolve(root, upstreamPath), 'utf-8'))
  const copy = normalize(readFileSync(resolve(root, copyPath), 'utf-8'))
  if (upstream !== copy) {
    console.error(`${copyPath} 已过期（来源 ${label}）`)
    stale = true
  }
}

if (stale) {
  console.error('设计 token / logo 副本已过期：运行 npm run tokens:sync')
  process.exit(1)
}
console.log('token 与 logo 副本与商家端一致')
