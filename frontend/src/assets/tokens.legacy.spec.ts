import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * 旧 token 名防回归（W Task 10，裁定 N）。
 *
 * 商家端与顾客端已把 `--color-*` 与 `--shadow-card` / `--shadow-control` 全部换成「市集大厅」新名，
 * `tokens.css` 的兼容映射已删除。源码不得再引用或重新定义这些旧名（包括 `tokens.css` 本身，
 * 它经 `tokens:sync` 原样复制给 shop/）；新增样式一律用 `tokens.css` 顶部的新 token。
 */
const SRC = resolve(process.cwd(), 'src')
/** 本文件的注释与正则里写着旧名，不参与扫描。 */
const SELF = 'assets/tokens.legacy.spec.ts'
const LEGACY = /--(?:color-[\w-]+|shadow-card|shadow-control)(?![\w-])/g

function sourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...sourceFiles(full))
    else if (/\.(vue|ts|css)$/.test(entry.name)) files.push(full)
  }
  return files
}

describe('旧 token 名', () => {
  it('frontend/src（含 tokens.css）不再出现 --color-* / --shadow-card / --shadow-control', () => {
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
    expect(files).toContain('assets/tokens.css')
    expect(files).toContain('views/InventoryView.vue')
    expect(files.length).toBeGreaterThan(100)
    // 正则确实能认出旧名，且不误伤新名。
    expect('--color-primary: x; --shadow-card: y;'.match(LEGACY)).toEqual([
      '--color-primary',
      '--shadow-card',
    ])
    expect('--shadow-sm: x; --accent: y;'.match(LEGACY)).toBeNull()
  })
})
