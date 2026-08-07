from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from .structured_output import validate_structured_output


class LLMResponse(BaseModel):
    text: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class LLMProvider(ABC):
    """Provider contract. Patent agents consume schemas, never provider payloads."""

    provider_name = "unknown"
    model = ""

    @abstractmethod
    def generate_text(self, *, system_prompt: str, user_prompt: str, context: dict | None = None) -> LLMResponse:
        raise NotImplementedError

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        context: dict | None = None,
    ) -> BaseModel:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        response = self.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt + "\nReturn strict JSON matching this schema:\n" + schema,
            context=context,
        )
        return validate_structured_output(response.text, response_model)

    # V1 compatibility.
    def complete(self, system: str, user: str) -> LLMResponse:
        return self.generate_text(system_prompt=system, user_prompt=user)

    def structured(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        return self.generate_structured(system_prompt=system, user_prompt=user, response_model=schema)

    def health_check(self) -> dict:
        return {"provider": self.provider_name, "model": self.model, "configured": True, "connection": "not-tested"}
