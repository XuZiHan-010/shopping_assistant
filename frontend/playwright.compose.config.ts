import { defineConfig, devices } from '@playwright/test'

/**
 * 本地 compose 全栈冒烟（N5 C Task 5 步骤 3）：对着 `docker compose up` 起来的真实镜像跑，
 * 不自己起任何服务。前置条件见 `e2e/compose/single-entry.spec.ts` 文件头。
 *
 * 证明的是部署拓扑：商家端静态镜像、顾客端镜像、backend 与数据库之间的地址、CORS 与单入口跳转。
 * 没有配置 LLM_API_KEY，助手回答走可见降级；带脚本化模型的 S1–S8 场景由各自的套件覆盖。
 */
export default defineConfig({
  testDir: './e2e/compose',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  reporter: 'list',
  use: {
    baseURL: process.env.COMPOSE_MERCHANT_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    // 顾客端按浏览器语言选显示语言；断言用中文文案，所以固定中文（与 shop/playwright.config.ts 一致）。
    locale: 'zh-CN',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
