import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e/s4',
  workers: 1,
  reporter: 'list',
  timeout: 60_000,
  use: { baseURL: 'http://127.0.0.1:5276', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  globalSetup: './scripts/s4-e2e-server.mjs',
})
