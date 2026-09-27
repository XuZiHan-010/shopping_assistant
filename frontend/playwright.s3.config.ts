import { defineConfig, devices } from '@playwright/test'

/**
 * S3 浏览器验收（`n2-merchant-vue-v2-migration` Task 7）：真实后端 + 真实 PostgreSQL +
 * 脚本化模型（`backend/tests/support/e2e_s3_app.py`，零 LLM 费用）。
 *
 * 需要调用方预先提供一个一次性库（启动脚本会清空并重新播种它），通过
 * `S3_E2E_DATABASE_URL` 指定，库名必须以 `_s3_e2e_test` 结尾；缺省为
 * `postgresql+psycopg://borough:borough_local@127.0.0.1:55451/borough_s3_e2e_test`。
 *
 * 进程由 `scripts/s3-e2e-server.mjs` 按 PID 管理，不用 Playwright 自带的 webServer
 * （Windows 上 shell 进程树可能不退出，见 `scripts/e2e-process.mjs`）。
 */
export default defineConfig({
  testDir: './e2e/s3',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5275',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  globalSetup: './scripts/s3-e2e-server.mjs',
})
