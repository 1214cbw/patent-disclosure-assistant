from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from patent_agent.core.config import Settings
from patent_agent.core.exceptions import LLMSchemaValidationFailed
from .provider import LLMProvider


class StructuredLLMService:
    """Finite retry, case-local cache and privacy-safe metadata audit."""

    def __init__(self, provider: LLMProvider, settings: Settings, case_dir: Path):
        self.provider = provider
        self.settings = settings
        self.case_dir = case_dir
        self.cache_dir = case_dir / "llm_cache"
        self.audit_path = case_dir / "logs" / "llm_calls.jsonl"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def generate(self, *, stage: str, system_prompt: str, user_prompt: str, response_model: type[BaseModel], context: dict | None, prompt_version: str, use_cache: bool | None = None) -> BaseModel:
        cache_allowed = self.settings.llm_cache_enabled if use_cache is None else use_cache
        input_hash = _hash_json({"system": system_prompt, "user": user_prompt, "context": context})
        cache_key = _hash_json({
            "provider": self.provider.provider_name,
            "model": self.provider.model,
            "prompt_version": prompt_version,
            "input_hash": input_hash,
            "schema": response_model.model_json_schema(),
            "cache_schema_version": self.settings.cache_schema_version,
        })
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_allowed and cache_path.exists():
            result = response_model.model_validate_json(cache_path.read_text(encoding="utf-8"))
            self._audit(stage, prompt_version, input_hash, _hash_json(result.model_dump()), 0.0, "CACHE_HIT", {}, cache_key)
            return result
        started = time.perf_counter()
        error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                repair = "" if attempt == 0 else "\nPrevious output failed validation. Return JSON only and satisfy every required field."
                result = self.provider.generate_structured(system_prompt=system_prompt, user_prompt=user_prompt + repair, response_model=response_model, context=context)
                cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                usage = getattr(self.provider, "last_usage", {})
                self._audit(stage, prompt_version, input_hash, _hash_json(result.model_dump()), time.perf_counter() - started, "PASS", usage, cache_key)
                if self.settings.debug_save_llm_payloads:
                    debug = self.case_dir / "logs" / "llm_debug"
                    debug.mkdir(parents=True, exist_ok=True)
                    (debug / f"{cache_key}.json").write_text(json.dumps({"system_prompt": system_prompt, "user_prompt": user_prompt, "context": context, "output": result.model_dump()}, ensure_ascii=False, indent=2), encoding="utf-8")
                return result
            except Exception as exc:  # bounded retry, then explicit error
                error = exc
        self._audit(stage, prompt_version, input_hash, "", time.perf_counter() - started, "FAIL", {}, cache_key, str(error))
        if isinstance(error, LLMSchemaValidationFailed):
            raise error
        raise LLMSchemaValidationFailed(f"LLM_SCHEMA_VALIDATION_FAILED after retries: {error}") from error

    def _audit(self, stage: str, prompt_version: str, input_hash: str, output_hash: str, latency: float, status: str, usage: dict, cache_key: str, error: str = "") -> None:
        record = {"stage": stage, "provider": self.provider.provider_name, "model": self.provider.model, "prompt_version": prompt_version, "input_hash": input_hash, "output_hash": output_hash, "token_usage": usage, "estimated_cost": _cost(usage, self.settings), "latency_seconds": round(latency, 4), "status": status, "cache_key": cache_key, "error": error[:500]}
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _hash_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _cost(usage: dict, settings: Settings) -> float | str:
    if settings.llm_input_price_per_million is None or settings.llm_output_price_per_million is None:
        return "unknown"
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
    return round(prompt * settings.llm_input_price_per_million / 1_000_000 + completion * settings.llm_output_price_per_million / 1_000_000, 8)
