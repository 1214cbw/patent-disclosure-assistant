from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from patent_agent.core.config import Settings
from patent_agent.core.exceptions import LLMDisabled, LLMSchemaValidationFailed
from patent_agent.llm import MockLLMProvider, OpenAICompatibleProvider, StructuredLLMService, normalize_llm_usage
from patent_agent.llm.structured_output import validate_structured_output


class StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def test_mock_structured_contract_and_cache(tmp_path: Path):
    provider = MockLLMProvider(responses={"StrictResult": {"value": "grounded"}})
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", template_root=tmp_path / "templates", output_root=tmp_path / "output")
    service = StructuredLLMService(provider, settings, tmp_path / "case")
    kwargs = dict(stage="test", system_prompt="safe", user_prompt="analyze", response_model=StrictResult, context={"evidence": ["EV-1"]}, prompt_version="test_v2.0")
    assert service.generate(**kwargs).value == "grounded"
    assert service.generate(**kwargs).value == "grounded"
    assert len(provider.calls) == 1
    assert "CACHE_HIT" in (tmp_path / "case" / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8")


def test_schema_parser_rejects_extra_or_non_json():
    with pytest.raises(LLMSchemaValidationFailed):
        validate_structured_output('{"value":"x","extra":1}', StrictResult)
    with pytest.raises(LLMSchemaValidationFailed):
        validate_structured_output("not json", StrictResult)


def test_disabled_openai_provider_never_calls_network(tmp_path: Path):
    settings = replace(Settings.load(tmp_path), patent_llm_mode="disabled")
    with pytest.raises(LLMDisabled):
        OpenAICompatibleProvider(settings).generate_text(system_prompt="x", user_prompt="y")


def test_deepseek_nested_usage_is_normalized():
    usage = normalize_llm_usage({
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
        "prompt_cache_hit_tokens": 75,
        "prompt_cache_miss_tokens": 25,
        "prompt_tokens_details": {"cached_tokens": 75},
        "completion_tokens_details": {"reasoning_tokens": 12},
    })
    assert usage == {
        "input_tokens": 100,
        "output_tokens": 40,
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
        "cache_hit_tokens": 75,
        "cache_miss_tokens": 25,
        "reasoning_tokens": 12,
    }


def test_project_env_load_and_process_override(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text("LLM_MODEL=from-file\nPATENT_LLM_MODE=local\nLLM_BASE_URL=http://127.0.0.1:9000\n", encoding="utf-8")
    assert Settings.load(tmp_path).llm_model == "from-file"
    monkeypatch.setenv("LLM_MODEL", "from-test")
    assert Settings.load(tmp_path).llm_model == "from-test"
