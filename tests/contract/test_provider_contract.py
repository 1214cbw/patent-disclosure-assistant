from patent_agent.llm import NormalizedLLMUsage


def test_normalized_usage_contract_is_flat_numeric():
    schema = NormalizedLLMUsage.model_json_schema()
    assert set(schema["properties"]) == {
        "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens",
        "total_tokens", "cache_hit_tokens", "cache_miss_tokens", "reasoning_tokens",
    }
    assert all(item["type"] == "integer" for item in schema["properties"].values())
