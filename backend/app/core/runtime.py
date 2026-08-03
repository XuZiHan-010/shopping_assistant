"""进程级运行时设置。

Windows 默认的 `ProactorEventLoop` 跑不了 psycopg 的异步模式，建立连接时会直接抛
`InterfaceError`。生产环境跑在 Linux 容器里不受影响，但本地开发和测试如果不切换，
**任何访问数据库的请求都会失败**——`/api/ready` 会在数据库健康的情况下返回 503。

麻烦之处在于两类入口的处理方式不同：

- `asyncio.run()`（Seed、OpenAPI 导出等脚本）遵循全局事件循环策略，用
  `configure_event_loop_policy()`；
- **uvicorn 不看全局策略**，它自己构造循环（`uvicorn.loops.asyncio.asyncio_loop_factory`
  在 win32 且非子进程模式下硬编码 `ProactorEventLoop`），必须用 `loop_factory()`
  把工厂显式传给它。

只做前者会留下一个隐蔽的坑：测试全绿，服务却连不上库。
"""

from __future__ import annotations

import asyncio
import sys


def configure_event_loop_policy() -> bool:
    """为 `asyncio.run()` 类入口切换事件循环策略。

    幂等：已经是目标策略时不重复设置。返回是否实际切换过，便于测试断言。

    **对 uvicorn 无效**，服务入口请用 `loop_factory()`。
    """

    if sys.platform != "win32":
        return False

    if isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
        return False

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return True


def loop_factory() -> str:
    """返回传给 `uvicorn.run(loop=...)` 的循环工厂。

    用 uvicorn 的 `"<module>:<attribute>"` 导入串扩展点，而不是直接传可调用对象：
    后者虽然运行时可用，但 uvicorn 把该参数标注成了字符串字面量类型，
    传函数会导致类型检查失败。

    Windows 上指向 `SelectorEventLoop`；其他平台返回 `"auto"`，
    保留 uvicorn 原有的 uvloop 优先行为。
    """

    if sys.platform == "win32":
        return "asyncio:SelectorEventLoop"
    return "auto"
