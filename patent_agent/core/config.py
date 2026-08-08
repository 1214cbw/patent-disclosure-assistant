from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_project_env(path: Path) -> dict[str, str]:
    """Read exactly one project-local .env without mutating process/global env."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


@dataclass(frozen=True)
class Settings:
    project_root: Path
    workspace_root: Path
    template_root: Path
    output_root: Path
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""  # Legacy model field (backward compat)
    llm_provider: str = "openai-compatible"
    llm_timeout: float = 120.0
    llm_max_retries: int = 1
    patent_llm_mode: str = "disabled"
    llm_cache_enabled: bool = True
    debug_save_llm_payloads: bool = False
    llm_input_price_per_million: float | None = None
    llm_output_price_per_million: float | None = None
    allow_external_llm: bool = False
    app_mode: str = "disclosure_only"
    # V6.5 dual-model fields
    llm_default_model: str = "deepseek-v4-flash"
    llm_allowed_models: str = "deepseek-v4-flash,deepseek-v4-pro"
    cache_schema_version: int = 2

    @property
    def default_model(self) -> str:
        """Resolved default model (V6.5+ dual-model support)."""
        from patent_agent.llm.model_registry import DEFAULT_MODEL, validate_model
        if self.llm_default_model:
            try:
                return validate_model(self.llm_default_model)
            except ValueError:
                pass
        # Legacy fallback
        if self.llm_model:
            try:
                return validate_model(self.llm_model)
            except ValueError:
                pass
        return DEFAULT_MODEL

    @property
    def allowed_models(self) -> list[str]:
        """Parse allowed models list."""
        raw = self.llm_allowed_models or ""
        return [m.strip() for m in raw.split(",") if m.strip()]

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        file_env = _load_project_env(root / ".env")

        def value(name: str, default: str = "") -> str:
            return os.environ.get(name, file_env.get(name, default))

        mode = value("PATENT_LLM_MODE", "disabled").strip().lower()
        if mode not in {"disabled", "external-approved", "local"}:
            raise ValueError("PATENT_LLM_MODE must be disabled, external-approved, or local")
        return cls(
            project_root=root,
            workspace_root=root / "workspace",
            template_root=root / "templates",
            output_root=root / "output",
            llm_base_url=value("LLM_BASE_URL"),
            llm_api_key=value("LLM_API_KEY"),
            llm_model=value("LLM_MODEL"),
            llm_provider=value("LLM_PROVIDER", "openai-compatible"),
            llm_timeout=float(value("LLM_TIMEOUT", "120")),
            llm_max_retries=max(0, int(value("LLM_MAX_RETRIES", "1"))),
            patent_llm_mode=mode,
            llm_cache_enabled=value("PATENT_LLM_CACHE", "true").lower() == "true",
            debug_save_llm_payloads=value("PATENT_DEBUG_SAVE_LLM_PAYLOADS", "false").lower() == "true",
            llm_input_price_per_million=_optional_float_value(value("LLM_INPUT_PRICE_PER_MILLION")),
            llm_output_price_per_million=_optional_float_value(value("LLM_OUTPUT_PRICE_PER_MILLION")),
            allow_external_llm=mode in {"external-approved", "local"},
            app_mode=value("APP_MODE", "disclosure_only").strip().lower(),
            llm_default_model=value("LLM_DEFAULT_MODEL", "deepseek-v4-flash").strip(),
            llm_allowed_models=value("LLM_ALLOWED_MODELS", "deepseek-v4-flash,deepseek-v4-pro").strip(),
            cache_schema_version=int(value("CACHE_SCHEMA_VERSION", "2")),
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
            "app_mode": self.app_mode,
            "default_model": self.default_model,
            "allowed_models": self.allowed_models,
        }

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
            "app_mode": self.app_mode,
        }


def _optional_float_value(raw: str) -> float | None:
    raw = raw.strip()
    return float(raw) if raw else None
