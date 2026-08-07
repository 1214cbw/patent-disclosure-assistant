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
    allow_external_llm: bool = False

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        return cls(
            project_root=root,
            workspace_root=root / "workspace",
            template_root=root / "templates",
            output_root=root / "output",
            llm_base_url=os.getenv("LLM_BASE_URL", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            allow_external_llm=os.getenv("PATENT_AGENT_ALLOW_EXTERNAL_LLM", "false").lower() == "true",
        )

    def safe_summary(self) -> dict:
        return {
            "llm_base_url_configured": bool(self.llm_base_url),
            "llm_api_key_configured": bool(self.llm_api_key),
            "llm_model": self.llm_model,
            "allow_external_llm": self.allow_external_llm,
        }

