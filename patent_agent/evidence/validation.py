from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from patent_agent.core.exceptions import EvidenceMismatch, InvalidEvidenceReference
from patent_agent.core.models import GroundedStatement


def collect_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            if key in {"evidence_ids", "prior_art_evidence_ids", "related_evidence_ids"} and isinstance(item, list):
                found.update(str(identifier) for identifier in item)
            else:
                found.update(collect_evidence_ids(item))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found.update(collect_evidence_ids(item))
        return found
    return set()


def validate_evidence_references(value: Any, store) -> list[str]:
    invalid = sorted(identifier for identifier in collect_evidence_ids(value) if not store.contains(identifier))
    if invalid:
        raise InvalidEvidenceReference("INVALID_EVIDENCE_REFERENCE: " + ", ".join(invalid))
    return invalid


def validate_statement_support(statement: GroundedStatement, store, minimum_overlap: float = 0.05) -> float:
    if not statement.evidence_ids:
        return 0.0
    statement_tokens = _semantic_tokens(statement.text)
    evidence_tokens = set()
    for evidence_id in statement.evidence_ids:
        evidence_tokens.update(_semantic_tokens(store.get(evidence_id).normalized_text))
    if not statement_tokens:
        return 1.0
    overlap = len(statement_tokens & evidence_tokens) / len(statement_tokens)
    if overlap < minimum_overlap:
        raise EvidenceMismatch(f"EVIDENCE_MISMATCH: overlap={overlap:.3f} for {statement.text[:80]}")
    return overlap


def _semantic_tokens(value: str) -> set[str]:
    ascii_words = set(re.findall(r"[a-zA-Z0-9_]{2,}", value.lower()))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    return ascii_words | {chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))}
