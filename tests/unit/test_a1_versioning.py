import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from patent_agent.core.models import EquationKnowledge, EvidenceStatus
from scripts.migrate_machine_human_fields import migrate


def test_machine_cannot_populate_human_formula():
    with pytest.raises(ValidationError, match="HUMAN_FORMULA_REQUIRES_HUMAN_MODIFICATION"):
        EquationKnowledge(
            equation_id="EQ-1",
            original_expression="x+y",
            normalized_latex="x+y",
            status=EvidenceStatus.SOURCE_FACT,
            human_formula="x+y",
            human_modified=False,
        )


def test_human_formula_migration_is_narrow_and_idempotent(tmp_path: Path):
    path = tmp_path / "result.json"
    payload = {
        "equations": [
            {"human_formula": "x+y", "human_modified": False, "original_expression": "x+y"},
            {"human_formula": "x + y", "human_modified": True, "original_expression": "x+y"},
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert migrate(path) == 1
    assert migrate(path) == 0
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["equations"][0]["human_formula"] is None
    assert result["equations"][0]["original_expression"] == "x+y"
    assert result["equations"][1]["human_formula"] == "x + y"
