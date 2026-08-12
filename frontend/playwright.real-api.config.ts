import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const FRONTEND_ROOT = fileURLToPath(new URL('.', import.meta.url))
const BACKEND_ROOT = fileURLToPath(new URL('../backend/', import.meta.url))
const DATABASE_URL =
  process.env.F4_E2E_DATABASE_URL ??
  'postgresql+psycopg://borough:borough_local@127.0.0.1:55443/borough_f4_test'

export default defineConfig({
  testDir: './e2e/real-api',
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5274',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command:
        'uv run alembic upgrade head && uv run python scripts/seed_f4_e2e.py && uv run uvicorn tests.support.e2e_app:app --host 127.0.0.1 --port 8011 --loop asyncio:SelectorEventLoop',
      cwd: BACKEND_ROOT,
      env: {
        APP_ENV: 'test',
        DATABASE_URL,
        FRONTEND_ORIGIN: 'http://127.0.0.1:5274',
        ADMIN_TOKEN: 'f4-e2e-admin-token',
        EXPORT_SIGNING_SECRET: 'f4-e2e-export-secret',
        F4_E2E_DATABASE_URL: DATABASE_URL,
      },
      url: 'http://127.0.0.1:8011/api/health',
      // 此测试专用端口必须始终运行迁移和种子数据，避免复用被其他测试清空的服务。
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5274 --strictPort',
      cwd: FRONTEND_ROOT,
      env: {
        VITE_API_BASE_URL: 'http://127.0.0.1:8011',
        VITE_USE_MOCK: 'false',
      },
      url: 'http://127.0.0.1:5274',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
