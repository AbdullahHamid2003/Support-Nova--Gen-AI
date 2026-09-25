"""OpenAI (or OpenAI-compatible, via AI_BASE_URL) and Google Gemini providers over their REST APIs.

Both request JSON constrained by the complaint schema (OpenAI ``response_format: json_schema`` with
``strict``; Gemini ``responseMimeType: application/json`` + ``responseJsonSchema``). Output is always
re-validated by the runner. Retryable failures (429, 5xx, timeouts, connection errors) are surfaced
to the runner, which applies the controlled retry policy.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from supportnova.core.errors import AIProviderError, AITimeout

from .base import AIProvider, AIRequest, AIResponse


def _classify(status: int, body: str, vendor: str) -> AIProviderError:
    if status == 429:
        return AIProviderError(f"{vendor} rate limit reached (429).", retryable=True, kind="rate_limited")
    if status in (401, 403):
        return AIProviderError(f"{vendor} rejected the API key or permissions ({status}).", retryable=False,
                               kind="authentication")
    if status >= 500:
        return AIProviderError(f"{vendor} server error ({status}).", retryable=True, kind="server_error")
    return AIProviderError(f"{vendor} rejected the request ({status}): {body[:300]}", retryable=False, kind="bad_request")


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, *, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(model)
        self._key = api_key
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        self._transport = transport

    def generate(self, request: AIRequest) -> AIResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": request.system},
                         {"role": "user", "content": self.user_content(request)}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": request.schema_name.replace(".", "_"), "strict": True,
                                                "schema": request.json_schema}},
            "max_completion_tokens": request.max_output_tokens,
        }
        if self.model.startswith(("gpt-4", "gpt-3.5")):
            body["temperature"] = request.temperature
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=request.timeout_seconds, transport=self._transport) as client:
                resp = client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as exc:
            raise AITimeout() from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Could not reach the OpenAI API: {exc}", retryable=True, kind="connection") from exc
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code >= 400:
            raise _classify(resp.status_code, resp.text, "OpenAI")
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise AIProviderError("The model declined the request (refusal).", retryable=False, kind="refusal")
        usage = data.get("usage") or {}
        return AIResponse(text=message.get("content") or "", provider=self.name, model=self.model,
                          latency_ms=latency, input_tokens=usage.get("prompt_tokens"),
                          output_tokens=usage.get("completion_tokens"), stop_reason=choice.get("finish_reason"),
                          request_id=resp.headers.get("x-request-id"), served_by=data.get("model"))


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(model)
        self._key = api_key
        self._transport = transport

    def generate(self, request: AIRequest) -> AIResponse:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        generation: dict[str, Any] = {"responseMimeType": "application/json", "responseJsonSchema": request.json_schema,
                                      "temperature": request.temperature, "maxOutputTokens": request.max_output_tokens}
        body = {"systemInstruction": {"parts": [{"text": request.system}]},
                "contents": [{"role": "user", "parts": [{"text": self.user_content(request)}]}],
                "generationConfig": generation}
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=request.timeout_seconds, transport=self._transport) as client:
                # the key travels in a header, never in the URL (URLs end up in proxy and access logs)
                headers = {"x-goog-api-key": self._key}
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code == 400 and "responseJsonSchema" in resp.text:
                    generation.pop("responseJsonSchema", None)   # older API versions: JSON mode + schema in prompt
                    resp = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise AITimeout() from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Could not reach the Gemini API: {exc}", retryable=True, kind="connection") from exc
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code >= 400:
            raise _classify(resp.status_code, resp.text, "Gemini")
        data = resp.json()
        candidate = (data.get("candidates") or [{}])[0]
        if candidate.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
            raise AIProviderError("The model declined the request (safety).", retryable=False, kind="refusal")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}
        return AIResponse(text=text, provider=self.name, model=self.model, latency_ms=latency,
                          input_tokens=usage.get("promptTokenCount"), output_tokens=usage.get("candidatesTokenCount"),
                          stop_reason=candidate.get("finishReason"), served_by=data.get("modelVersion"))
