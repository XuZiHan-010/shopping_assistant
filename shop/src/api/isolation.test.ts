import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) ? [path] : []
  })
}

const read = (path: string) => readFileSync(path, 'utf-8')
/** 去掉注释再扫：注释里解释「不写 localStorage」不算写。 */
const code = (path: string) =>
  read(path)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')

describe('顾客端边界', () => {
  it('公开的 catalogApi 不依赖会话凭证：服务端组件会用到它，共享凭证会混淆不同访客', () => {
    expect(read('src/api/catalogApi.ts')).not.toMatch(/credentials|getSession|X-Session-Id/)
  })

  it('shop 不 import 商家端代码', () => {
    for (const file of sources('src')) {
      expect(read(file), file).not.toMatch(/from ['"](?:\.\.\/)+frontend|from ['"]@borough\/web/)
    }
  })

  it('组件与页面不直接消费 generated.ts（只有 api/ 层可以）', () => {
    const offenders = sources('src')
      .filter((file) => !file.split(sep).join('/').startsWith('src/api/'))
      .filter((file) => /from ['"]@\/api\/generated['"]/.test(read(file)))
    expect(offenders).toEqual([])
  })

  it('会话凭证不写任何持久化存储或 cookie（credentials.ts 之外也不写）', () => {
    for (const file of sources('src')) {
      expect(code(file), file).not.toMatch(/localStorage|sessionStorage|document\.cookie/)
    }
  })
})
