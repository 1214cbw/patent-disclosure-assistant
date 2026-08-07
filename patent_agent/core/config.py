from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    workspace_root: Path
    template_root: Path
    output_root: Path
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_provider: str = "openai-compatible"
    llm_timeout: float = 120.0
    llm_max_retries: int = 1
    patent_llm_mode: str = "disabled"
    llm_cache_enabled: bool = True
    debug_save_llm_payloads: bool = False
    llm_input_price_per_million: float | None = None
    llm_output_price_per_million: float | None = None
    allow_external_llm: bool = False

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        mode = os.getenv("PATENT_LLM_MODE", "disabled").strip().lower()
        if mode not in {"disabled", "external-approved", "local"}:
            raise ValueError("PATENT_LLM_MODE must be disabled, external-approved, or local")
        return cls(
            project_root=root,
            workspace_root=root / "workspace",
            template_root=root / "templates",
            output_root=root / "output",
            llm_base_url=os.getenv("LLM_BASE_URL", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            llm_provider=os.getenv("LLM_PROVIDER", "openai-compatible"),
            llm_timeout=float(os.getenv("LLM_TIMEOUT", "120")),
            llm_max_retries=max(0, int(os.getenv("LLM_MAX_RETRIES", "1"))),
            patent_llm_mode=mode,
            llm_cache_enabled=os.getenv("PATENT_LLM_CACHE", "true").lower() == "true",
            debug_save_llm_payloads=os.getenv("PATENT_DEBUG_SAVE_LLM_PAYLOADS", "false").lower() == "true",
            llm_input_price_per_million=_optional_float("LLM_INPUT_PRICE_PER_MILLION"),
            llm_output_price_per_million=_optional_float("LLM_OUTPUT_PRICE_PER_MILLION"),
            allow_external_llm=mode in {"external-approved", "local"},
        )

    def safe_summary(self) -> dict:
        return {
            "llm_base_url_configured": bool(self.llm_base_url),
            "llm_api_key_configured": bool(self.llm_api_key),
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "patent_llm_mode": self.patent_llm_mode,
            "llm_timeout": self.llm_timeout,
            "llm_max_retries": self.llm_max_retries,
            "llm_cache_enabled": self.llm_cache_enabled,
            "debug_save_llm_payloads": self.debug_save_llm_payloads,
            "allow_external_llm": self.allow_external_llm,
        }


def _optional_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None
