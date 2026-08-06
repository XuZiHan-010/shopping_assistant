"""DeepSeek OpenAI 兼容适配器；测试仅使用 MockTransport。"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.llm.client import LlmBudget, LlmBudgetExceededError, LlmResult, LlmUnavailableError


class DeepSeekLlmClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings, self._transport = settings, transport

    def is_configured(self) -> bool:
        return bool(self._settings.llm_api_key)

    async def complete(
        self, *, system: str, user: str, fallback: str, budget: LlmBudget
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
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.llm_base_url,
                timeout=self._settings.llm_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/chat/completions",
                    json={
                        "model": self._settings.llm_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "max_tokens": min(remaining, self._settings.llm_max_output_tokens_per_call),
                    },
                    headers={"authorization": f"Bearer {self._settings.llm_api_key}"},
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError):
            return LlmResult(fallback, 0, True)
        tokens = int(body.get("usage", {}).get("total_tokens", 0))
        budget.charge(tokens)
        choices = body.get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        return LlmResult(text or fallback, tokens, not bool(text))
