"""Anthropic Claude provider (official ``anthropic`` Python SDK).

* Structured outputs: ``output_config.format`` with the complaint JSON Schema - the first text block
  is guaranteed to be JSON matching the schema; the runner still validates it independently.
* Default model ``claude-opus-5`` (AI_MODEL overrides). Thinking is left at the model default
  (adaptive); ``output_config.effort`` (AI_EFFORT, default "medium") trades depth for latency to meet
  the SRS 20-second target. Sampling parameters are not sent (rejected by current models).
* Server-side refusal fallbacks (``fallbacks: "default"``, beta ``server-side-fallback-2026-07-01``)
  are enabled for models that support them, so a classifier decline is re-run on Anthropic's
  recommended fallback model instead of failing the complaint.
* SDK retries are disabled (``max_retries=0``): the pipeline runner owns the controlled retry policy
  so that every attempt, including invalid outputs, is logged as retry evidence (SRS Step 47).
"""

from __future__ import annotations

import time
from typing import Any

from supportnova.core.errors import AIProviderError, AITimeout

from .base import AIProvider, AIRequest, AIResponse

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-opus-5-5"}


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, *, base_url: str | None = None, effort: str | None = "medium",
                 refusal_fallback: bool = True) -> None:
        super().__init__(model)
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url or None, max_retries=0)
        self.effort = effort
        self.refusal_fallback = refusal_fallback and model in FALLBACK_MODELS

    def _effort_supported(self) -> bool:
        return bool(self.effort) and not self.model.startswith("claude-haiku")

    def generate(self, request: AIRequest) -> AIResponse:
        a = self._anthropic
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.json_schema}}
        if self._effort_supported():
            output_config["effort"] = self.effort
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max(request.max_output_tokens, 4096),
            # stable instructions + reference data first so the prefix can be prompt-cached
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": self.user_content(request)}],
            "output_config": output_config,
        }
        client = self._client.with_options(timeout=request.timeout_seconds)
        started = time.perf_counter()
        try:
            if self.refusal_fallback:
                resp = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = client.messages.create(**kwargs)
        except a.APITimeoutError as exc:
            raise AITimeout() from exc
        except a.RateLimitError as exc:
            raise AIProviderError("Anthropic rate limit reached (429).", retryable=True, kind="rate_limited") from exc
        except (a.AuthenticationError, a.PermissionDeniedError) as exc:
            raise AIProviderError("Anthropic rejected the API key or permissions.", retryable=False,
                                  kind="authentication") from exc
        except (a.BadRequestError, a.NotFoundError, a.UnprocessableEntityError) as exc:
            raise AIProviderError(f"Anthropic rejected the request: {getattr(exc, 'message', exc)}", retryable=False,
                                  kind="bad_request") from exc
        except a.APIStatusError as exc:  # 5xx incl. 529 overloaded
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409, 429)
            raise AIProviderError(f"Anthropic API error {exc.status_code}.", retryable=retryable,
                                  kind="server_error" if retryable else "api_error") from exc
        except a.APIConnectionError as exc:
            raise AIProviderError("Could not reach the Anthropic API.", retryable=True, kind="connection") from exc
        latency = int((time.perf_counter() - started) * 1000)
        if resp.stop_reason == "refusal":
            category = getattr(getattr(resp, "stop_details", None), "category", None)
            raise AIProviderError(f"The model declined the request (refusal, category={category}).", retryable=False,
                                  kind="refusal")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        usage = getattr(resp, "usage", None)
        return AIResponse(text=text, provider=self.name, model=self.model, latency_ms=latency,
                          input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
                          stop_reason=resp.stop_reason, request_id=getattr(resp, "_request_id", None),
                          served_by=getattr(resp, "model", self.model))

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "effort": self.effort if self._effort_supported() else None,
                "structured_outputs": "output_config.format (json_schema)",
                "refusal_fallback": FALLBACK_BETA if self.refusal_fallback else None}
