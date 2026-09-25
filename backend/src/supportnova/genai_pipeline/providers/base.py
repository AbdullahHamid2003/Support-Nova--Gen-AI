"""GenAI provider abstraction. Pipeline code depends only on this interface; the concrete
provider is selected by configuration (AI_PROVIDER / AI_MODEL / AI_API_KEY)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AIRequest:
    stage: str                      # "analysis" | "communication"
    system: str
    user: str
    schema_name: str
    json_schema: dict[str, Any]     # provider-adapted structured-output schema
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    attempt: int = 1
    correction: str | None = None   # validation feedback appended on controlled retries


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    request_id: str | None = None
    served_by: str | None = None


class AIProvider(ABC):
    name: str = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """Return the raw JSON text produced for ``request`` (validation happens in the runner)."""

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model}

    @staticmethod
    def user_content(request: AIRequest) -> str:
        if request.correction:
            return (request.user + "\n\n<validation_feedback>\n" + request.correction +
                    "\nReturn a corrected JSON object only.\n</validation_feedback>")
        return request.user
