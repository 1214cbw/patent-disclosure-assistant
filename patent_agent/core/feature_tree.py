"""Technical Feature Tree for disclosure generation planning.

Ensures complete coverage of source material in the disclosure by
building a structured tree of technical features, each linked to
evidence and facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeatureNode:
    """A node in the technical feature tree."""
    id: str
    label_cn: str  # Chinese label
    label_en: str = ""  # Original English label if applicable
    category: str = "method"  # method | data | architecture | effect | parameter
    evidence_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    description: str = ""  # Brief description
    detail_required: bool = True  # Whether this needs detailed expansion
    children: list[FeatureNode] = field(default_factory=list)
    parent_id: str | None = None
    coverage_status: str = "pending"  # pending | covered | needs_review


@dataclass
class TechnicalFeatureTree:
    """Complete technical feature tree for a disclosure."""
    root: FeatureNode
    total_nodes: int = 0
    covered_nodes: int = 0
    missing_evidence_nodes: list[str] = field(default_factory=list)
    build_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": _feature_node_to_dict(self.root),
            "total_nodes": self.total_nodes,
            "covered_nodes": self.covered_nodes,
            "missing_evidence_nodes": self.missing_evidence_nodes,
        }

    def get_all_nodes(self) -> list[FeatureNode]:
        """Flatten the tree into a list."""
        result = []

        def _collect(node: FeatureNode):
            result.append(node)
            for child in node.children:
                _collect(child)

        _collect(self.root)
        self.total_nodes = len(result)
        return result

    def coverage_ratio(self) -> float:
        """Ratio of covered nodes to total."""
        if self.total_nodes == 0:
            return 0.0
        return self.covered_nodes / self.total_nodes

    def nodes_by_category(self) -> dict[str, list[FeatureNode]]:
        """Group nodes by category."""
        groups: dict[str, list[FeatureNode]] = {}
        for node in self.get_all_nodes():
            groups.setdefault(node.category, []).append(node)
        return groups


def _feature_node_to_dict(node: FeatureNode) -> dict:
    """Convert a FeatureNode to a plain dict for JSON serialization."""
    return {
        "id": node.id,
        "label_cn": node.label_cn,
        "label_en": node.label_en,
        "category": node.category,
        "evidence_ids": node.evidence_ids,
        "fact_ids": node.fact_ids,
        "description": node.description,
        "detail_required": node.detail_required,
        "children": [_feature_node_to_dict(c) for c in node.children],
        "coverage_status": node.coverage_status,
    }


def build_feature_tree_from_understanding(
    understanding,  # TechnicalUnderstandingResult
    evidence_store,  # EvidenceStore
) -> TechnicalFeatureTree:
    """Build a technical feature tree from existing understanding and evidence.

    This is a deterministic builder that structures the technical facts
    into a hierarchical tree suitable for disclosure planning.
    """
    from datetime import datetime, timezone

    facts = understanding.facts
    steps = understanding.steps
    components = understanding.components

    # Helper to safely extract string from any object
    def _to_str(obj):
        if isinstance(obj, str):
            return obj
        if hasattr(obj, 'text'):
            val = obj.text
            return val if isinstance(val, str) else str(val)
        if hasattr(obj, 'description'):
            val = obj.description
            return val if isinstance(val, str) else str(val)
        if hasattr(obj, 'name'):
            val = obj.name
            return val if isinstance(val, str) else str(val)
        if hasattr(obj, 'statement'):
            val = obj.statement
            return val if isinstance(val, str) else str(val)
        return str(obj)

    # V7: no domain hardcoding. The feature tree is always built from the
    # case's OWN facts (the old motor/LDM-specific tree with hardcoded
    # diffusion/U-Net/interpolation content was removed - it contaminated
    # non-LDM motor cases such as REAL-PAPER-002).
    tree = _build_generic_tree(facts, steps, components, evidence_store)

    tree.build_timestamp = datetime.now(timezone.utc).isoformat()
    tree.get_all_nodes()  # Update total_nodes count
    return tree


def _build_generic_tree(facts, steps, components, evidence_store) -> TechnicalFeatureTree:
    """Build a generic feature tree from any set of facts."""
    root = FeatureNode(id="ROOT", label_cn="技术方案总体", category="method")

    for i, fact in enumerate(facts, 1):
        cat = getattr(fact, "category", "method")
        stmt = getattr(fact, "statement", "")
        eids = getattr(fact, "evidence_ids", []) or []
        node = FeatureNode(
            id=f"F{i:02d}",
            label_cn=stmt[:60] if stmt else f"特征{i}",
            category=cat,
            evidence_ids=eids,
            fact_ids=[getattr(fact, "fact_id", "")],
            parent_id="ROOT",
        )
        root.children.append(node)

    return TechnicalFeatureTree(root=root)
