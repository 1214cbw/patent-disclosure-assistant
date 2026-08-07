from __future__ import annotations

import json
import urllib.request

from patent_agent.core.config import Settings
from patent_agent.core.exceptions import PatentAgentError
from .provider import LLMProvider, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, system: str, user: str) -> LLMResponse:
        if not self.settings.allow_external_llm:
            raise PatentAgentError("External LLM calls are disabled. Set PATENT_AGENT_ALLOW_EXTERNAL_LLM=true only after confidentiality review.")
        if not all((self.settings.llm_base_url, self.settings.llm_api_key, self.settings.llm_model)):
            raise PatentAgentError("LLM configuration is incomplete")
        payload = json.dumps({"model": self.settings.llm_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0}).encode("utf-8")
        request = urllib.request.Request(self.settings.llm_base_url.rstrip("/") + "/chat/completions", data=payload, headers={"Authorization": "Bearer " + self.settings.llm_api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
        return LLMResponse(text=data["choices"][0]["message"]["content"], model=data.get("model", self.settings.llm_model), usage=data.get("usage", {}))

