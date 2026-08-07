from patent_agent.core.models import GroundedInventionCandidate, ReviewStatus


class CandidateReviewEngine:
    def merge(self, candidates: list[GroundedInventionCandidate], candidate_ids: list[str], new_id: str) -> GroundedInventionCandidate:
        selected = [item for item in candidates if item.candidate_id in candidate_ids]
        if len(selected) < 2: raise ValueError("MERGE_REQUIRES_TWO_CANDIDATES")
        base = selected[0]
        return base.model_copy(update={"candidate_id": new_id, "title": " / ".join(dict.fromkeys(item.title for item in selected)), "mandatory_features": _unique([feature for item in selected for feature in item.mandatory_features]), "optional_features": _unique([feature for item in selected for feature in item.optional_features]), "evidence_ids": sorted({identifier for item in selected for identifier in item.evidence_ids}), "merged_from": candidate_ids, "review_status": ReviewStatus.LOCKED, "human_modified": True, "locked": True})

    def split(self, candidate: GroundedInventionCandidate, parts: list[dict]) -> list[GroundedInventionCandidate]:
        if len(parts) < 2: raise ValueError("SPLIT_REQUIRES_TWO_PARTS")
        output = []
        for index, part in enumerate(parts, 1):
            allowed = {item.text: item for item in candidate.mandatory_features + candidate.optional_features}
            features = [allowed[text] for text in part["feature_texts"] if text in allowed]
            output.append(candidate.model_copy(update={"candidate_id": part.get("candidate_id", f"{candidate.candidate_id}-S{index}"), "title": part["title"], "mandatory_features": features, "optional_features": [], "split_from": candidate.candidate_id, "review_status": ReviewStatus.LOCKED, "human_modified": True, "locked": True}))
        return output


def _unique(items):
    result = []
    for item in items:
        if not any(existing.text == item.text for existing in result): result.append(item)
    return result
