"""数据库连接串归一化。

单独成模块，是为了让 `Settings`（Web 服务）与 `JobSettings`（离线 Cron）共用
同一份实现：`job_config` 已经在 import `config` 的 `AppEnvironment`，把函数放进
任一方都会形成循环导入。

曾经这段逻辑只存在于 `Settings`，于是 Web 服务连得上、Cron 一启动就
`ModuleNotFoundError: No module named 'psycopg2'`——两条路径对同一个环境变量
给出了不同解释。共享一份实现是这个缺口的根治方式。
"""

from __future__ import annotations

from typing import Any

_BARE_SCHEME = "postgresql://"
_PSYCOPG_SCHEME = "postgresql+psycopg://"


def normalize_postgres_url(value: Any) -> Any:
    """把 Railway 注入的 ``postgresql://`` 补成 ``postgresql+psycopg://``。

    不补的话 SQLAlchemy 会按无驱动后缀的 URL 选中默认的 psycopg2 方言，而项目
    只装 psycopg 3。已带后缀的 URL 与非字符串原样返回，交由字段本身的校验处理。
    """

    if isinstance(value, str) and value.startswith(_BARE_SCHEME):
        return value.replace(_BARE_SCHEME, _PSYCOPG_SCHEME, 1)
    return value
