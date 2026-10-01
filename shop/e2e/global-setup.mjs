// S1 浏览器验收的全局启动：迁移 + 重新播种 → 启动脚本化模型的真实后端 → 启动直连该后端的 Next.js。
//
// 数据库不由本脚本创建：它会清空整库，只接受名称以 `_s1_e2e_test` 结尾、由调用方预先准备好的一次性库。
// 每次运行都重新播种，因为验收会下单、支付、改掉库存——不能指望上一次的残留状态。
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { startManagedServer } from '../scripts/e2e-process.mjs'

export const S1_BACKEND_PORT = 8013
export const S1_SHOP_PORT = 3275
const DEFAULT_DATABASE_URL =
  'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_s1_e2e_test'

const BACKEND_ROOT = fileURLToPath(new URL('../../backend/', import.meta.url))
const SHOP_ROOT = fileURLToPath(new URL('..', import.meta.url))

function runBackendStep(label, args, env) {
  const result = spawnSync('uv', args, { cwd: BACKEND_ROOT, env, stdio: 'inherit', windowsHide: true })
  if (result.status !== 0) {
    throw new Error(`${label} 失败，退出码：${result.status ?? result.error?.message}`)
  }
}

export default async function startS1E2EServers() {
  const databaseUrl = process.env.S1_E2E_DATABASE_URL ?? DEFAULT_DATABASE_URL
  if (!databaseUrl.replace(/\/+$/, '').endsWith('_s1_e2e_test')) {
    throw new Error('S1 验收会清空整库，S1_E2E_DATABASE_URL 必须指向名称以 _s1_e2e_test 结尾的库')
  }
  const backendEnv = {
    ...process.env,
    APP_ENV: 'test',
    DATABASE_URL: databaseUrl,
    S1_E2E_DATABASE_URL: databaseUrl,
  }

  runBackendStep('数据库迁移', ['run', 'alembic', 'upgrade', 'head'], backendEnv)
  runBackendStep('S1 种子数据', ['run', 'python', 'scripts/seed_s1_e2e.py'], backendEnv)

  const stopBackend = await startManagedServer({
    label: 'S1 E2E 后端',
    port: S1_BACKEND_PORT,
    command: 'uv',
    cwd: BACKEND_ROOT,
    healthPath: '/api/health',
    args: [
      'run',
      'uvicorn',
      '--factory',
      'tests.support.e2e_s1_app:create_app_from_env',
      '--host',
      '127.0.0.1',
      '--port',
      String(S1_BACKEND_PORT),
      // psycopg 异步驱动在 Windows 默认的 Proactor 循环上不可用。
      '--loop',
      'asyncio:SelectorEventLoop',
    ],
    env: backendEnv,
  })

  let stopShop
  try {
    stopShop = await startManagedServer({
      label: 'S1 E2E shop',
      port: S1_SHOP_PORT,
      cwd: SHOP_ROOT,
      healthPath: '/health',
      args: ['node_modules/next/dist/bin/next', 'dev', '--hostname', '127.0.0.1', '--port', String(S1_SHOP_PORT)],
      env: {
        NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${S1_BACKEND_PORT}`,
        E2E_NEXT_DIST_DIR: '.next-e2e',
      },
    })
  } catch (error) {
    await stopBackend()
    throw error
  }

  return async () => {
    await stopShop()
    await stopBackend()
  }
}
