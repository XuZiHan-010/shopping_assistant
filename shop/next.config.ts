import type { NextConfig } from 'next'

// 浏览器直连 Backend（严格 CORS）；不用 rewrites / API Routes 做代理（AGENTS.md §十一）。
// standalone 输出让 Docker 镜像只带运行所需文件。
const config: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
}

export default config
