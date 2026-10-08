"""本地嵌入模型（PRD A7，契约 §6.14）。

嵌入模型必须在 backend 进程内运行（本版没有 Worker）。这里只定义：

- `Embedder` 协议：索引构建与查询共用，测试用确定性假实现替身；
- `FastEmbedEmbedder`：基于 fastembed（ONNX Runtime，不依赖 PyTorch）的实现，
  首次使用时才加载模型，加载失败不影响进程启动——检索按 §7.6 降级为关键词并显式标注。

本地推理不是 LLM 调用，不产生费用（R3 不适用）。模型文件在镜像构建期下载到
`EMBEDDING_CACHE_DIR`，运行时不访问外网。
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Sequence
from typing import Any, Protocol


class EmbeddingUnavailableError(RuntimeError):
    """模型未配置、加载失败或推理失败；调用方据此走降级，不向用户透出原文。"""


class Embedder(Protocol):
    #: 写入索引版本的模型标识；查询时只用同一模型生成的向量（换模型须重建索引）。
    @property
    def model_name(self) -> str: ...

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """线程安全的懒加载封装；推理是 CPU 密集同步调用，调用方须放进工作线程。"""

    def __init__(
        self,
        model_name: str,
        *,
        cache_dir: str | None = None,
        threads: int = 1,
        batch_size: int = 4,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._threads = threads
        # 小批量：整批编码会让 ONNX Runtime 的内存池按最长批次膨胀（N4-C Task 3 实测）。
        self._batch_size = batch_size
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    fastembed = importlib.import_module("fastembed")
                    self._model = fastembed.TextEmbedding(
                        self._model_name, cache_dir=self._cache_dir, threads=self._threads
                    )
                except Exception as exc:  # 依赖缺失、模型文件缺失、ONNX 加载失败都一样降级
                    raise EmbeddingUnavailableError("embedding model unavailable") from exc
            return self._model

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        try:
            return [list(map(float, v)) for v in model.query_embed(list(texts))]
        except Exception as exc:
            raise EmbeddingUnavailableError("query embedding failed") from exc

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        try:
            return [
                list(map(float, v))
                for v in model.passage_embed(list(texts), batch_size=self._batch_size)
            ]
        except Exception as exc:
            raise EmbeddingUnavailableError("passage embedding failed") from exc


def build_embedder(
    model_name: str | None, *, cache_dir: str | None = None, threads: int = 1
) -> Embedder | None:
    """`EMBEDDING_MODEL` 为空时返回 None：向量召回关闭，检索如实标注关键词降级。"""

    if not model_name or not model_name.strip():
        return None
    return FastEmbedEmbedder(model_name.strip(), cache_dir=cache_dir, threads=threads)
