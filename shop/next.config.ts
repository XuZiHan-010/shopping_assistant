import type { NextConfig } from 'next'

// 浏览器直连 Backend（严格 CORS）；不用 rewrites / API Routes 做代理（AGENTS.md §十一）。
// standalone 输出让 Docker 镜像只带运行所需文件。
const config: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  // 左下角是产品偏好入口；开发工具指示器会遮住它并拦截点击。
  devIndicators: false,
  // 浏览器验收独立启动 dev，避免与开发者正在使用的 .next/dev 锁互相阻塞。
  distDir: process.env.E2E_NEXT_DIST_DIR ?? '.next',
}

export default config
