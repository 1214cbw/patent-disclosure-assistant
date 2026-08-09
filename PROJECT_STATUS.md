# Patent Agent 项目状态

## Current Version

**V7.1 FINAL DELIVERY QUALITY HARDENING**

- Starting baseline: `7fd04f9`
- Product scope: evidence-grounded paper/report → Chinese patent technical disclosure
- Delivery state model: `CONTENT_VALIDATED → DOCX_VALIDATED → RENDER_VALIDATED → DELIVERY_READY → DONE`
- Standard production entry: CLI/Web share `build_real_case_workflow(...)` provider construction

## V7.1 Completed Capabilities

- Independent semantic 5.x headings and Chinese embodiment headings; no body slicing
- Section body/figure-description completeness and exact section routing gates
- Evidence-driven, case-local figure planning with required node/edge contracts
- Rendered graph parity, collision, dangling-edge, and narrative-consistency gates
- Evidence-derived technical-token registry and split-token validation
- Case-local inline-math registry derived from the current document equations
- Canonical OMML structural signature comparison for every display equation
- Microsoft Word compatible PDF export plus PyMuPDF geometry/render audit
- Explicit delivery states; `VALIDATED` is not treated as `DELIVERY_READY`
- Production hardcode AST audit with forbidden production branching = 0
- Open-vocabulary cross-case detection based on current evidence fingerprint; fixed concept families are auxiliary only
- Source-language detection separated from `patent_output_language=zh-CN`

## REAL-PAPER-002 V7.1 Clean Rebuild

- Case: `REAL-PAPER-002-V7-1-REBUILD`
- Standard production CLI used for A1 → A2 → B → C → FINAL
- Final acceptance used no temporary `python -c` workflow construction
- Source language: `en` (detected from ingested evidence)
- Patent/disclosure language: `zh-CN`
- `translation_postprocess_used=false`
- Technical headings: 20/20 PASS
- Sections: 44/44 PASS
- Figures: 5/5 PASS; 0 dangling edges; 0 collisions; rendered graph parity PASS
- Equations: 10/10 canonical OMML signatures PASS; PDF locations PASS
- Final rendered disclosure: 37 pages
- Delivery Quality Gate: PASS
- Case state: `DONE`

Canonical runtime manifest:

`workspace/private_cases/REAL-PAPER-002-V7-1-REBUILD/real_case_manifest.json`

The output package contains `real_case_manifest.json` only as a read-only delivery snapshot; it is not a second source of truth.

## REAL-PAPER-001 Regression

- Case-scope regression test: 1 passed
- Figure/layout/source regression suites: 20 passed
- No case-specific exemption or production branch was added
- Historical case-specific crop coordinates were removed from production code; reviewed coordinates must be supplied as case-local registry data

## Tests

Counts below are from actual pytest collection/execution on 2026-08-09:

- Full suite: **152 passed, 1 skipped, 0 failed**
- V7 generalization suite: **31 collected**
- V7.1 delivery-quality suite: **30 collected**
- Combined V7/V7.1 suites: **61 passed**
- CASE-001 explicit regression: **1 passed**
- Figure/layout regression suites: **20 passed**

The skipped test is retained; no test was deleted or weakened to obtain PASS.

## Production Hardcode Audit

- Scope: `patent_agent/**/*.py`, `app/**/*.py`
- Occurrences reviewed: 26
- Allowed evidence/vocabulary/documentation occurrences: 26
- Forbidden production case/domain hardcodes: **0**
- Canonical report: `production_hardcode_audit.json`

## Delivery Artifacts

Output directory:

`output/real_case/REAL-PAPER-002-V7-1-REBUILD/`

Primary files:

- `技术交底书_v7_1.docx`
- `技术交底书.docx`
- `技术交底书_v7_1.pdf`
- `权利要求草案.docx`
- `权利要求草案.pdf`
- `delivery_quality_report.md`
- `generalization_v7_1_report.md`
- `heading_audit.json`
- `section_audit.json`
- `figure_audit.json`
- `equation_audit.json`
- `render_audit.json`
- `traceability.json`
- `real_case_manifest.json` (read-only delivery snapshot)

## Known Boundaries

- Prior-art coverage remains limited to explicitly supplied/imported material and is not an exhaustive legal search.
- Inventor/agent confirmation remains required for source omissions identified in `inventor_questions.md`.
- The current equation renderer supports the documented patent-oriented math subset and fails closed on unsupported canonical expressions.
- Word-compatible render acceptance on Windows requires Microsoft Word; this V7.1 rebuild used Word COM successfully.
