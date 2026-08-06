"""容器和本地开发启动入口。"""

from __future__ import annotations

import os

import uvicorn

from app.core.runtime import loop_factory

# 收到 SIGTERM 后最多等待这么久，让在途 SSE 流收尾，超时后 uvicorn 强制断开
# 剩余连接。Railway 自己的 SIGTERM→SIGKILL 宽限期更长，这里给出一个明确的
# 上限，避免依赖 uvicorn 未设置时的默认行为（可能无限等待）。
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30

# 刻意不传 `workers=`：限流器（`SlidingWindowRateLimiter`）、LLM 每日预算的
# 「估算-reserve」协调和运维可观测性计数器（`OperationalMetrics`）都是进程内
# 状态。同一容器起多个 worker 会让它们各算各的——`LlmBudgetRepository.reserve`
# 在数据库层是原子的，预算本身不会超发，但限流命中数和可观测性指标会失真。
# MVP 阶段没有 Redis 等共享存储，要扩容请在 Railway 加多个 Service 副本，
# 不要在这里加 worker 数；副本之间的「进程内近似」约束见 docs/deployment.md。


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        proxy_headers=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
        # uvicorn 不看全局事件循环策略，必须显式传工厂，
        # 否则 Windows 上会拿到 ProactorEventLoop 而连不上数据库。
        loop=loop_factory(),
    )


if __name__ == "__main__":
    main()
