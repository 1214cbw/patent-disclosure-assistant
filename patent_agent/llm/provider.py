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


class NormalizedLLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0


def normalize_llm_usage(raw: dict[str, Any] | None) -> dict[str, int]:
    """Normalize OpenAI/DeepSeek token usage so agents never parse provider payloads."""
    raw = raw or {}
    prompt_details = raw.get("prompt_tokens_details") if isinstance(raw.get("prompt_tokens_details"), dict) else {}
    completion_details = raw.get("completion_tokens_details") if isinstance(raw.get("completion_tokens_details"), dict) else {}

    def number(*values: Any) -> int:
        return next((int(item) for item in values if isinstance(item, (int, float)) and not isinstance(item, bool)), 0)

    input_tokens = number(raw.get("input_tokens"), raw.get("prompt_tokens"))
    output_tokens = number(raw.get("output_tokens"), raw.get("completion_tokens"))
    normalized = NormalizedLLMUsage(**{
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": number(raw.get("total_tokens"), input_tokens + output_tokens),
        "cache_hit_tokens": number(raw.get("cache_hit_tokens"), raw.get("prompt_cache_hit_tokens"), prompt_details.get("cached_tokens")),
        "cache_miss_tokens": number(raw.get("cache_miss_tokens"), raw.get("prompt_cache_miss_tokens")),
        "reasoning_tokens": number(raw.get("reasoning_tokens"), completion_details.get("reasoning_tokens")),
    })
    return normalized.model_dump()


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
