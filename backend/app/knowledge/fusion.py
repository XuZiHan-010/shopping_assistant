"""关键词与向量召回的融合（PRD A7，契约 §6.14）。

用倒数排名融合（RRF）：只看名次、不看分数，关键词加权分与余弦相似度不需要先归一化到同一量纲——
这是两种异质检索融合的稳妥默认（Cormack 等，2009）。
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence

#: RRF 平滑常数；60 是原论文与主流实现的默认值，不针对本评测集调参。
RRF_K = 60


def rrf_fuse[T: Hashable](
    *rankings: Sequence[tuple[T, float]], k: int = RRF_K
) -> list[tuple[T, float]]:
    """每路给出 `(文档, 原始分)` 的有序列表（原始分只用于展示，不参与融合）。

    返回按融合分降序的 `(文档, 融合分)`；同分按首次出现的顺序（关键词在前时偏向关键词）。
    """

    fused: dict[T, float] = {}
    for ranking in rankings:
        for rank, (item, _score) in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda pair: -pair[1])
