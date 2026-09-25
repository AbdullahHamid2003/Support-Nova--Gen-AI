"""Controlled retry runner (SRS Step 47): detect invalid output, log every attempt, retry with
validation feedback up to a fixed limit (never infinite), then hand unresolved failures to manual review."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel

from supportnova.core.errors import AIProviderError
from supportnova.core.logging import get_logger
from supportnova.security.pii import redact

from .fault_injection import FaultInjector
from .parsing import validate_output
from .providers.base import AIProvider, AIRequest, AIResponse

log = get_logger(__name__)


@dataclass
class AttemptRecord:
    attempt: int
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    response_text: str | None
    parsed_ok: bool
    error_type: str | None
    error_message: str | None
    fault_injection: str | None
    request_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    stage: str
    ok: bool
    output: BaseModel | None
    data: dict[str, Any] | None
    attempts: list[AttemptRecord]
    error: str | None = None
    latency_ms: int = 0


def run_stage(provider: AIProvider, request: AIRequest, *, max_attempts: int, faults: FaultInjector | None = None,
              on_attempt: Callable[[AttemptRecord], None] | None = None, sleep: Callable[[float], None] = time.sleep) -> StageResult:
    attempts: list[AttemptRecord] = []
    started = time.perf_counter()
    correction: str | None = None
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        req = replace(request, attempt=attempt, correction=correction)
        meta = {"stage": req.stage, "schema": req.schema_name, "system_chars": len(req.system), "user_chars": len(req.user),
                "user_preview": redact(req.user[-1200:]).text, "correction": correction}
        try:
            resp: AIResponse = provider.generate(req)
        except AIProviderError as exc:
            rec = AttemptRecord(attempt, provider.name, provider.model, 0, None, None, None, False,
                                exc.kind, exc.message, faults.profile if faults else None, meta)
            attempts.append(rec)
            if on_attempt:
                on_attempt(rec)
            last_error = f"{exc.kind}: {exc.message}"
            log.warning("GenAI attempt failed", extra={"stage": req.stage, "attempt": attempt, "provider": provider.name})
            if not exc.retryable or attempt == max_attempts:
                break
            # rate limits and network drop-outs (e.g. a DNS blip) need a few seconds to clear
            sleep(min(8.0, (2.0 if exc.kind in ("rate_limited", "connection") else 0.5) * (2 ** (attempt - 1))))
            continue
        text = resp.text
        if faults:
            text = faults.mutate_raw(req.stage, text, attempt)
        model, data, errors = validate_output(text, req.schema_name)
        if faults and data is not None and not errors:
            mutated = faults.mutate_data(req.stage, data, attempt)
            if mutated is not data:
                model, data, errors = validate_output(json.dumps(mutated), req.schema_name)
        rec = AttemptRecord(attempt, resp.provider, resp.model, resp.latency_ms, resp.input_tokens,
                            resp.output_tokens, text[:20000], not errors,
                            None if not errors else "invalid_output", "; ".join(errors[:6]) if errors else None,
                            faults.profile if faults else None, {**meta, "stop_reason": resp.stop_reason,
                                                                 "request_id": resp.request_id, "served_by": resp.served_by})
        attempts.append(rec)
        if on_attempt:
            on_attempt(rec)
        if not errors and model is not None:
            return StageResult(req.stage, True, model, data, attempts,
                               latency_ms=int((time.perf_counter() - started) * 1000))
        last_error = "invalid_output: " + "; ".join(errors[:4])
        correction = ("Your previous response failed validation: " + "; ".join(errors[:6]) +
                      ". Return only one JSON object that matches the schema exactly.")
        if attempt < max_attempts:
            sleep(0.25 * attempt)
    return StageResult(request.stage, False, None, None, attempts, error=last_error,
                       latency_ms=int((time.perf_counter() - started) * 1000))
