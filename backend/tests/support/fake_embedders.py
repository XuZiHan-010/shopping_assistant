"""确定性假嵌入器（N4-C）：测试不下载、不加载真实模型。

- `BigramEmbedder`：字符二元组哈希到固定维度，语义很弱但对中文关键词重叠足够稳定，
  用作「较好」的模型；
- `RandomEmbedder`：整段文本哈希成伪随机向量，与内容无关，用作「明显更差」的模型；
- `FailingEmbedder`：任何调用都抛 `EmbeddingUnavailableError`。
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence

from app.knowledge.embedding import EmbeddingUnavailableError

DIMENSIONS = 64


def _bigram_vector(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    lowered = text.lower()
    for i in range(len(lowered) - 1):
        gram = lowered[i : i + 2]
        if gram.strip():
            vector[int(hashlib.md5(gram.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
    if not any(vector):
        vector[0] = 1.0
    return vector


class BigramEmbedder:
    def __init__(self, model_name: str = "fake-bigram") -> None:
        self._model_name = model_name
        self.query_calls = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.query_calls += 1
        return [_bigram_vector(t) for t in texts]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [_bigram_vector(t) for t in texts]


class RandomEmbedder:
    def __init__(self, model_name: str = "fake-random") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def _vector(self, text: str) -> list[float]:
        rng = random.Random(hashlib.sha256(text.encode()).hexdigest())
        return [rng.uniform(-1.0, 1.0) for _ in range(DIMENSIONS)]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class FailingEmbedder:
    def __init__(self, model_name: str = "fake-bigram") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingUnavailableError("fake failure")

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingUnavailableError("fake failure")
