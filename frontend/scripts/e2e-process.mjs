import { spawn } from 'node:child_process'

const STARTUP_TIMEOUT_MS = 30_000
const SHUTDOWN_TIMEOUT_MS = 5_000
const POLL_TIMEOUT_MS = 500

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

// 显式给每次探测加超时：一个占着端口但挂死不响应的进程会让不带超时的
// fetch 无限期悬挂，吃掉大半个 STARTUP_TIMEOUT_MS 预算，报出跟真实原因
// （端口被占用/服务未启动）无关的超时错误。
async function isListening(origin) {
  try {
    const response = await fetch(origin, { signal: AbortSignal.timeout(POLL_TIMEOUT_MS) })
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
 * 以子进程方式启动一个本地服务，并返回按真实 PID 收尾的 teardown。
 *
 * Playwright 自带的 webServer 在 Windows 上启动的是 shell 进程树，测试结束后
 * 可能不退出（表现为断言全过但 CLI 以超时码结束），因此这里自行管理进程。
 *
 * `command` 缺省是当前 Node；启动非 Node 服务（如 `uv run uvicorn`）时显式传入，
 * 同样不经过 shell，收尾仍按 PID 回收整棵进程树。`healthPath` 缺省探测根路径，
 * 根路径不返回 2xx 的服务（如后端 API）传就绪端点。
 */
export async function startManagedServer({
  label,
  port,
  args,
  env,
  command = process.execPath,
  cwd = process.cwd(),
  healthPath = '',
  startupTimeoutMs = STARTUP_TIMEOUT_MS,
}) {
  const origin = `http://127.0.0.1:${port}`
  const probe = `${origin}${healthPath}`

  if (await isListening(probe)) {
    throw new Error(
      `${label} 端口 ${port} 已被占用。E2E 需要自己启动并回收服务（--strictPort），` +
        `不复用已有进程——已有进程的环境变量未知，可能跑在与门禁不同的传输层上。` +
        `请先停掉占用 ${port} 的进程再重试。`,
    )
  }

  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...env },
    stdio: 'ignore',
    windowsHide: true,
  })

  try {
    const deadline = Date.now() + startupTimeoutMs
    while (Date.now() < deadline) {
      if (child.exitCode !== null) {
        throw new Error(`${label} 在启动前退出，退出码：${child.exitCode}`)
      }
      if (await isListening(probe)) {
        return async () => {
          // Windows 上先按进程树回收：若先 `child.kill()`，父进程退出后 `forceStop`
          // 会因 exitCode 已有值而直接返回，`taskkill /T` 再也枚举不到孙进程——
          // `uv run uvicorn` 这类「启动器 → 真实服务」的服务会留下占着端口的孤儿进程。
          if (process.platform === 'win32') await forceStop(child)
          else child.kill()
          await waitForExit(child, SHUTDOWN_TIMEOUT_MS)
          await forceStop(child)
        }
      }
      await delay(100)
    }
    throw new Error(`${label} 未在 ${startupTimeoutMs}ms 内监听 ${origin}`)
  } catch (error) {
    await forceStop(child)
    throw error
  }
}
