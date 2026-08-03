import { defineConfig, devices } from '@playwright/test'

const PORT = 5273
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // 必须显式 --host 127.0.0.1：Vite 默认只绑 `localhost`，而在部分 Windows 环境
    // 上 `localhost` 解析为 IPv6 ::1，此时 Playwright 轮询 127.0.0.1 会一直连不上，
    // 最终以「Timed out waiting for config.webServer」失败，看不出真实原因。
    // 必须显式 --host 127.0.0.1：Vite 默认只绑 `localhost`，而在部分 Windows 环境
    // 上 `localhost` 解析为 IPv6 ::1，此时 Playwright 轮询 127.0.0.1 会一直连不上，
    // 最终以「Timed out waiting for config.webServer」失败，看不出真实原因。
    command: `npm run dev -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
