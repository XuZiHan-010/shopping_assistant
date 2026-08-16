import { defineConfig, devices } from '@playwright/test'

const BASE_URL = 'http://127.0.0.1:5285'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'first-paint.spec.ts',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // 首屏产物由 test:e2e:first-paint 先构建，再由 globalSetup 以直接 Node 子进程
  // 启动/回收 preview。Windows 的 webServer shell 进程树在 test 已结束后会卡住，
  // 使门禁没有确定退出码；globalSetup 能按实际子进程 PID 收尾。
  globalSetup: './scripts/first-paint-server.mjs',
})
