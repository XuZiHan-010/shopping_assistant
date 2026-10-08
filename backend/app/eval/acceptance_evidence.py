"""手动合成评测专用证据账本；不进入生产路径，不代表费用授权。

每次调用先追加预留、再调用原费用守卫，返回后立即保存合成响应。未知用量、异常、
中断和重复 ID 均停止批次，禁止自动重试；跨日期/进程继续使用同一文件且不重置限额。
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.llm.client import DEFAULT_LLM_CALL_OPTIONS, ConversationalLlmClient, LlmStreamEvent


def validate_settings(settings: Settings) -> None:
    url = make_url(settings.database_url)
    if url.host not in {"localhost", "127.0.0.1"} or not (url.database or "").endswith("_test"):
        raise ValueError("验收只允许本地可丢弃 _test 库")
    if (
        not settings.llm_api_key
        or settings.llm_model != "deepseek-flash"
        or settings.llm_protocol != "openai"
        or settings.llm_base_url.rstrip("/") != "https://api.deepseek.com"
        or settings.memory_extraction_max_tokens != 4000
    ):
        raise ValueError("须使用 DeepSeek OpenAI 协议、deepseek-flash、记忆预算 4000")


def prepare_output(path: Path) -> None:
    """收费之前确认目录可写且不会覆盖已有结果；中断后也不自动覆盖重跑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write('{"status":"PREPARED","complete":false}\n')


def append_evidence(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(row, ensure_ascii=False) + "\n")
        output.flush()
        os.fsync(output.fileno())


class EvidenceBatch:
    def __init__(self, path: Path, *, max_calls: int = 442, max_tokens: int = 2_000_000):
        if not 0 < max_calls <= 442 or not 0 < max_tokens <= 2_000_000:
            raise ValueError("不得扩大验收批次上限")
        self.path = path
        self.header: dict[str, Any] = {
            "event": "BATCH", "max_calls": max_calls, "max_tokens": max_tokens,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock():
            if path.exists():
                if self._rows()[0] != self.header:
                    raise ValueError("批次上限不可修改")
            else:
                append_evidence(path, self.header)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            yield
        finally:
            os.close(descriptor)
            lock.unlink()

    def _rows(self) -> list[dict[str, Any]]:
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        if not rows:
            raise ValueError("批次账本为空，禁止重置")
        return rows

    def configure(self, settings: Settings) -> None:
        """只保存白名单配置，不序列化 Settings 或连接串中的凭证。"""
        validate_settings(settings)
        url = make_url(settings.database_url)
        config = {
            "event": "CONFIG",
            "model": settings.llm_model,
            "protocol": settings.llm_protocol,
            "base_url": settings.llm_base_url,
            "max_output_tokens": settings.llm_max_output_tokens_per_call,
            "memory_max_tokens": settings.memory_extraction_max_tokens,
            "daily_tokens": settings.llm_daily_budget_tokens,
            "disable_thinking_for_structured": settings.llm_disable_thinking_for_structured,
            "database_host": url.host,
            "database_port": url.port,
            "database_name": url.database,
        }
        with self._lock():
            configs = [row for row in self._rows() if row["event"] == "CONFIG"]
            if configs and configs != [config]:
                raise ValueError("批次配置发生变化，须重新核对授权与口径")
            if not configs:
                append_evidence(self.path, config)

    def reserve(self, request_id: str, tokens: int, *, payload: str | None = None) -> None:
        if tokens <= 0:
            raise ValueError("预留 token 必须为正数")
        with self._lock():
            rows = self._rows()
            reserved = {r["request_id"]: r["tokens"] for r in rows if r["event"] == "RESERVE"}
            results = {r["request_id"]: r for r in rows if r["event"] == "RESULT"}
            if request_id in reserved:
                raise ValueError("重复请求禁止自动重跑")
            if any(key not in results for key in reserved):
                raise ValueError("批次存在未完成调用，须人工核对用量")
            if any(not r["result"].get("usage_known") for r in results.values()):
                raise ValueError("批次存在未知用量，须人工核对")
            if len(reserved) >= self.header["max_calls"]:
                raise ValueError("批次调用次数已达上限")
            consumed = sum(r["result"]["tokens"] for r in results.values())
            if consumed + tokens > self.header["max_tokens"]:
                raise ValueError("批次 token 余额不足以预留本次最大预算")
            append_evidence(
                self.path,
                {
                    "event": "RESERVE",
                    "request_id": request_id,
                    "tokens": tokens,
                    "synthetic_request": payload,
                },
            )

    def finish(self, request_id: str, result: dict[str, Any]) -> None:
        with self._lock():
            rows = self._rows()
            if not any(r.get("request_id") == request_id and r["event"] == "RESERVE" for r in rows):
                raise ValueError("调用缺少预留")
            if any(r.get("request_id") == request_id and r["event"] == "RESULT" for r in rows):
                raise ValueError("重复结果禁止覆盖")
            append_evidence(
                self.path, {"event": "RESULT", "request_id": request_id, "result": result}
            )

    def client(
        self, inner: ConversationalLlmClient, request_id: str, *, max_output_tokens: int
    ) -> EvidenceClient:
        return EvidenceClient(self, inner, request_id, max_output_tokens)


class EvidenceClient:
    def __init__(
        self,
        batch: EvidenceBatch,
        inner: ConversationalLlmClient,
        request_id: str,
        max_output_tokens: int,
    ):
        self.batch, self.inner = batch, inner
        self.request_id, self.max_output_tokens = request_id, max_output_tokens

    def is_configured(self) -> bool:
        return self.inner.is_configured()

    async def _call(self, method: str, kwargs: dict[str, Any]) -> Any:
        # UTF-8 字节数作为输入的保守上界，包含工具 Schema 与角色元数据。
        # 不改变发给模型的消息、选项或单次预算。
        payload = {k: v for k, v in kwargs.items() if k not in {"budget", "options"}}
        payload["options"] = asdict(kwargs.get("options", DEFAULT_LLM_CALL_OPTIONS))
        serialized = json.dumps(payload, ensure_ascii=False, default=lambda value: asdict(value))
        reserve = max(
            kwargs["budget"].max_tokens,
            len(serialized.encode("utf-8")) + self.max_output_tokens + 1024,
        )
        self.batch.reserve(self.request_id, reserve, payload=serialized)
        try:
            result = await getattr(self.inner, method)(**kwargs)
        except BaseException as exc:
            self.batch.finish(
                self.request_id,
                {"error_type": type(exc).__name__, "tokens": reserve, "usage_known": False},
            )
            raise
        self.batch.finish(self.request_id, asdict(result))
        if not result.usage_known:
            raise ValueError("最后一次调用用量未知，已留存证据，停止批次")
        if not 0 <= result.tokens <= reserve:
            raise ValueError("实际用量超出预留或无效，已留存证据，停止批次")
        return result

    async def complete(self, **kwargs: Any) -> Any:
        return await self._call("complete", kwargs)

    async def converse(self, **kwargs: Any) -> Any:
        return await self._call("converse", kwargs)

    async def converse_stream(self, **kwargs: Any) -> AsyncIterator[LlmStreamEvent]:
        raise ValueError("人工验收只支持非流式调用")
        yield  # pragma: no cover
