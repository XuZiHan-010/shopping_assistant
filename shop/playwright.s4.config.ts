import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e/s4',
  workers: 1,
  reporter: 'list',
  timeout: 60_000,
  use: { baseURL: 'http://127.0.0.1:3276', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], locale: 'zh-CN' } }],
  globalSetup: './e2e/s4-global-setup.mjs',
})
