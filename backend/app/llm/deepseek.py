"""DeepSeek OpenAI 兼容适配器；测试仅使用 MockTransport。"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx

from app.core.config import Settings
from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
    LlmCallOptions,
    LlmFailureKind,
    LlmResult,
    LlmUnavailableError,
)

logger = logging.getLogger(__name__)


class DeepSeekLlmClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings, self._transport = settings, transport

    def is_configured(self) -> bool:
        return bool(self._settings.llm_api_key)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmResult:
        if not self.is_configured():
            raise LlmUnavailableError("未配置 LLM_API_KEY")
        budget.charge_call()
        # 事后记账挡不住一次超支：预算耗尽时这次调用照样要付钱。因此先在本地拦截，
        # 再把剩余额度作为 max_tokens 随请求发出，让上限对上游同样生效。
        # max_tokens 限制的是生成部分，而预算按 total_tokens 记，因此这是上界而非精确等式。
        remaining = budget.max_tokens - budget.tokens
        if remaining <= 0:
            raise LlmBudgetExceededError(f"单请求 LLM token 已达上限 {budget.max_tokens}")
        kind: LlmFailureKind | None = None
        status_code: int | None = None
        content = ""
        usage: Mapping[object, object] | None = None
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        usage_known = False
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.llm_base_url,
                timeout=self._settings.llm_timeout_seconds,
                transport=self._transport,
            ) as client:
                payload: dict[str, object] = {
                    "model": self._settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "max_tokens": min(remaining, self._settings.llm_max_output_tokens_per_call),
                }
                if (
                    options.thinking == "disabled"
                    and self._settings.llm_disable_thinking_for_structured
                ):
                    payload["thinking"] = {"type": "disabled"}
                    if options.json_output:
                        payload["response_format"] = {"type": "json_object"}
                response = await client.post(
                    "/chat/completions",
                    json=payload,
                    headers={"authorization": f"Bearer {self._settings.llm_api_key}"},
                )
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError("响应顶层不是对象")
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
                raise ValueError("响应 choices 形状无效")
            message = choices[0].get("message")
            if not isinstance(message, Mapping):
                raise ValueError("响应 message/content 形状无效")
            raw_content = message.get("content")
            if not isinstance(raw_content, str):
                raise ValueError("响应 message/content 形状无效")
            content = raw_content
            usage = body.get("usage")
            if usage is not None and not isinstance(usage, Mapping):
                raise ValueError("响应 usage 形状无效")
            if usage is not None:
                total_tokens = _usage_value(usage, "total_tokens")
                input_tokens = _usage_value(usage, "prompt_tokens")
                output_tokens = _usage_value(usage, "completion_tokens")
                usage_known = {"total_tokens", "prompt_tokens", "completion_tokens"} <= usage.keys()
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            kind = {
                401: LlmFailureKind.HTTP_401,
                403: LlmFailureKind.HTTP_403,
                429: LlmFailureKind.HTTP_429,
            }.get(status_code, LlmFailureKind.HTTP_OTHER)
        except httpx.TimeoutException:
            kind = LlmFailureKind.TIMEOUT
        except httpx.NetworkError:
            kind = LlmFailureKind.NETWORK
        except ValueError:
            kind = LlmFailureKind.BAD_PAYLOAD
        except httpx.HTTPError:
            kind = LlmFailureKind.NETWORK

        if kind is not None:
            logger.warning(
                "llm_upstream_failed",
                extra={
                    "failure_kind": kind.value,
                    "status_code": status_code,
                    "model": self._settings.llm_model,
                },
            )
            return LlmResult(
                fallback,
                0,
                True,
                failure_kind=kind,
                usage_known=kind in {LlmFailureKind.HTTP_401, LlmFailureKind.HTTP_403},
            )

        budget.charge(total_tokens)
        return LlmResult(
            content,
            total_tokens,
            False,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_known=usage_known,
        )


def _usage_value(usage: Mapping[object, object], key: str) -> int:
    value = usage.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"响应 usage.{key} 无效")
    return value
