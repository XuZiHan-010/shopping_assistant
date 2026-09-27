"""受信 Skill（PRD A4，契约 §6.11）：索引进静态提示，正文经 `load_skill` 按需加载。

格式与索引思路沿用蓝图 anthropic-commerce-agents@fd4d592（仓库内只读快照）
`commerce-common/commerce_common/skills.py`（目录 + `SKILL.md` + YAML frontmatter，按名字排序），
在这里重新实现并补上蓝图没有的三样：版本号、长度上限、单回合加载数上限。

依赖方向：`skills/` 不 import `repositories/`（§5.6）；`tools/` 不 import 这里的加载实现，
`load_skill` 工具由装配层注册。
"""
