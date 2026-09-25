"""GenAI API tests (SRS 1.10 item 11): the real provider adapters against fake vendor APIs - the exact request
each vendor receives, response parsing, error mapping, the controlled retry policy and the structured-output
schema. No network and no API key are needed and no vendor is ever contacted."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from supportnova.core.config import Settings
from supportnova.core.errors import AIProviderError
from supportnova.genai_pipeline.providers import build_provider
from supportnova.genai_pipeline.providers.base import AIRequest
from supportnova.genai_pipeline.providers.http_providers import GeminiProvider, OpenAIProvider
from supportnova.genai_pipeline.runner import run_stage
from supportnova.genai_pipeline.schemas import provider_schema

COMM = "customer_communication.v1"
VALID_COMM = {"schema_version": "1.0", "complaint_id": "CMP-00001", "tone": "professional", "subject": "Update on CMP-00001",
              "customer_response": "Thank you for contacting Lumora. We are checking your order with the carrier.",
              "follow_up_message": None,
              "claims": [{"statement": "The order is late.", "source_type": "complaint", "source_ref": "complaint"}]}
# keywords vendor structured-output modes reject (Anthropic: numeric/string/array constraints; OpenAI strict mode)
REJECTED = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
            "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties", "$schema", "$id", "const"}


def _request(schema_name: str = COMM, *, inline: bool = False) -> AIRequest:
    return AIRequest(stage="communication", system="SYSTEM PROMPT", user="USER PROMPT", schema_name=schema_name,
                     json_schema=provider_schema(schema_name, inline_refs=inline), temperature=0.1, max_output_tokens=2048,
                     timeout_seconds=10)


def _openai_reply(content: str, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"id": "chatcmpl-1", "model": "gpt-4.1-mini", "usage": {"prompt_tokens": 20, "completion_tokens": 30},
                                     "choices": [{"message": {"role": "assistant", "content": content, **extra}, "finish_reason": "stop"}]},
                          headers={"x-request-id": "req_1"})


# ------------------------------------------------------------------ structured-output schema
@pytest.mark.parametrize("name", ["complaint_analysis.v1", COMM])
@pytest.mark.parametrize("inline", [False, True])
def test_structured_output_schema_uses_only_supported_keywords(name: str, inline: bool) -> None:
    schema = provider_schema(name, inline_refs=inline)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            keywords = {k for k in node if not (path.endswith(".properties") or path.endswith(".$defs"))}
            assert not (REJECTED & keywords), (path, REJECTED & keywords)
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False, path
                assert set(node.get("required", [])) == set(node.get("properties", {})), path  # optional = nullable
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(schema, "$")
    if inline:
        assert '"$ref"' not in json.dumps(schema)


def test_schema_adaptation_keeps_field_names_that_look_like_keywords(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from supportnova.genai_pipeline import schemas

    custom = {"type": "object", "properties": {"title": {"type": "string", "minLength": 3}, "pattern": {"type": "string"}},
              "required": ["title"]}
    monkeypatch.setattr(schemas, "load_schema", lambda name: custom)
    adapted = schemas.provider_schema("custom.v1")
    assert set(adapted["properties"]) == {"title", "pattern"}          # live "change JSON schema" stays safe
    assert "minLength" not in adapted["properties"]["title"]           # the constraint itself is still stripped
    assert adapted["required"] == ["title", "pattern"] and adapted["additionalProperties"] is False


# ------------------------------------------------------------------ provider selection
def test_factory_selects_the_configured_provider() -> None:
    claude = build_provider(Settings(ai_provider="anthropic", ai_api_key="sk-ant-test"))
    assert (claude.name, claude.model) == ("anthropic", "claude-opus-5")
    assert build_provider(Settings(ai_provider="real", ai_api_key="sk-ant-test")).name == "anthropic"
    assert build_provider(Settings(ai_provider="openai", ai_api_key="sk-test")).name == "openai"
    assert build_provider(Settings(ai_provider="gemini", ai_api_key="AIza-test")).name == "gemini"
    assert build_provider(Settings(ai_provider="anthropic", ai_api_key="sk-ant-test", ai_model="claude-sonnet-5")).model == "claude-sonnet-5"


def test_there_is_no_mock_provider() -> None:
    with pytest.raises(ValueError, match="AI_PROVIDER"):
        Settings(ai_provider="mock")


def test_a_missing_key_fails_honestly_and_is_not_retried() -> None:
    s = Settings(ai_provider="openai", ai_model="gpt-4.1-mini")      # vendor chosen, key not yet added
    assert (s.resolved_provider, s.resolved_model, s.ai_configured) == ("openai", "gpt-4.1-mini", False)
    provider = build_provider(s)
    assert (provider.name, provider.model) == ("openai", "gpt-4.1-mini")
    with pytest.raises(AIProviderError) as err:
        provider.generate(_request())
    assert err.value.kind == "not_configured" and not err.value.retryable
    result = run_stage(provider, _request(), max_attempts=3, sleep=lambda s: None)
    assert not result.ok and [a.error_type for a in result.attempts] == ["not_configured"]


def test_secrets_file_overrides_the_settings_file(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from supportnova.core import config

    monkeypatch.delenv("AI_PROVIDER", raising=False)
    (tmp_path / ".env").write_text("AI_PROVIDER=openai\nAI_API_KEY=\nAI_MODEL=gpt-4.1-mini\n", encoding="utf-8")
    (tmp_path / ".env.secrets").write_text("AI_API_KEY=sk-test-from-secrets\n", encoding="utf-8")
    s = Settings(_env_file=(str(tmp_path / ".env"), str(tmp_path / ".env.secrets")))
    assert s.ai_api_key is not None and s.ai_api_key.get_secret_value() == "sk-test-from-secrets"
    assert (s.resolved_provider, s.resolved_model) == ("openai", "gpt-4.1-mini")
    monkeypatch.delenv("SUPPORTNOVA_ENV_FILE", raising=False)
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in config._env_files()] == [".env", ".env.secrets"]


# ------------------------------------------------------------------ Anthropic (official SDK)
def _anthropic(handler: Callable[[Any], Any], model: str = "claude-opus-5") -> Any:
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")  # the SDK's HTTP layer
    from supportnova.genai_pipeline.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider("sk-ant-test", model)
    provider._client = anthropic.Anthropic(api_key="sk-ant-test", max_retries=0,
                                           http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    return provider


def _claude_reply(text: str, stop_reason: str = "end_turn") -> Any:
    import httpx2
    return httpx2.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
                                      "content": [{"type": "text", "text": text}], "stop_reason": stop_reason,
                                      "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 34}})


def test_anthropic_request_uses_structured_output_and_parses_the_reply() -> None:
    seen: dict[str, Any] = {}

    def handler(req: Any) -> Any:
        seen.update(path=req.url.path, beta=req.headers.get("anthropic-beta"), key=req.headers.get("x-api-key"),
                    body=json.loads(req.content))
        return _claude_reply(json.dumps(VALID_COMM))

    request = _request()
    reply = _anthropic(handler).generate(request)
    body = seen["body"]
    assert seen["path"] == "/v1/messages" and seen["key"] == "sk-ant-test"
    assert body["model"] == "claude-opus-5"
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": request.json_schema}
    assert body["output_config"]["effort"] == "medium"
    assert body["fallbacks"] == "default" and seen["beta"] == "server-side-fallback-2026-07-01"
    assert "temperature" not in body                                  # current Claude models reject sampling params
    assert body["system"][0]["text"] == "SYSTEM PROMPT" and body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [{"role": "user", "content": "USER PROMPT"}]
    assert json.loads(reply.text) == VALID_COMM
    assert (reply.provider, reply.input_tokens, reply.output_tokens, reply.stop_reason) == ("anthropic", 12, 34, "end_turn")


def test_anthropic_models_without_fallback_or_effort_use_the_plain_endpoint() -> None:
    seen: dict[str, Any] = {}

    def handler(req: Any) -> Any:
        seen.update(query=str(req.url.query), beta=req.headers.get("anthropic-beta"), body=json.loads(req.content))
        return _claude_reply(json.dumps(VALID_COMM))

    _anthropic(handler, model="claude-haiku-4-5-20251001").generate(_request())
    assert "beta" not in seen["query"] and seen["beta"] is None
    assert "fallbacks" not in seen["body"] and "effort" not in seen["body"]["output_config"]


@pytest.mark.parametrize(("status", "kind", "retryable"), [
    (429, "rate_limited", True), (529, "server_error", True), (500, "server_error", True),
    (401, "authentication", False), (400, "bad_request", False),
])
def test_anthropic_errors_map_to_the_retry_policy(status: int, kind: str, retryable: bool) -> None:
    import httpx2

    def handler(req: Any) -> Any:
        return httpx2.Response(status, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})

    with pytest.raises(AIProviderError) as err:
        _anthropic(handler).generate(_request())
    assert (err.value.kind, err.value.retryable) == (kind, retryable)


def test_anthropic_refusal_is_not_retried_as_invalid_output() -> None:
    with pytest.raises(AIProviderError) as err:
        _anthropic(lambda req: _claude_reply("", stop_reason="refusal")).generate(_request())
    assert err.value.kind == "refusal" and err.value.retryable is False


# ------------------------------------------------------------------ OpenAI (REST)
def test_openai_request_uses_strict_json_schema() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(url=str(req.url), auth=req.headers.get("authorization"), body=json.loads(req.content))
        return _openai_reply(json.dumps(VALID_COMM))

    request = _request()
    reply = OpenAIProvider("sk-test", "gpt-4.1-mini", transport=httpx.MockTransport(handler)).generate(request)
    fmt = seen["body"]["response_format"]
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == "Bearer sk-test"
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == request.json_schema and fmt["json_schema"]["name"] == "customer_communication_v1"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert json.loads(reply.text) == VALID_COMM and reply.request_id == "req_1" and reply.input_tokens == 20


def test_openai_compatible_gateway_via_base_url() -> None:
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        return _openai_reply(json.dumps(VALID_COMM))

    OpenAIProvider("sk-test", "gpt-4.1-mini", base_url="https://gateway.example/v1/",
                   transport=httpx.MockTransport(handler)).generate(_request())
    assert urls == ["https://gateway.example/v1/chat/completions"]


@pytest.mark.parametrize(("status", "kind", "retryable"), [
    (429, "rate_limited", True), (503, "server_error", True), (401, "authentication", False), (400, "bad_request", False),
])
def test_openai_errors_map_to_the_retry_policy(status: int, kind: str, retryable: bool) -> None:
    provider = OpenAIProvider("sk-test", "gpt-4.1-mini", transport=httpx.MockTransport(lambda req: httpx.Response(status, text="err")))
    with pytest.raises(AIProviderError) as err:
        provider.generate(_request())
    assert (err.value.kind, err.value.retryable) == (kind, retryable)


def test_openai_refusal_is_reported() -> None:
    provider = OpenAIProvider("sk-test", "gpt-4.1-mini",
                              transport=httpx.MockTransport(lambda req: _openai_reply("", refusal="I can't help with that.")))
    with pytest.raises(AIProviderError) as err:
        provider.generate(_request())
    assert err.value.kind == "refusal"


# ------------------------------------------------------------------ Gemini (REST)
def _gemini_reply(text: str, finish: str = "STOP") -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
                                     "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7}, "modelVersion": "gemini-2.5-flash"})


def test_gemini_key_travels_in_a_header_never_the_url() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(url=str(req.url), key=req.headers.get("x-goog-api-key"), body=json.loads(req.content))
        return _gemini_reply(json.dumps(VALID_COMM))

    request = _request(inline=True)
    reply = GeminiProvider("AIza-secret", "gemini-2.5-flash", transport=httpx.MockTransport(handler)).generate(request)
    assert "AIza-secret" not in seen["url"] and seen["key"] == "AIza-secret"
    assert seen["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    config = seen["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json" and config["responseJsonSchema"] == request.json_schema
    assert json.loads(reply.text) == VALID_COMM and reply.output_tokens == 7


def test_gemini_falls_back_to_json_mode_when_schema_is_rejected() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        if len(bodies) == 1:
            return httpx.Response(400, text="Unknown name 'responseJsonSchema'")
        return _gemini_reply(json.dumps(VALID_COMM))

    GeminiProvider("AIza-x", "gemini-2.5-flash", transport=httpx.MockTransport(handler)).generate(_request(inline=True))
    assert "responseJsonSchema" in bodies[0]["generationConfig"] and "responseJsonSchema" not in bodies[1]["generationConfig"]


def test_gemini_safety_block_is_a_refusal() -> None:
    provider = GeminiProvider("AIza-x", "gemini-2.5-flash", transport=httpx.MockTransport(lambda req: _gemini_reply("", "SAFETY")))
    with pytest.raises(AIProviderError) as err:
        provider.generate(_request(inline=True))
    assert err.value.kind == "refusal"


# ------------------------------------------------------------------ controlled retries with a real adapter (SRS Step 47)
def _scripted_openai(replies: list[httpx.Response]) -> tuple[OpenAIProvider, list[dict[str, Any]]]:
    bodies: list[dict[str, Any]] = []
    queue = iter(replies)

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return next(queue)

    return OpenAIProvider("sk-test", "gpt-4.1-mini", transport=httpx.MockTransport(handler)), bodies


def test_invalid_json_is_retried_with_the_validation_errors_then_accepted() -> None:
    provider, bodies = _scripted_openai([_openai_reply('{"schema_version": "1.0", "complaint_id": '), _openai_reply(json.dumps(VALID_COMM))])
    result = run_stage(provider, _request(), max_attempts=3, sleep=lambda s: None)
    assert result.ok and [a.parsed_ok for a in result.attempts] == [False, True]
    assert result.attempts[0].error_type == "invalid_output" and "JSON" in (result.attempts[0].error_message or "")
    assert "<validation_feedback>" in bodies[1]["messages"][1]["content"]     # the errors go back to the model


def test_schema_violation_is_retried() -> None:
    missing = {k: v for k, v in VALID_COMM.items() if k != "customer_response"}
    provider, _ = _scripted_openai([_openai_reply(json.dumps(missing)), _openai_reply(json.dumps(VALID_COMM))])
    result = run_stage(provider, _request(), max_attempts=3, sleep=lambda s: None)
    assert result.ok and "customer_response" in (result.attempts[0].error_message or "")


def test_retries_are_bounded_and_the_failure_is_reported() -> None:
    provider, bodies = _scripted_openai([_openai_reply("not json")] * 5)
    result = run_stage(provider, _request(), max_attempts=3, sleep=lambda s: None)
    assert not result.ok and len(result.attempts) == 3 and len(bodies) == 3   # no infinite retries
    assert result.error and result.error.startswith("invalid_output")      # the pipeline routes this to manual review


def test_transient_errors_are_retried_but_authentication_errors_are_not() -> None:
    provider, _ = _scripted_openai([httpx.Response(503, text="busy"), _openai_reply(json.dumps(VALID_COMM))])
    assert run_stage(provider, _request(), max_attempts=3, sleep=lambda s: None).ok
    provider, bodies = _scripted_openai([httpx.Response(401, text="bad key")] * 3)
    result = run_stage(provider, _request(), max_attempts=3, sleep=lambda s: None)
    assert not result.ok and len(bodies) == 1 and result.attempts[0].error_type == "authentication"
