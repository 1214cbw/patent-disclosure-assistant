# Patent Agent 项目状态

## Current Version

**V7.2 PATENT SEMANTICS & EMBODIMENT ARCHITECTURE HARDENING**

- Starting baseline: `39cbc479e4c5df9b4570ba123d3e1c714aaac5c9`
- Product scope: evidence-grounded paper/report → Chinese patent technical disclosure
- Delivery state model: `CONTENT_VALIDATED → PATENT_SEMANTICS_VALIDATED → DOCX_VALIDATED → RENDER_VALIDATED → DELIVERY_READY → DONE`
- Standard production entry: CLI/Web share provider-aware workflow construction

## V7.2 Completed Capabilities

- Typed `InventionCoreGraph` separates facts, features, modules, steps, parameters, experiments, validations, limitations, and embodiments
- Evidence-driven `EmbodimentPlanner` creates complete implementations rather than mapping fact clusters directly to embodiments
- Primary embodiment coverage, step continuity, input/output continuity, final-result, and distinctness hard gates
- Case-local scenario and technical-role registries; comparison baselines and validation-only concepts are isolated from invention components
- Paragraph-local exact-parameter, unsupported-generalization, scenario-drift, and open-vocabulary entailment checks
- Section 5/7 semantic-role separation and mechanical-mirroring audit
- Required-claim-feature coverage and substantive-paragraph traceability gates
- Patent semantic validation is a required delivery state before DOCX/PDF acceptance
- Production hardcode AST audit with forbidden production branching = 0

## REAL-PAPER-002 V7.2 Clean Rebuild

- Case: `REAL-PAPER-002-V7-2-REBUILD`
- Standard production CLI used through checkpoint C and FINAL; no temporary `python -c` workflow construction
- Source language: `en`; patent/disclosure language: `zh-CN`
- Embodiments: 1 primary, 0 alternatives; primary steps: 9
- Required features: 4/4 covered
- Substantive paragraphs: 15/15 evidence-backed; unsupported: 0
- Semantic drift findings: 0; Section 5/7 mirror risk: false
- Patent Semantics Gate: PASS
- Delivery Quality Gate: PASS
- Final disclosure: 17 pages, 12 equations, 4 figures
- DOCX/PDF/OpenXML/render and visual sampling: PASS
- Case state: `DONE`

Canonical runtime manifest:

`workspace/private_cases/REAL-PAPER-002-V7-2-REBUILD/real_case_manifest.json`

The output package contains `real_case_manifest.json` only as a read-only delivery snapshot. It has `source_of_truth=false` and points to the canonical runtime manifest above.

## Regression Status

- CASE-001 regression: PASS; no case-specific exemption was introduced
- V7/V7.1 regression: PASS
- V7.2 semantic regression: 89 collected, 89 passed
- No test was deleted or weakened to obtain PASS

## Tests

Counts below are from actual pytest collection/execution on 2026-08-09:

- Starting baseline: **152 passed, 1 skipped, 0 failed**
- Final full suite: **245 passed, 1 skipped, 0 failed**
- V7.2 semantic suite: **89 collected, 89 passed**

## Production Hardcode Audit

- Scope: `patent_agent/**/*.py`, `app/**/*.py`
- Occurrences reviewed: 40
- Allowed evidence/vocabulary/documentation occurrences: 40
- Forbidden production case/domain hardcodes: **0**
- Canonical report: `production_hardcode_audit.json`

## Delivery Artifacts

Output directory:

`output/real_case/REAL-PAPER-002-V7-2-REBUILD/`

Primary files:

- `技术交底书_v7_2.docx`
- `技术交底书.docx`
- `技术交底书_v7_2.pdf`
- `权利要求草案.docx`
- `权利要求草案.pdf`
- `patent_semantics_report.md`
- `embodiment_audit.json`
- `semantic_drift_audit.json`
- `claim_embodiment_support.json`
- `section_redundancy_audit.json`
- `heading_audit.json`
- `section_audit.json`
- `figure_audit.json`
- `equation_audit.json`
- `render_audit.json`
- `traceability.json`
- `real_case_manifest.json` (read-only delivery snapshot)

## Known Boundaries

- Prior-art coverage remains limited to supplied/imported material and is not an exhaustive legal search.
- Inventor and patent-agent confirmation remains required for source omissions identified in `inventor_questions.md`.
- The generated claims are an auxiliary draft and require professional review before filing.
- Word-compatible final render acceptance on Windows requires Microsoft Word; this rebuild used Word COM successfully.
