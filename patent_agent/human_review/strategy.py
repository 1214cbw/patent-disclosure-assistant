from patent_agent.core.models import GroundedProtectionStrategy, GroundedStatement, ReviewStatus, TechnicalUnderstandingResult


class ProtectionStrategyReviewer:
    def select_scope(self, strategy: GroundedProtectionStrategy, mode: str) -> GroundedProtectionStrategy:
        mode = mode.title()
        if mode not in {"Broad", "Balanced", "Conservative"}: raise ValueError("Scope must be Broad, Balanced, or Conservative")
        core = list(strategy.independent_claim_core); dependent = list(strategy.dependent_claim_features)
        if mode == "Broad": selected = core[:max(1, min(2, len(core)))]
        elif mode == "Balanced": selected = core
        else: selected = core + dependent[:2]
        return strategy.model_copy(update={"independent_claim_core": selected, "scope_strategy": mode, "review_status": ReviewStatus.LOCKED, "human_modified": True, "locked": True})

    def promote_to_mandatory(self, strategy: GroundedProtectionStrategy, statement: GroundedStatement, understanding: TechnicalUnderstandingResult, evidence_store) -> GroundedProtectionStrategy:
        valid = statement.evidence_ids and all(evidence_store.contains(identifier) for identifier in statement.evidence_ids)
        fact_supported = any(set(fact.evidence_ids) & set(statement.evidence_ids) for fact in understanding.facts)
        if not valid or not fact_supported: raise ValueError("UNSUPPORTED_INDEPENDENT_CLAIM_FEATURE")
        core = list(strategy.independent_claim_core)
        if not any(item.text == statement.text for item in core): core.append(statement)
        dependent = [item for item in strategy.dependent_claim_features if item.text != statement.text]
        return strategy.model_copy(update={"independent_claim_core": core, "dependent_claim_features": dependent, "review_status": ReviewStatus.EDITED, "human_modified": True})
