import { defineConfig, devices } from '@playwright/test'

const PORT = 5273
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './e2e',
  // 首屏门禁依赖 production preview 的独立构建目录、API 基址和 idle 冻结，
  // 只能由 playwright.first-paint.config.ts 运行；常规 Mock E2E 不得混入它。
  // S3 验收需要真实后端与一次性库，只能由 playwright.s3.config.ts 运行。
  // compose 全栈冒烟要先 `docker compose up`，只能由 playwright.compose.config.ts 运行。
  testIgnore: [
    '**/real-api/**',
    '**/s3/**',
    '**/s4/**',
    '**/n3/**',
    '**/compose/**',
    '**/first-paint.spec.ts',
  ],
  fullyParallel: true,
  // 跑的是 Vite 开发服务器（模块不打包、按需转译）：多个 worker 并行时单次整页加载可达数秒，
  // 一个用例里连开六七个页面的窄屏溢出检查单独跑 16–24 秒，并行时会撞默认的 30 秒。
  // 首屏性能另有 production preview 上的门禁（playwright.first-paint.config.ts），不靠这里的超时把关。
  timeout: 60_000,
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
