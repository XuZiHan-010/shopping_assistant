import { startManagedServer } from './e2e-process.mjs'

const PORT = 5285

export default async function startFirstPaintPreview() {
  return startManagedServer({
    label: '首屏 preview',
    port: PORT,
    args: [
      'node_modules/vite/bin/vite.js',
      'preview',
      '--outDir',
      'dist-first-paint',
      '--host',
      '127.0.0.1',
      '--port',
      String(PORT),
      '--strictPort',
    ],
  })
}
