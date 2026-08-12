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
      // 首屏 production-preview 的专用构建目录；它与 dist 一样是 Vite 生成物。
      '**/dist-first-paint/**',
      '**/node_modules/**',
      '**/playwright-report/**',
      '**/test-results/**',
      // OpenAPI 机器产物，禁止手改，也不参与代码风格检查。
      'src/api/generated.ts',
      // chat fixture 镜像，同样是机器产物，禁止手改，也不参与代码风格检查。
      'src/api/mock/fixtures.generated.ts',
    ],
  },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    name: 'app/api-no-store-imports',
    files: ['src/api/**'],
    rules: {
      // `src/api/**` 不得 import `src/stores/**`：store 本身要调 api 发请求，
      // 反向引用会形成 store → api → store 的循环依赖。凭证从 store 传进
      // api 的唯一合法方式是 `credentials.ts` 的 `setCredentialProvider`
      // （main.ts 注入），而不是 api 直接 import 某个 store。
      //
      // 循环一旦被这条规则挡住就再也回不来了，比写在文档里靠代码评审可靠。
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/stores/*', '@/stores', '**/stores/*', '**/stores'],
              message:
                'src/api/** 禁止直接 import store，会形成 store → api → store 的循环依赖。' +
                '请通过 credentials.ts 的 setCredentialProvider 由 main.ts 注入凭证来源。',
            },
          ],
        },
      ],
    },
  },
  {
    name: 'app/no-mock-imports-in-production-code',
    files: ['src/**/*.{ts,mts,js,mjs,vue}'],
    ignores: ['src/api/mock/**', 'src/api/transport.ts', 'src/**/*.spec.*'],
    rules: {
      // Mock 只能由 transport 边界动态加载；其余生产代码不得静态依赖演示数据。
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/mock', '@/api/mock/*', '**/api/mock', '**/api/mock/*'],
              message:
                '生产代码不得依赖 api/mock；Mock 只能由 api/transport.ts 动态加载，' +
                '产品常量请放在 src/constants/。',
            },
          ],
        },
      ],
    },
  },
)
