from __future__ import annotations

import json
import re
from pydantic import BaseModel, ValidationError

from patent_agent.core.exceptions import LLMSchemaValidationFailed


def validate_structured_output(raw: str, schema: type[BaseModel]) -> BaseModel:
    candidate = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
        return schema.model_validate(payload)
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        raise LLMSchemaValidationFailed(f"LLM_SCHEMA_VALIDATION_FAILED: {exc}") from exc
