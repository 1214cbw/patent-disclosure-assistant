from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from patent_agent.core.models import StrictSchema

from .models import ArtifactState, ChangeImpact, DependencyLink, HumanCorrection


DEFAULT_STAGE_DEPENDENCIES = {
    "fact": ["knowledge"],
    "knowledge": ["candidate"],
    "candidate": ["strategy"],
    "strategy": ["claim_feature", "disclosure"],
    "claim_feature": ["claim", "support_matrix", "scope_review"],
    "claim": ["support_matrix", "scope_review", "traceability"],
    "disclosure": ["support_matrix", "figure", "traceability"],
    "terminology": ["disclosure", "claim", "figure"],
    "equation": ["disclosure", "traceability"],
}


class DependencySnapshot(StrictSchema):
    links: list[DependencyLink]
    artifact_states: dict[str, ArtifactState]


class DependencyGraph:
    def __init__(self, links: list[DependencyLink] | None = None):
        self.links = links or []
        self.states: dict[str, ArtifactState] = {}

    @classmethod
    def standard(cls) -> "DependencyGraph":
        links = [DependencyLink(source_id=source, target_id=target, relation="invalidates") for source, targets in DEFAULT_STAGE_DEPENDENCIES.items() for target in targets]
        graph = cls(links)
        for node in {item.source_id for item in links} | {item.target_id for item in links}:
            graph.states[node] = ArtifactState.CURRENT
        return graph

    def add(self, source_id: str, target_id: str, relation: str = "derived_from") -> None:
        link = DependencyLink(source_id=source_id, target_id=target_id, relation=relation)
        if link not in self.links:
            self.links.append(link)
        self.states.setdefault(source_id, ArtifactState.CURRENT)
        self.states.setdefault(target_id, ArtifactState.CURRENT)

    def lock(self, object_id: str) -> None:
        self.states[object_id] = ArtifactState.LOCKED

    def unlock(self, object_id: str) -> None:
        self.states[object_id] = ArtifactState.CURRENT

    def invalidate(self, correction: HumanCorrection, changed_ids: list[str]) -> ChangeImpact:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for link in self.links:
            adjacency[link.source_id].append(link.target_id)
        roots = list(changed_ids)
        target_type = _canonical_type(correction.target_type)
        if target_type not in roots:
            roots.append(target_type)
        queue = deque(roots)
        affected: list[str] = []
        seen = set(roots)
        while queue:
            current = queue.popleft()
            for target in adjacency.get(current, []):
                if target in seen:
                    continue
                seen.add(target)
                if self.states.get(target) != ArtifactState.LOCKED:
                    self.states[target] = ArtifactState.STALE
                affected.append(target)
                queue.append(target)
        return ChangeImpact(correction_id=correction.correction_id, changed_ids=changed_ids, affected_ids=affected, stale_artifacts={key: value for key, value in self.states.items() if value == ArtifactState.STALE})

    def mark_current(self, artifact_id: str) -> None:
        if self.states.get(artifact_id) != ArtifactState.LOCKED:
            self.states[artifact_id] = ArtifactState.CURRENT

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DependencySnapshot(links=self.links, artifact_states=self.states).model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "DependencyGraph":
        snapshot = DependencySnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        graph = cls(snapshot.links); graph.states = snapshot.artifact_states
        return graph


def render_change_impact_markdown(impact: ChangeImpact) -> str:
    lines = ["# Change Impact Report", "", f"Correction: `{impact.correction_id}`", "", "## Changed", ""]
    lines += [f"- {item}" for item in impact.changed_ids] or ["- none"]
    lines += ["", "## Potentially affected", ""]
    lines += [f"- {item}: STALE" for item in impact.affected_ids] or ["- none"]
    return "\n".join(lines) + "\n"


def _canonical_type(value: str) -> str:
    lowered = value.lower()
    for token in DEFAULT_STAGE_DEPENDENCIES:
        if token in lowered:
            return token
    return lowered
