// N3 商家浏览器验收：S3 隔离库重新播种后，接入 N3 脚本化模型与真实 API。
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { startManagedServer } from './e2e-process.mjs'

const BACKEND_PORT = 8014
const FRONTEND_PORT = 5275
const DEFAULT_DATABASE_URL =
  'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_n3_browser_s3_e2e_test'
const BACKEND_ROOT = fileURLToPath(new URL('../../backend/', import.meta.url))
const FRONTEND_ROOT = fileURLToPath(new URL('..', import.meta.url))
const SHOP_ROOT = fileURLToPath(new URL('../../shop/', import.meta.url))

function backendStep(label, args, env) {
  const result = spawnSync('uv', args, { cwd: BACKEND_ROOT, env, stdio: 'inherit', windowsHide: true })
  if (result.status !== 0) throw new Error(`${label} 失败：${result.status ?? result.error?.message}`)
}

export default async function startN3E2EServers() {
  const databaseUrl = process.env.S3_E2E_DATABASE_URL ?? DEFAULT_DATABASE_URL
  if (!databaseUrl.replace(/\/+$/, '').endsWith('_s3_e2e_test')) {
    throw new Error('N3 浏览器验收会清空整库，数据库名必须以 _s3_e2e_test 结尾')
  }
  const env = { ...process.env, APP_ENV: 'test', DATABASE_URL: databaseUrl, S3_E2E_DATABASE_URL: databaseUrl }
  backendStep('数据库迁移', ['run', 'alembic', 'upgrade', 'head'], env)
  backendStep('S3 基础数据', ['run', 'python', 'scripts/seed_s3_e2e.py'], env)
  backendStep('N3 补充数据', ['run', 'python', 'scripts/seed_n3_e2e.py'], env)
  const stopBackend = await startManagedServer({
    label: 'N3 E2E 后端', port: BACKEND_PORT, command: 'uv', cwd: BACKEND_ROOT,
    healthPath: '/api/health',
    args: [
      'run', 'uvicorn', '--factory', 'tests.support.e2e_n3_app:create_app_from_env',
      '--host', '127.0.0.1', '--port', String(BACKEND_PORT),
      '--loop', 'asyncio:SelectorEventLoop',
    ],
    env,
  })
  let stopFrontend
  let stopShop
  try {
    stopFrontend = await startManagedServer({
      label: 'N3 E2E Vite', port: FRONTEND_PORT, cwd: FRONTEND_ROOT,
      args: ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(FRONTEND_PORT), '--strictPort'],
      env: { VITE_API_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}`, VITE_USE_MOCK: 'false' },
    })
    stopShop = await startManagedServer({
      label: 'N3 E2E shop', port: 3275, cwd: SHOP_ROOT, healthPath: '/health',
      startupTimeoutMs: 90_000,
      args: ['node_modules/next/dist/bin/next', 'dev', '--hostname', '127.0.0.1', '--port', '3275'],
      env: { NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}` },
    })
  } catch (error) {
    if (stopFrontend) await stopFrontend()
    await stopBackend()
    throw error
  }
  return async () => { await stopShop(); await stopFrontend(); await stopBackend() }
}
