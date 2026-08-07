from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    model: str
    usage: dict = {}


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> LLMResponse:
        raise NotImplementedError

    def structured(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        import json
        response = self.complete(system, user + "\nReturn JSON matching this schema:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False))
        return schema.model_validate_json(response.text)

