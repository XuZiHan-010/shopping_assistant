# OpenAPI 机器可读产物设计

## 目标

让前端 F0 可直接将后端 OpenAPI 输入 `openapi-typescript`，同时保留现有的人读文档。

## 方案

`scripts/export_openapi.py` 从一次 `create_app(...).openapi()` 调用取得 schema，并从该对象写出两份产物：

- `docs/api.json`：UTF-8、缩进 JSON、末尾换行；供代码生成工具直接读取。
- `docs/api.md`：同一 JSON 包在 Markdown 代码块内；供人工查阅。

不改变路由、Pydantic Schema、OpenAPI 内容或对外 API 契约。

## 防漂移

契约测试从当前 FastAPI 应用重新生成 schema，分别与两个文件的渲染结果逐字比较；另确认 `api.json` 可直接被 JSON 解析，且不是 Markdown 包装格式。

## 验收

- 运行导出脚本后存在并更新两份产物。
- `docs/api.json` 可被 `openapi-typescript` 直接消费。
- 任一产物与应用 schema 不一致时，测试失败并提示重新导出。
