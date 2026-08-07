import os

import pytest

from patent_agent.core.config import Settings
from patent_agent.llm import OpenAICompatibleProvider


@pytest.mark.skipif(os.getenv("RUN_LLM_SMOKE_TESTS") != "1", reason="paid/external LLM smoke tests require explicit opt-in")
def test_real_llm_configuration_is_explicit():
    settings = Settings.load()
    assert settings.patent_llm_mode in {"external-approved", "local"}
    status = OpenAICompatibleProvider(settings).health_check()
    assert status["configured"] is True
