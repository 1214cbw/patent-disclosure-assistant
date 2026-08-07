import pytest
from pydantic import ValidationError

from patent_agent.core.models import ClaimFeature, ClaimsSupportMatrix, GroundedDisclosure, GroundedInventionCandidate, GroundedProtectionStrategy, TechnicalUnderstandingResult


@pytest.mark.parametrize("model", [TechnicalUnderstandingResult, GroundedInventionCandidate, GroundedProtectionStrategy, GroundedDisclosure, ClaimFeature, ClaimsSupportMatrix])
def test_v2_contracts_are_strict_and_versioned(model):
    schema = model.model_json_schema()
    assert "schema_version" in schema["properties"]
    assert schema.get("additionalProperties") is False
    with pytest.raises(ValidationError):
        model.model_validate({"unexpected": True})
