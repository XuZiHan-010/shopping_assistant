import nextVitals from 'eslint-config-next/core-web-vitals'
import nextTs from 'eslint-config-next/typescript'

const config = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: [
      '.next/**',
      '.next-e2e/**',
      '.next-s4-e2e/**',
      'node_modules/**',
      'test-results/**',
      'playwright-report/**',
      'src/api/generated.ts',
      'next-env.d.ts',
    ],
  },
]

export default config
