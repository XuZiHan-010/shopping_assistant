import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * 旧 token 名防回归（WS 收尾 W Task 10 步骤 3）。
 *
 * 共享 `tokens.css` 的旧名兼容映射已删除，顾客端再引用 `--color-*` 或
 * `--shadow-card` / `--shadow-control` 会取到空值而静默失去样式；一律用新 token。
 */
const SRC = resolve(process.cwd(), 'src')
/** 本文件的注释与正则里写着旧名，不参与扫描。 */
const SELF = 'styles/tokens.legacy.test.ts'
const LEGACY = /--(?:color-[\w-]+|shadow-card|shadow-control)(?![\w-])/g

function sourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...sourceFiles(full))
    else if (/\.(tsx?|css)$/.test(entry.name)) files.push(full)
  }
  return files
}

describe('旧 token 名', () => {
  it('shop/src 不再出现 --color-* / --shadow-card / --shadow-control', () => {
    const offenders: string[] = []
    for (const file of sourceFiles(SRC)) {
      const path = relative(SRC, file).replaceAll('\\', '/')
      if (path === SELF) continue
      const lines = readFileSync(file, 'utf-8').split('\n')
      lines.forEach((line, index) => {
        for (const match of line.matchAll(LEGACY))
          offenders.push(`${path}:${index + 1} ${match[0]}`)
      })
    }
    expect(offenders).toEqual([])
  })

  it('扫描确实覆盖到源码（防止路径写错导致空扫描而恒通过）', () => {
    const files = sourceFiles(SRC).map((file) => relative(SRC, file).replaceAll('\\', '/'))
    expect(files).toContain('styles/tokens.css')
    expect(files).toContain('app/globals.css')
    expect(files.length).toBeGreaterThan(50)
  })
})
