"""A3 工具注册表与四类闸门：新 Agent 内核唯一的数据出入口（§5.6、§6.9）。

依赖方向：`loop → skills → tools → services / repositories`；本包不得 import `app.agent.loop`
或 `app.skills`，工具必须能脱离循环单独测试。
"""
