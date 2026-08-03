#!/usr/bin/env node
/**
 * fixture 镜像漂移检查。与 check-generated.mjs 同构。
 * 纳入本地质量门禁与 CI，不要纳入 Docker 构建。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { renderModule } from './sync-fixtures.mjs'

const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const committedPath = resolve(frontendRoot, 'src', 'api', 'mock', 'fixtures.generated.ts')

const fresh = await renderModule()
const committed = readFileSync(committedPath, 'utf8')

if (fresh !== committed) {
  console.error(
    '\nsrc/api/mock/fixtures.generated.ts 与 docs/fixtures/chat/ 不一致。\n' +
      '请运行 npm run fixtures 重新生成并提交。\n' +
      '若 fixture 本身过期，先在 backend/ 运行 uv run python ../scripts/export_chat_fixtures.py。\n',
  )
  process.exit(1)
}

console.log('fixtures.generated.ts 与 docs/fixtures/chat/ 一致')
