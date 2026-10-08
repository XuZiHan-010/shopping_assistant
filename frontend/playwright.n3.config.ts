import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e/n3',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5275', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], locale: 'zh-CN' } }],
  globalSetup: './scripts/n3-e2e-server.mjs',
})
