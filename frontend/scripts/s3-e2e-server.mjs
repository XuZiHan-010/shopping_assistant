// S3 浏览器验收（`n2-merchant-vue-v2-migration` Task 7）的全局启动：
// 迁移 + 重新播种 → 启动脚本化模型的真实后端 → 启动直连该后端的 Vite。
//
// 数据库不由本脚本创建：它会清空整库，只接受名称以 `_s3_e2e_test` 结尾、由调用方
// 预先准备好的一次性库（见 playwright.s3.config.ts 头注释）。每次运行都重新播种，
// 因为验收会批准草稿、改掉库存——不能指望上一次的残留状态。
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { startManagedServer } from './e2e-process.mjs'

export const S3_BACKEND_PORT = 8012
export const S3_FRONTEND_PORT = 5275
const DEFAULT_DATABASE_URL =
  'postgresql+psycopg://borough:borough_local@127.0.0.1:55451/borough_s3_e2e_test'

const BACKEND_ROOT = fileURLToPath(new URL('../../backend/', import.meta.url))
const FRONTEND_ROOT = fileURLToPath(new URL('..', import.meta.url))

function runBackendStep(label, args, env) {
  const result = spawnSync('uv', args, { cwd: BACKEND_ROOT, env, stdio: 'inherit', windowsHide: true })
  if (result.status !== 0) {
    throw new Error(`${label} 失败，退出码：${result.status ?? result.error?.message}`)
  }
}

export default async function startS3E2EServers() {
  const databaseUrl = process.env.S3_E2E_DATABASE_URL ?? DEFAULT_DATABASE_URL
  if (!databaseUrl.replace(/\/+$/, '').endsWith('_s3_e2e_test')) {
    throw new Error('S3 验收会清空整库，S3_E2E_DATABASE_URL 必须指向名称以 _s3_e2e_test 结尾的库')
  }
  const backendEnv = {
    ...process.env,
    APP_ENV: 'test',
    DATABASE_URL: databaseUrl,
    S3_E2E_DATABASE_URL: databaseUrl,
  }

  runBackendStep('数据库迁移', ['run', 'alembic', 'upgrade', 'head'], backendEnv)
  runBackendStep('S3 种子数据', ['run', 'python', 'scripts/seed_s3_e2e.py'], backendEnv)

  const stopBackend = await startManagedServer({
    label: 'S3 E2E 后端',
    port: S3_BACKEND_PORT,
    command: 'uv',
    cwd: BACKEND_ROOT,
    healthPath: '/api/health',
    args: [
      'run',
      'uvicorn',
      '--factory',
      'tests.support.e2e_s3_app:create_app_from_env',
      '--host',
      '127.0.0.1',
      '--port',
      String(S3_BACKEND_PORT),
      // psycopg 异步驱动在 Windows 默认的 Proactor 循环上不可用（与 F4 真实后端验收同一处理）。
      '--loop',
      'asyncio:SelectorEventLoop',
    ],
    env: backendEnv,
  })

  let stopFrontend
  try {
    stopFrontend = await startManagedServer({
      label: 'S3 E2E Vite',
      port: S3_FRONTEND_PORT,
      cwd: FRONTEND_ROOT,
      args: [
        'node_modules/vite/bin/vite.js',
        '--host',
        '127.0.0.1',
        '--port',
        String(S3_FRONTEND_PORT),
        '--strictPort',
      ],
      env: {
        VITE_API_BASE_URL: `http://127.0.0.1:${S3_BACKEND_PORT}`,
        VITE_USE_MOCK: 'false',
      },
    })
  } catch (error) {
    await stopBackend()
    throw error
  }

  return async () => {
    await stopFrontend()
    await stopBackend()
  }
}
