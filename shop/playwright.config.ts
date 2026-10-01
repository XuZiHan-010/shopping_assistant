import { defineConfig, devices } from '@playwright/test'

/**
 * S1 浏览器验收（`n2-shop-nextjs-app` Task 8）：真实后端 + 真实 PostgreSQL + 脚本化模型
 * （`backend/tests/support/e2e_s1_app.py`，零 LLM 费用）。
 *
 * 需要调用方预先提供一个一次性库（启动脚本会清空并重新播种它），通过 `S1_E2E_DATABASE_URL`
 * 指定，库名必须以 `_s1_e2e_test` 结尾；缺省为
 * `postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_s1_e2e_test`。
 *
 * 进程由 `e2e/global-setup.mjs` 按 PID 管理，不用 Playwright 自带的 webServer
 * （Windows 上 shell 进程树可能不退出，见 `scripts/e2e-process.mjs`）。
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  // S4 需要自己的一次性库与后端，只能由 playwright.s4.config.ts 运行。
  testIgnore: ['**/s4/**'],
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  timeout: 60_000,
  use: {
    baseURL: 'http://127.0.0.1:3275',
    trace: 'retain-on-failure',
  },
  // 顾客端按浏览器语言渲染（R1），S1 断言中文文案，必须固定中文浏览器语言，与 S4 配置一致。
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], locale: 'zh-CN' } }],
  globalSetup: './e2e/global-setup.mjs',
})
