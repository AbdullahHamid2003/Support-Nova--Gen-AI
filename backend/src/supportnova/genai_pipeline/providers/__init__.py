"""Provider factory: AI_PROVIDER=openai|anthropic|gemini|real selects the implementation; AI_API_KEY
authenticates it. Switching vendor is configuration only (no code changes).

There is no fallback that fabricates output: without a key the provider reports ``not_configured`` on every
call, the GenAI step is recorded as failed and the complaint goes to human review with the Python decision."""

from __future__ import annotations

from supportnova.core.config import Settings, get_settings
from supportnova.core.errors import AIProviderError
from supportnova.core.logging import get_logger

from .base import AIProvider, AIRequest, AIResponse

log = get_logger(__name__)
_cached: tuple[tuple[str, str, bool], AIProvider] | None = None
_forced: AIProvider | None = None

__all__ = ["AIProvider", "AIRequest", "AIResponse", "get_provider", "use_provider"]


class UnconfiguredProvider(AIProvider):
    """Stands in for the configured vendor while no API key is set: every call fails honestly."""

    def __init__(self, name: str, model: str) -> None:
        super().__init__(model)
        self.name = name

    def generate(self, request: AIRequest) -> AIResponse:
        raise AIProviderError("No AI_API_KEY is set on the server, so the AI step cannot run.",
                              retryable=False, kind="not_configured")


def build_provider(settings: Settings) -> AIProvider:
    provider = settings.resolved_provider
    key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else ""
    model = settings.resolved_model
    if not key:
        log.warning("AI_PROVIDER=%s but AI_API_KEY is empty - the GenAI step will report not_configured", provider)
        return UnconfiguredProvider(provider, model)
    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(key, model, base_url=settings.ai_base_url, effort=settings.ai_effort,
                                 refusal_fallback=settings.ai_refusal_fallback)
    if provider == "gemini":
        from .http_providers import GeminiProvider
        return GeminiProvider(key, model)
    from .http_providers import OpenAIProvider
    return OpenAIProvider(key, model, base_url=settings.ai_base_url)


def use_provider(provider: AIProvider | None) -> None:
    """Send every GenAI call to ``provider`` (None restores the configured one). Used by the test suite, which
    must stay deterministic and must not spend a paid API's credit."""
    global _forced
    _forced = provider


def get_provider() -> AIProvider:
    """Process-wide provider instance (rebuilt when the configuration changes)."""
    global _cached
    if _forced is not None:
        return _forced
    settings = get_settings()
    signature = (settings.resolved_provider, settings.resolved_model, bool(settings.ai_api_key))
    if _cached is None or _cached[0] != signature:
        _cached = (signature, build_provider(settings))
    return _cached[1]
