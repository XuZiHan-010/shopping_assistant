import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
// 从 vitest/config 导入才认 test 字段；vite 的 defineConfig 不接受它。
import { defineConfig } from 'vitest/config'

import { assertMockDisabledInProduction } from './src/build/mock-flag'

export default defineConfig(({ mode }) => {
  assertMockDisabledInProduction(mode, loadEnv(mode, process.cwd(), 'VITE_'))

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        // 契约测试直接消费后端导出的真实 ChatResponse，不自造载荷。
        '@fixtures': fileURLToPath(new URL('../docs/fixtures', import.meta.url)),
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
          },
        },
      },
    },
    test: {
      environment: 'happy-dom',
      include: ['src/**/*.spec.ts'],
    },
  }
})
