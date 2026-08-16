import { defineConfig, devices } from '@playwright/test'

const PORT = 5273
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e',
  // 首屏门禁依赖 production preview 的独立构建目录、API 基址和 idle 冻结，
  // 只能由 playwright.first-paint.config.ts 运行；常规 Mock E2E 不得混入它。
  testIgnore: ['**/real-api/**', '**/first-paint.spec.ts'],
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // Windows 上由 Playwright webServer 启动的 shell 树在测试结束后可能不退出。
  // 直接管理 Vite Node 子进程，按实际 PID 收尾；Mock 模式仍由 setup 显式注入。
  globalSetup: './scripts/mock-e2e-server.mjs',
})
