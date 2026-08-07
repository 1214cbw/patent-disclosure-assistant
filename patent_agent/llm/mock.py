from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .provider import LLMProvider, LLMResponse


MockResponder = Callable[[type[BaseModel], dict | None], BaseModel | dict[str, Any]]


class MockLLMProvider(LLMProvider):
    provider_name = "mock"
    model = "mock-grounded-v2"

    def __init__(self, responses: dict[str, Any] | None = None, responder: MockResponder | None = None):
        self.responses = responses or {}
        self.responder = responder
        self.calls: list[dict[str, Any]] = []
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def generate_text(self, *, system_prompt: str, user_prompt: str, context: dict | None = None) -> LLMResponse:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "context": context})
        value = self.responses.get("text", "{}")
        return LLMResponse(text=value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), model=self.model, usage=self.last_usage)

    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[BaseModel], context: dict | None = None) -> BaseModel:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "context": context, "response_model": response_model.__name__})
        value = self.responder(response_model, context) if self.responder else self.responses.get(response_model.__name__)
        if value is None:
            raise KeyError(f"No mock response for {response_model.__name__}")
        return value if isinstance(value, response_model) else response_model.model_validate(value)

    def health_check(self) -> dict:
        return {"provider": self.provider_name, "model": self.model, "configured": True, "connection": "mock"}
