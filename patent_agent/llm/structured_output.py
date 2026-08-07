from __future__ import annotations

import json
from pydantic import BaseModel, ValidationError


def validate_structured_output(raw: str, schema: type[BaseModel]) -> BaseModel:
    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"STRUCTURED_OUTPUT_INVALID: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"STRUCTURED_OUTPUT_NOT_JSON: {exc}") from exc

