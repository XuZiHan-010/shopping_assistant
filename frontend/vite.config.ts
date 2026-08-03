import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
// 从 vitest/config 导入才认 test 字段；vite 的 defineConfig 不接受它。
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // 契约测试直接消费后端导出的真实 ChatResponse，不自造载荷。
      '@fixtures': fileURLToPath(new URL('../docs/fixtures', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts'],
  },
})
