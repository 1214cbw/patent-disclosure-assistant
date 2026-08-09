"""Central construction of production real-case workflows."""
from __future__ import annotations

from patent_agent.core.config import Settings
from patent_agent.real_case import RealCaseManager, effective_llm_mode


def build_real_case_workflow(settings: Settings, case_id: str):
    """Build the workflow used by both CLI and Web production entry points."""
    from patent_agent.llm import OpenAICompatibleProvider
    from patent_agent.workflow.real_case_pipeline import RealCaseWorkflow

    manifest = RealCaseManager(settings.project_root).load(case_id)
    effective = effective_llm_mode(settings.patent_llm_mode, manifest)
    provider = None
    if effective != "disabled":
        provider = OpenAICompatibleProvider(settings, model=manifest.llm_model or None)
    if manifest.current_checkpoint == "B" and not manifest.synthetic and provider is None:
        raise RuntimeError(
            "LLM_PROVIDER_REQUIRED_FOR_CHECKPOINT_B_TO_C: "
            f"global={settings.patent_llm_mode}, case={manifest.llm_mode}, effective={effective}"
        )
    return RealCaseWorkflow(settings, provider)

