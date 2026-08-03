#!/usr/bin/env node
/**
 * generated.ts 漂移检查。
 *
 * `src/api/generated.ts` 是提交进仓库的生成产物：Railway 的 frontend service
 * Root Directory 是 /frontend（AGENTS.md §十四），Docker 构建上下文里没有 docs/，
 * 所以构建期不能跑 codegen，只能消费已提交的文件。
 *
 * 代价是它可能与 docs/api.json 脱节，而且不会有任何东西自动失败。这个脚本把
 * 脱节变成一条明确的错误：重新生成到临时文件，与提交版本逐字节比对。
 *
 * 纳入本地质量门禁与 CI，**不要**纳入 Docker 构建。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const schemaPath = resolve(frontendRoot, '..', 'docs', 'api.json')
const committedPath = resolve(frontendRoot, 'src', 'api', 'generated.ts')

const workDir = mkdtempSync(join(tmpdir(), 'borough-codegen-'))
const freshPath = join(workDir, 'generated.ts')

try {
  execFileSync(
    process.execPath,
    [
      resolve(frontendRoot, 'node_modules', 'openapi-typescript', 'bin', 'cli.js'),
      schemaPath,
      '-o',
      freshPath,
    ],
    { stdio: 'pipe' },
  )

  const fresh = readFileSync(freshPath, 'utf8')
  const committed = readFileSync(committedPath, 'utf8')

  if (fresh !== committed) {
    console.error(
      '\nsrc/api/generated.ts 与 docs/api.json 不一致。\n' +
        '请运行 npm run codegen 重新生成并提交。\n' +
        '若 docs/api.json 本身过期，先在 backend/ 运行 uv run python ../scripts/export_openapi.py。\n',
    )
    process.exit(1)
  }

  console.log('generated.ts 与 docs/api.json 一致')
} finally {
  rmSync(workDir, { recursive: true, force: true })
}
