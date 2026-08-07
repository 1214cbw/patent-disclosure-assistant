# V2 Pipeline Report

Synthetic demo: YES

| Stage | Status | Duration (s) | Output |
|---|---:|---:|---|
| v2_stage_1_ingestion | PASS | 0.0317 | {"files": 1, "source_chunks": 12, "evidence_chunks": 12, "images": 0} |
| v2_stage_2_grounded_understanding | PASS | 0.07 | {"facts": 22, "equations": 4, "uncertainties": 3} |
| v2_stage_3_grounded_invention_mining | PASS | 0.0374 | {"candidates": 3, "selected": "INV-001"} |
| checkpoint_A_v2 | PASS | 0.0456 | {"decision": "approve", "note": "auto-approved for synthetic demo", "updated_at": "2026-08-07T09:04:34.282164+00:00"} |
| v2_stage_4_manual_prior_art | PASS | 0.0204 | {"references": 2, "prior_art_evidence": 2, "assessments": 8} |
| v2_stage_5_protection_strategy | PASS | 0.0386 | {"independent_core": 4, "dependent_features": 3, "support_gaps": 0} |
| checkpoint_B_v2 | PASS | 0.0459 | {"decision": "approve", "note": "auto-approved for synthetic demo", "updated_at": "2026-08-07T09:04:34.390596+00:00"} |
| v2_stage_6_grounded_disclosure | PASS | 0.0337 | {"sections": 12, "paragraphs": 23} |
| v2_stage_7_claim_features | PASS | 0.0255 | {"claims": 6, "claim_features": 12} |
| checkpoint_C_v2 | PASS | 0.0409 | {"decision": "approve", "note": "auto-approved for synthetic demo", "updated_at": "2026-08-07T09:04:34.498156+00:00"} |
| v2_stage_8_claim_support | PASS | 0.0077 | {"records": 12, "status": "PASS", "unsupported_independent": 0} |
| v2_stage_9_figures_traceability | PASS | 0.0904 | {"figures": 2, "traceability_links": 41, "broken": 0} |
| v2_stage_10_grounded_review | PASS | 0.0056 | {"deterministic_findings": 0, "semantic_findings": 0, "errors": 0} |
| v2_stage_11_document_rendering | PASS | 0.197 | {"disclosure": "C:\\Users\\25032\\Desktop\\gongshi\\patent_agent\\output\\v2_demo\\技术交底书_v2_demo.docx", "claims": "C:\\Users\\25032\\Desktop\\gongshi\\patent_agent\\output\\v2_demo\\权利要求草案_v2_demo.docx"} |
| v2_stage_12_validation | PASS | 20.7293 | {"document_pass": true, "omml": 5, "quality_gates": {"Gate 1 Evidence Integrity": "PASS", "Gate 2 Technical Understanding": "PASS", "Gate 3 Invention Candidate": "PASS", "Gate 4 Claim Support": "PASS", "Gate 5 Traceability": "PASS", "Gate 6 Document Validation": "PASS"}} |
