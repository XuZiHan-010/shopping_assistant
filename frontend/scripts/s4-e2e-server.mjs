// S4 商家浏览器验收：专用一次性库、真实 API 与脚本化模型。
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { startManagedServer } from './e2e-process.mjs'

const DEFAULT_DATABASE_URL =
  'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_s4_e2e_test'
const BACKEND_ROOT = fileURLToPath(new URL('../../backend/', import.meta.url))
const FRONTEND_ROOT = fileURLToPath(new URL('..', import.meta.url))

function runBackendStep(label, args, env) {
  const result = spawnSync('uv', args, { cwd: BACKEND_ROOT, env, stdio: 'inherit', windowsHide: true })
  if (result.status !== 0) throw new Error(`${label} 失败：${result.status ?? result.error?.message}`)
}

export default async function startS4Merchant() {
  const databaseUrl = process.env.S4_E2E_DATABASE_URL ?? DEFAULT_DATABASE_URL
  if (!databaseUrl.replace(/\/+$/, '').endsWith('_s4_e2e_test')) {
    throw new Error('S4 E2E 只允许使用名称以 _s4_e2e_test 结尾的一次性库')
  }
  const env = { ...process.env, APP_ENV: 'test', DATABASE_URL: databaseUrl, S4_E2E_DATABASE_URL: databaseUrl }
  runBackendStep('S4 迁移', ['run', 'alembic', 'upgrade', 'head'], env)
  runBackendStep('S4 种子', ['run', 'python', 'scripts/seed_s4_e2e.py'], env)
  const stopBackend = await startManagedServer({
    label: 'S4 E2E 后端', port: 8014, command: 'uv', cwd: BACKEND_ROOT,
    healthPath: '/api/health',
    args: ['run', 'uvicorn', '--factory', 'tests.support.e2e_s4_app:create_app_from_env',
      '--host', '127.0.0.1', '--port', '8014', '--loop', 'asyncio:SelectorEventLoop'],
    env,
  })
  let stopFrontend
  try {
    stopFrontend = await startManagedServer({
      label: 'S4 E2E Vite', port: 5276, cwd: FRONTEND_ROOT,
      args: ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5276', '--strictPort'],
      env: { VITE_API_BASE_URL: 'http://127.0.0.1:8014', VITE_USE_MOCK: 'false' },
    })
  } catch (error) {
    await stopBackend()
    throw error
  }
  return async () => { await stopFrontend(); await stopBackend() }
}
