import { spawn } from 'node:child_process'

const PORT = 5285
const ORIGIN = `http://127.0.0.1:${PORT}`
const STARTUP_TIMEOUT_MS = 30_000
const SHUTDOWN_TIMEOUT_MS = 5_000

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function waitForPreview(child) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS

  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`首屏 preview 在启动前退出，退出码：${child.exitCode}`)
    }

    try {
      const response = await fetch(ORIGIN)
      if (response.ok) return
    } catch {
      // preview 尚未开始监听，继续以条件轮询等待。
    }
    await delay(100)
  }

  throw new Error(`首屏 preview 未在 ${STARTUP_TIMEOUT_MS}ms 内监听 ${ORIGIN}`)
}

async function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null) return

  await Promise.race([new Promise((resolve) => child.once('exit', resolve)), delay(timeoutMs)])
}

async function forceStop(child) {
  if (!child.pid || child.exitCode !== null) return

  const taskkill = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
    stdio: 'ignore',
    windowsHide: true,
  })
  await new Promise((resolve) => taskkill.once('exit', resolve))
}

export default async function startFirstPaintPreview() {
  const child = spawn(
    process.execPath,
    [
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
    { cwd: process.cwd(), stdio: 'ignore', windowsHide: true },
  )

  try {
    await waitForPreview(child)
  } catch (error) {
    await forceStop(child)
    throw error
  }

  return async () => {
    child.kill()
    await waitForExit(child, SHUTDOWN_TIMEOUT_MS)
    await forceStop(child)
  }
}
