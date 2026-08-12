// F6：构建产物不得包含任何密钥。
// VITE_ 前缀变量会被内联进静态产物，一旦有人误把密钥写成 VITE_ 变量，
// 它就会公开在 CDN 上。让这类错误在门禁里失败，而不是上线后才发现。
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const distDir = join(frontendRoot, 'dist')

const PATTERNS = [
  { name: 'DeepSeek API Key', re: /\bsk-[A-Za-z0-9]{16,}\b/ },
  { name: 'PostgreSQL 连接串', re: /postgres(?:ql)?(?:\+\w+)?:\/\/[^\s"']+:[^\s"']+@/ },
  { name: '演示商家 Token 映射', re: /DEMO_MERCHANT_TOKENS/ },
  { name: '管理员令牌', re: /ADMIN_TOKEN/ },
  { name: '导出签名密钥', re: /EXPORT_SIGNING_SECRET/ },
]

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) yield* walk(full)
    else yield full
  }
}

const hits = []
for (const file of walk(distDir)) {
  if (!/\.(js|css|html|json|map)$/.test(file)) continue
  const content = readFileSync(file, 'utf8')
  for (const { name, re } of PATTERNS) {
    if (re.test(content)) hits.push(`${name} → ${file.slice(distDir.length + 1)}`)
  }
}

if (hits.length > 0) {
  console.error('构建产物中检出疑似密钥：')
  for (const hit of hits) console.error(`  ${hit}`)
  process.exit(1)
}

console.log('构建产物未检出密钥形态字符串')
