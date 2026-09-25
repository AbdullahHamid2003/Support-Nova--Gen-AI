"""Parse and validate GenAI output (SRS Step 46): JSON extraction, JSON-Schema validation against the
committed schema file (required fields, types, enums), then Pydantic model validation."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from .schemas import MODELS, load_schema

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(text: str) -> tuple[Any | None, str | None]:
    if not text or not text.strip():
        return None, "The response was empty."
    body = text.strip()
    m = _FENCE.match(body)
    if m:
        body = m.group(1)
    try:
        return json.loads(body), None
    except json.JSONDecodeError as exc:
        start, end = body.find("{"), body.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(body[start:end + 1]), None
            except json.JSONDecodeError:
                pass
        return None, f"The response is not valid JSON ({exc.msg} at position {exc.pos})."


def validate_output(text: str, schema_name: str) -> tuple[BaseModel | None, dict[str, Any] | None, list[str]]:
    data, err = extract_json(text)
    if err:
        return None, None, [err]
    if not isinstance(data, dict):
        return None, None, ["The response must be a JSON object."]
    errors: list[str] = []
    validator = Draft202012Validator(load_schema(schema_name))
    for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path))[:25]:
        location = "/".join(str(p) for p in e.path) or "(root)"
        errors.append(f"{location}: {e.message[:200]}")
    if errors:
        return None, data, errors
    try:
        model = MODELS[schema_name].model_validate(data)
    except ValidationError as exc:
        return None, data, [f"{'/'.join(str(p) for p in er['loc'])}: {er['msg']}" for er in exc.errors()[:25]]
    return model, data, []
