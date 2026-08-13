import { spawn } from 'node:child_process'

const STARTUP_TIMEOUT_MS = 30_000
const SHUTDOWN_TIMEOUT_MS = 5_000

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function isListening(origin) {
  try {
    const response = await fetch(origin)
    return response.ok
  } catch {
    return false
  }
}

async function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null) return

  await Promise.race([new Promise((resolve) => child.once('exit', resolve)), delay(timeoutMs)])
}

/**
 * 强制回收进程树。
 *
 * Windows 上 `child.kill()` 只终止 Node 自身，Vite 派生的子进程会留下来占住端口，
 * 所以要用 taskkill /T；但 taskkill 是 Windows 专有命令，POSIX 上 spawn 会发出
 * `error` 而不是 `exit`，只监听 `exit` 会让收尾永久挂起并抛未处理异常。
 */
async function forceStop(child) {
  if (!child.pid || child.exitCode !== null) return

  if (process.platform !== 'win32') {
    child.kill('SIGKILL')
    await waitForExit(child, SHUTDOWN_TIMEOUT_MS)
    return
  }

  const taskkill = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
    stdio: 'ignore',
    windowsHide: true,
  })
  await new Promise((resolve) => {
    taskkill.once('exit', resolve)
    taskkill.once('error', resolve)
  })
}

/**
 * 以 Node 子进程方式启动一个本地服务，并返回按真实 PID 收尾的 teardown。
 *
 * Playwright 自带的 webServer 在 Windows 上启动的是 shell 进程树，测试结束后
 * 可能不退出（表现为断言全过但 CLI 以超时码结束），因此这里自行管理进程。
 */
export async function startManagedServer({ label, port, args, env }) {
  const origin = `http://127.0.0.1:${port}`

  if (await isListening(origin)) {
    throw new Error(
      `${label} 端口 ${port} 已被占用。E2E 需要自己启动并回收服务（--strictPort），` +
        `不复用已有进程——已有进程的环境变量未知，可能跑在与门禁不同的传输层上。` +
        `请先停掉占用 ${port} 的进程再重试。`,
    )
  }

  const child = spawn(process.execPath, args, {
    cwd: process.cwd(),
    env: { ...process.env, ...env },
    stdio: 'ignore',
    windowsHide: true,
  })

  try {
    const deadline = Date.now() + STARTUP_TIMEOUT_MS
    while (Date.now() < deadline) {
      if (child.exitCode !== null) {
        throw new Error(`${label} 在启动前退出，退出码：${child.exitCode}`)
      }
      if (await isListening(origin)) {
        return async () => {
          child.kill()
          await waitForExit(child, SHUTDOWN_TIMEOUT_MS)
          await forceStop(child)
        }
      }
      await delay(100)
    }
    throw new Error(`${label} 未在 ${STARTUP_TIMEOUT_MS}ms 内监听 ${origin}`)
  } catch (error) {
    await forceStop(child)
    throw error
  }
}
