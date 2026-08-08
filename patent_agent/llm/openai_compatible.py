from __future__ import annotations

import json
import urllib.error
import urllib.request

from pydantic import BaseModel

from patent_agent.core.config import Settings
from patent_agent.core.exceptions import LLMConnectionFailed, LLMDisabled
from .provider import LLMProvider, LLMResponse, normalize_llm_usage
from .structured_output import validate_structured_output


class OpenAICompatibleProvider(LLMProvider):
    provider_name = "openai-compatible"

    def __init__(self, settings: Settings, model: str | None = None):
        self.settings = settings
        self.model = model or settings.default_model
        self.last_usage: dict[str, int] = {}

    def set_model(self, model: str):
        """Dynamically change the model for subsequent calls."""
        from patent_agent.llm.model_registry import validate_model
        self.model = validate_model(model)

    def generate_text(self, *, system_prompt: str, user_prompt: str, context: dict | None = None) -> LLMResponse:
        return self._generate_text(system_prompt=system_prompt, user_prompt=user_prompt, context=context, json_mode=False)

    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[BaseModel], context: dict | None = None) -> BaseModel:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        response = self._generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt + "\nReturn strict JSON matching this schema:\n" + schema,
            context=context,
            json_mode=True,
        )
        return validate_structured_output(response.text, response_model)

    def _generate_text(self, *, system_prompt: str, user_prompt: str, context: dict | None, json_mode: bool) -> LLMResponse:
        if self.settings.patent_llm_mode == "disabled":
            raise LLMDisabled("LLM_DISABLED: PATENT_LLM_MODE is disabled")
        required = bool(self.settings.llm_base_url and self.settings.llm_model)
        if self.settings.patent_llm_mode == "external-approved":
            required = required and bool(self.settings.llm_api_key)
        if not required:
            raise LLMConnectionFailed("LLM_CONNECTION_FAILED: provider configuration is incomplete")
        context_text = json.dumps(context or {}, ensure_ascii=False, separators=(",", ":"))
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt + "\nCONTEXT_JSON:\n" + context_text},
            ],
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self.settings.llm_base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = "Bearer " + self.settings.llm_api_key
        request = urllib.request.Request(endpoint, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LLMConnectionFailed(f"LLM_CONNECTION_FAILED: {type(exc).__name__}: {exc}") from exc
        choices = data.get("choices") or []
        if not choices:
            raise LLMConnectionFailed("LLM_EMPTY_OUTPUT: provider returned no choices")
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise LLMConnectionFailed("LLM_TRUNCATED_OUTPUT: provider stopped at token limit")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMConnectionFailed("LLM_EMPTY_OUTPUT: provider returned empty content")
        self.last_usage = normalize_llm_usage(data.get("usage"))
        return LLMResponse(text=content, model=data.get("model", self.settings.llm_model), usage=self.last_usage, raw_metadata={"request_id": data.get("id", ""), "finish_reason": finish_reason or ""})

    def health_check(self) -> dict:
        configured = bool(self.settings.llm_base_url and self.model and (self.settings.llm_api_key or self.settings.patent_llm_mode == "local"))
        return {"provider": self.provider_name, "model": self.model, "mode": self.settings.patent_llm_mode, "configured": configured, "connection": "not-tested"}
