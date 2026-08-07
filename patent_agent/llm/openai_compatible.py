from __future__ import annotations

import json
import urllib.error
import urllib.request

from patent_agent.core.config import Settings
from patent_agent.core.exceptions import LLMConnectionFailed, LLMDisabled
from .provider import LLMProvider, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    provider_name = "openai-compatible"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.llm_model
        self.last_usage: dict[str, int] = {}

    def generate_text(self, *, system_prompt: str, user_prompt: str, context: dict | None = None) -> LLMResponse:
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
        self.last_usage = data.get("usage", {})
        return LLMResponse(text=data["choices"][0]["message"]["content"], model=data.get("model", self.settings.llm_model), usage=self.last_usage, raw_metadata={"request_id": data.get("id", "")})

    def health_check(self) -> dict:
        configured = bool(self.settings.llm_base_url and self.model and (self.settings.llm_api_key or self.settings.patent_llm_mode == "local"))
        return {"provider": self.provider_name, "model": self.model, "mode": self.settings.patent_llm_mode, "configured": configured, "connection": "not-tested"}
