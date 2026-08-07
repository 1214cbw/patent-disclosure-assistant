class PatentAgentError(RuntimeError):
    code = "PATENT_AGENT_ERROR"


class CheckpointRequired(PatentAgentError):
    code = "CHECKPOINT_REQUIRED"


class EquationRenderFailed(PatentAgentError):
    code = "EQUATION_RENDER_FAILED"


class SearchUnavailable(PatentAgentError):
    code = "SEARCH_UNAVAILABLE"


class ClaimSupportFailed(PatentAgentError):
    code = "CLAIM_SUPPORT_FAILED"


class ReferenceBroken(PatentAgentError):
    code = "REFERENCE_BROKEN"

