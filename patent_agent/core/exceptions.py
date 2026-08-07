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


class LLMDisabled(PatentAgentError):
    code = "LLM_DISABLED"


class LLMConnectionFailed(PatentAgentError):
    code = "LLM_CONNECTION_FAILED"


class LLMSchemaValidationFailed(PatentAgentError):
    code = "LLM_SCHEMA_VALIDATION_FAILED"


class InvalidEvidenceReference(PatentAgentError):
    code = "INVALID_EVIDENCE_REFERENCE"


class EvidenceMismatch(PatentAgentError):
    code = "EVIDENCE_MISMATCH"


class SourceFactWithoutEvidence(PatentAgentError):
    code = "SOURCE_FACT_WITHOUT_EVIDENCE"


class ClaimFeatureUnsupported(PatentAgentError):
    code = "CLAIM_FEATURE_UNSUPPORTED"


class TraceabilityBroken(PatentAgentError):
    code = "TRACEABILITY_BROKEN"


class InventorConfirmationRequired(PatentAgentError):
    code = "INVENTOR_CONFIRMATION_REQUIRED"
