import { spawn } from 'node:child_process'

const child = spawn(
  process.execPath,
  ['node_modules/vite/bin/vite.js', 'build', '--outDir', 'dist-first-paint'],
  {
    cwd: process.cwd(),
    env: {
      ...process.env,
      VITE_API_BASE_URL: 'http://borough-preview.test',
      VITE_USE_MOCK: 'false',
    },
    stdio: 'inherit',
  },
)

child.once('error', (error) => {
  throw error
})

child.once('close', (code) => {
  process.exitCode = code ?? 1
})
