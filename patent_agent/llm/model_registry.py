"""DeepSeek Model Registry for Patent Agent dual-model support.

Defines allowed models, display names, and validation.
Single source of truth for model identifiers.
"""
from __future__ import annotations

from dataclasses import dataclass

ALLOWED_MODEL_IDS = {"deepseek-v4-flash", "deepseek-v4-pro"}


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    display_name: str
    recommended: bool = False


MODEL_REGISTRY: dict[str, ModelInfo] = {
    "deepseek-v4-flash": ModelInfo(
        model_id="deepseek-v4-flash",
        display_name="DeepSeek V4-Flash（推荐）",
        recommended=True,
    ),
    "deepseek-v4-pro": ModelInfo(
        model_id="deepseek-v4-pro",
        display_name="DeepSeek V4-Pro",
        recommended=False,
    ),
}

DEFAULT_MODEL = "deepseek-v4-flash"


def get_model_info(model_id: str) -> ModelInfo | None:
    """Get display info for a model ID."""
    return MODEL_REGISTRY.get(model_id)


def validate_model(model_id: str) -> str:
    """Validate and normalize a model ID. Raises ValueError if invalid."""
    mid = model_id.strip().lower()
    if mid not in ALLOWED_MODEL_IDS:
        raise ValueError(
            f"不支持的模型：{model_id}。允许的模型：{', '.join(sorted(ALLOWED_MODEL_IDS))}"
        )
    return mid


def allowed_models_display() -> list[dict]:
    """Return list of allowed models for UI display."""
    return [
        {
            "model_id": info.model_id,
            "display_name": info.display_name,
            "recommended": info.recommended,
        }
        for info in MODEL_REGISTRY.values()
    ]


def resolve_model(project_model: str | None, default_model: str) -> str:
    """Resolve effective model: project setting > system default."""
    if project_model:
        return validate_model(project_model)
    return validate_model(default_model)
