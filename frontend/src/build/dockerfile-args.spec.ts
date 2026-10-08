import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Railway 把服务变量作为 build-arg 传给 Dockerfile，**未声明的 build-arg 会被静默丢弃**：
 * 变量明明配了却完全不生效，且没有任何报错（docs/deployment.md「前端环境变量」）。
 * 所以 `env.d.ts` 里声明的每个 `VITE_*` 变量都必须在 Dockerfile 里有对应的 ARG 与 ENV。
 */
describe('frontend/Dockerfile 的构建参数', () => {
  const root = resolve(__dirname, '../..')
  // 按行比较并去掉行尾空白：仓库在 Windows 上检出时是 CRLF。
  const lines = new Set(
    readFileSync(resolve(root, 'Dockerfile'), 'utf-8')
      .split('\n')
      .map((line) => line.trim()),
  )
  const declared = [
    ...readFileSync(resolve(root, 'env.d.ts'), 'utf-8').matchAll(/readonly (VITE_[A-Z_]+)\??:/g),
  ].map((match) => match[1]!)

  it('env.d.ts 至少声明了后端地址与顾客端地址', () => {
    expect(declared).toEqual(expect.arrayContaining(['VITE_API_BASE_URL', 'VITE_SHOP_BASE_URL']))
  })

  it.each(declared)('%s 在 Dockerfile 里同时有 ARG 与 ENV', (name) => {
    expect(lines.has(`ARG ${name}`), `缺少 ARG ${name}`).toBe(true)
    expect(lines.has(`ENV ${name}=$${name}`), `缺少 ENV ${name}`).toBe(true)
  })
})
