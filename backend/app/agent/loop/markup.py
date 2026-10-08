"""上游模型泄漏的内部标记识别；主循环与压缩摘要共用（避免 compaction 反向依赖 runner）。"""

from __future__ import annotations

import re
from typing import Final

#: DeepSeek 内部工具调用标记（半角或全角竖线，如 `<｜｜DSML｜｜ calls>`）。
#: 2026-09-30 E5 真实对比中观察到：模型偶尔把这套工具调用语法直接写进正文。
TOOL_CALL_MARKUP: Final = re.compile(r"<\s*/?\s*[|｜]+\s*DSML\s*[|｜]+")
