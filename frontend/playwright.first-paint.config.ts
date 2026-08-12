import { defineConfig, devices } from '@playwright/test'

// 5273 供常规 Mock E2E、5274 供 real-api E2E；首屏 production preview 独占此端口。
const PORT = 5285
const BASE_URL = `http://127.0.0.1:${PORT}`
const FIRST_PAINT_OUT_DIR = 'dist-first-paint'

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
  webServer: {
    // 不使用默认 dist：其他构建可以在 preview 运行时覆写它，使页面加载到错误的
    // import.meta.env 编译值，进而绕过 page.route 的隔离。构建与预览必须指向同一专用目录。
    command: `npm run build -- --outDir ${FIRST_PAINT_OUT_DIR} && npm run preview -- --outDir ${FIRST_PAINT_OUT_DIR} --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    // 此门禁验证的是上面命令产出的 production preview。复用未知进程会重新引入旧产物风险。
    reuseExistingServer: false,
    timeout: 120_000,
    // 必须走生产构建：Task 5 禁止 production 启用 Mock。首屏用例在 page.route()
    // 层只拦截身份与空会话请求，因此不会访问真实后端或 LLM。
    env: {
      VITE_API_BASE_URL: 'http://borough-preview.test',
      VITE_USE_MOCK: 'false',
    },
  },
})
