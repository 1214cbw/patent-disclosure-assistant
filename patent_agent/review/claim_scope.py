from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from patent_agent.core.models import ClaimTerminologyRegistry, ClaimsSupportMatrix, GroundedClaimSet, GroundedNoveltyMatrix, GroundedProtectionStrategy, PatentClaimV2, StrictSchema


class ClaimScopeAssessment(StrictSchema):
    claim_number: int
    scope_level: Literal["VERY_BROAD", "BROAD", "BALANCED", "NARROW", "VERY_NARROW"]
    mandatory_feature_count: int
    potentially_unnecessary_features: list[str] = Field(default_factory=list)
    potentially_missing_core_features: list[str] = Field(default_factory=list)
    parameter_locking_risks: list[str] = Field(default_factory=list)
    terminology_narrowing_risks: list[str] = Field(default_factory=list)
    enablement_risks: list[str] = Field(default_factory=list)
    novelty_risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    support_scope_risks: list[str] = Field(default_factory=list)
    warning_requires_ack: bool = False


class ClaimScopeVariant(StrictSchema):
    name: Literal["Broad", "Balanced", "Conservative"]
    feature_ids: list[str]
    rendered_text: str
    coverage: str
    support: Literal["PASS", "WARNING", "FAIL"]
    novelty_risk: str
    narrowing_risk: str


class ClaimScopeComparison(StrictSchema):
    claim_number: int
    same_feature_pool: list[str]
    variants: list[ClaimScopeVariant]


class ClaimScopeReview(StrictSchema):
    assessments: list[ClaimScopeAssessment]
    comparisons: list[ClaimScopeComparison]
    deterministic_rule_version: str = "claim_scope_rules_v2.1"


class ClaimScopeEngine:
    IMPLEMENTATION_TERMS = ("CNN", "卷积神经网络", "STM32", "单片机", "PID", "PI控制", "特定型号")
    PARAMETER_PATTERN = re.compile(r"(?:\d+(?:\.\d+)?\s*(?:℃|°C|ms|s|Hz|kHz|MPa|V|A|%|毫米|微米)|阈值.{0,8}\d)", re.IGNORECASE)

    def assess(self, claims: GroundedClaimSet, strategy: GroundedProtectionStrategy, novelty: GroundedNoveltyMatrix, support: ClaimsSupportMatrix, terminology: ClaimTerminologyRegistry) -> ClaimScopeReview:
        assessments, comparisons = [], []
        core_text = {item.text for item in strategy.independent_claim_core}
        support_by_feature = {item.feature_id: item for item in support.records}
        novelty_by_feature: dict[str, list[str]] = {}
        for item in novelty.assessments:
            novelty_by_feature.setdefault(item.feature_id, []).append(item.assessment)
        broad_terms = {term.selected_term for term in terminology.terms} | {term.patent_term for term in terminology.terms if term.patent_term}
        for claim in claims.claims:
            if claim.parent_claims or claim.claim_type not in {"method", "system"}: continue
            feature_texts = {item.text for item in claim.features}
            missing = sorted(core_text - feature_texts)
            unnecessary = [item.feature_id for item in claim.features if not item.mandatory]
            parameter = [item.feature_id for item in claim.features if self.PARAMETER_PATTERN.search(item.text)]
            narrowing = [item.feature_id for item in claim.features if any(term.lower() in item.text.lower() for term in self.IMPLEMENTATION_TERMS) and not any(term and term in item.text for term in broad_terms)]
            support_risks = [f"SUPPORT_SCOPE_RISK:{item.feature_id}" for item in claim.features if support_by_feature.get(item.feature_id) is None or support_by_feature[item.feature_id].support_status == "UNSUPPORTED"]
            enablement = ["ENABLEMENT_RISK: missing core features " + ", ".join(missing)] if missing else []
            disclosed = [item.feature_id for item in claim.features if "EXPLICITLY_DISCLOSED" in novelty_by_feature.get(item.feature_id, [])]
            novelty_risks = ["NOVELTY_RISK: all broad features are explicitly disclosed by imported prior art"] if claim.features and len(disclosed) == len(claim.features) else []
            count, core_count = len(claim.features), max(1, len(core_text))
            if missing and count < core_count: level = "VERY_BROAD"
            elif missing: level = "BROAD"
            elif count == core_count and not unnecessary: level = "BALANCED"
            elif count <= core_count + 1: level = "NARROW"
            else: level = "VERY_NARROW"
            recommendations = []
            if missing: recommendations.append("Restore missing core features before approval.")
            if parameter: recommendations.append("Move non-essential numeric limits to dependent claims or embodiments.")
            if narrowing: recommendations.append("Replace specific implementation terms with confirmed functional terminology.")
            if novelty_risks: recommendations.append("Use the balanced differentiating feature set or revise the inventive concept.")
            warning = level == "VERY_NARROW" or (level == "VERY_BROAD" and bool(enablement))
            assessments.append(ClaimScopeAssessment(claim_number=claim.claim_number, scope_level=level, mandatory_feature_count=sum(item.mandatory for item in claim.features), potentially_unnecessary_features=unnecessary, potentially_missing_core_features=missing, parameter_locking_risks=[f"PARAMETER_LOCKING_RISK:{item}" for item in parameter], terminology_narrowing_risks=[f"IMPLEMENTATION_NARROWING:{item}" for item in narrowing], enablement_risks=enablement, novelty_risks=novelty_risks, recommendations=recommendations, support_scope_risks=support_risks, warning_requires_ack=warning))
            comparisons.append(self.compare(claim, support_by_feature, novelty_by_feature))
        return ClaimScopeReview(assessments=assessments, comparisons=comparisons)

    def compare(self, claim: PatentClaimV2, support_by_feature: dict, novelty_by_feature: dict) -> ClaimScopeComparison:
        pool = list(claim.features); mandatory = [item for item in pool if item.mandatory]; optional = [item for item in pool if not item.mandatory]
        broad = mandatory[:max(1, min(2, len(mandatory)))]; balanced = mandatory or pool[:1]; conservative = mandatory + optional or pool
        variants = []
        for name, features in (("Broad", broad), ("Balanced", balanced), ("Conservative", conservative)):
            support = "PASS" if features and all(support_by_feature.get(item.feature_id) and support_by_feature[item.feature_id].support_status == "SUPPORTED" for item in features) else "FAIL"
            disclosed = [item for item in features if "EXPLICITLY_DISCLOSED" in novelty_by_feature.get(item.feature_id, [])]
            variants.append(ClaimScopeVariant(name=name, feature_ids=[item.feature_id for item in features], rendered_text=_render_variant(claim, features), coverage={"Broad": "maximum", "Balanced": "recommended", "Conservative": "limited"}[name], support=support, novelty_risk="HIGH" if features and len(disclosed) == len(features) else "REVIEW", narrowing_risk="HIGH" if any(self.PARAMETER_PATTERN.search(item.text) for item in features) else "LOW"))
        return ClaimScopeComparison(claim_number=claim.claim_number, same_feature_pool=[item.feature_id for item in pool], variants=variants)


def _render_variant(claim: PatentClaimV2, features: list) -> str:
    subject = "一种技术系统" if claim.claim_type == "system" else "一种技术方法"
    return subject + "，其特征在于，包括：" + "；".join(item.text.rstrip("。；") for item in features) + "。"


def render_scope_comparison(review: ClaimScopeReview) -> str:
    lines = ["# Claim Scope Comparison", "", "All variants are rendered from the same supported feature graph.", ""]
    for comparison in review.comparisons:
        lines += [f"## Claim {comparison.claim_number}", "", f"Feature pool: {', '.join(comparison.same_feature_pool)}", ""]
        for item in comparison.variants:
            lines += [f"### {item.name}", "", f"- Features: {', '.join(item.feature_ids)}", f"- Coverage: {item.coverage}", f"- Support: {item.support}", f"- Novelty risk: {item.novelty_risk}", f"- Narrowing risk: {item.narrowing_risk}", "", item.rendered_text, ""]
    return "\n".join(lines)


def render_scope_review(review: ClaimScopeReview) -> str:
    lines = ["# Claim Scope Review", ""]
    for item in review.assessments:
        lines += [f"## Claim {item.claim_number}", "", f"- Scope: **{item.scope_level}**", f"- Mandatory features: {item.mandatory_feature_count}", f"- Missing core: {', '.join(item.potentially_missing_core_features) or 'none'}", f"- Parameter locking: {', '.join(item.parameter_locking_risks) or 'none'}", f"- Terminology narrowing: {', '.join(item.terminology_narrowing_risks) or 'none'}", f"- Enablement: {', '.join(item.enablement_risks) or 'none'}", f"- Support scope: {', '.join(item.support_scope_risks) or 'none'}", f"- Novelty: {', '.join(item.novelty_risks) or 'none'}", f"- Warning requires acknowledgement: {item.warning_requires_ack}", ""]
    return "\n".join(lines)
