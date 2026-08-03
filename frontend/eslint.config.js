import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

// 用 .js 而非 .ts：ESLint 9 加载 TypeScript 配置需要额外的 jiti 依赖，
// 而 docs/frontend-development-plan.md §4 的目标目录写的就是 eslint.config.js。
export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{ts,mts,js,mjs,vue}'],
  },
  {
    name: 'app/files-to-ignore',
    ignores: [
      '**/dist/**',
      '**/node_modules/**',
      '**/playwright-report/**',
      '**/test-results/**',
      // OpenAPI 机器产物，禁止手改，也不参与代码风格检查。
      'src/api/generated.ts',
    ],
  },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
)
