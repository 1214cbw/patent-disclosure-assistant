from patent_agent.core.models import ClaimFeature, GroundedClaimSet, PatentClaimV2, ReviewStatus


class ClaimFeatureEditor:
    def edit(self, claims: GroundedClaimSet, *, claim_number: int, action: str, feature_id: str, supported_pool: dict[str, ClaimFeature], text: str | None = None, target_claim: int | None = None) -> GroundedClaimSet:
        items = [item.model_copy(deep=True) for item in claims.claims]; claim = next(item for item in items if item.claim_number == claim_number)
        feature = next((item for item in claim.features if item.feature_id == feature_id), None); action = action.upper()
        if action == "ADD":
            feature = supported_pool.get(feature_id)
            if feature is None: raise ValueError("CLAIM_FEATURE_UNSUPPORTED")
            claim.features.append(feature.model_copy(update={"human_modified": True, "review_status": ReviewStatus.LOCKED, "locked": True}))
        elif action == "REMOVE":
            if feature is None: raise KeyError(feature_id)
            claim.features = [item for item in claim.features if item.feature_id != feature_id]
        elif action == "EDIT":
            if feature is None: raise KeyError(feature_id)
            allowed = supported_pool.get(feature_id)
            if allowed is None or text != allowed.text: raise ValueError("CLAIM_FEATURE_UNSUPPORTED")
            claim.features = [item.model_copy(update={"text": text, "human_modified": True, "review_status": ReviewStatus.LOCKED, "locked": True}) if item.feature_id == feature_id else item for item in claim.features]
        elif action in {"MOVE", "PROMOTE"}:
            if feature is None or target_claim is None: raise ValueError("MOVE requires existing feature and target_claim")
            target = next(item for item in items if item.claim_number == target_claim)
            if action == "PROMOTE" and (target.parent_claims or target.claim_type not in {"method", "system"}): raise ValueError("PROMOTE_TARGET_MUST_BE_INDEPENDENT")
            claim.features = [item for item in claim.features if item.feature_id != feature_id]
            target.features.append(feature.model_copy(update={"mandatory": action == "PROMOTE", "human_modified": True, "review_status": ReviewStatus.LOCKED, "locked": True}))
            target.rendered_text = _render(target); target.human_modified = True
        else: raise ValueError(f"Unsupported claim edit: {action}")
        claim.rendered_text = _render(claim); claim.human_modified = True; claim.review_status = ReviewStatus.EDITED
        if not claim.parent_claims and claim.claim_type in {"method", "system"} and any(item.mandatory and item.support_status == "UNSUPPORTED" for item in claim.features): raise ValueError("UNSUPPORTED_INDEPENDENT_CLAIM_FEATURE")
        return claims.model_copy(update={"claims": items})

    def manual_text_edit(self, claims: GroundedClaimSet, claim_number: int, text: str) -> GroundedClaimSet:
        return claims.model_copy(update={"claims": [item.model_copy(update={"rendered_text": text, "human_modified": True, "structured_mapping_stale": True, "review_status": ReviewStatus.NEEDS_REVIEW}) if item.claim_number == claim_number else item for item in claims.claims]})


def _render(claim: PatentClaimV2) -> str:
    if claim.parent_claims:
        subject = "系统" if claim.claim_type == "system" else "方法"; lead = f"根据权利要求{claim.parent_claims[0]}所述的{subject}"
    else: lead = "一种电机状态监测与自适应控制系统" if claim.claim_type == "system" else "一种电机状态监测与自适应控制方法"
    return lead + "，其特征在于，包括：" + "；".join(item.text.rstrip("。；") for item in claim.features) + "。"
