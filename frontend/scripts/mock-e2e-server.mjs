import { startManagedServer } from './e2e-process.mjs'

const PORT = 5273

export default async function startMockE2EServer() {
  return startManagedServer({
    label: 'Mock E2E Vite',
    port: PORT,
    args: [
      'node_modules/vite/bin/vite.js',
      '--host',
      '127.0.0.1',
      '--port',
      String(PORT),
      '--strictPort',
    ],
    // F2 起的 E2E 跑的是 Mock 传输层，不依赖真实后端。显式注入而不是依赖
    // .env.development——CI 上没有那个文件时会静默退回真实传输并全线失败。
    env: { VITE_USE_MOCK: 'true' },
  })
}
