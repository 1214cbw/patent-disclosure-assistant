# V7.1 Baseline Defect Audit

## Scope and immutable baseline

- Repository: `C:\Users\25032\Desktop\gongshi\patent_agent`
- Branch / commit: `main` / `7fd04f9d5b5704826114da496824e0654898375a`
- Baseline tests: 121 passed, 1 skipped, 0 failed; V7 collection: 31 tests.
- Audited artifact: `output/real_case/REAL-PAPER-002-V7-REBUILD/技术交底书_v7_0.docx`.
- Rendering: Microsoft Word COM produced a 27-page PDF because LibreOffice is not installed in the execution environment. Poppler rendered all 27 PDF pages to PNG for inspection.

This file records defects reproduced before V7.1 production repairs. It is not a statement that the historic V7 package is delivery-ready.

## Reproduced defects

| Code | Reproduction evidence | Root cause / control gap |
|---|---|---|
| `TITLE_PREFIX_TRUNCATION` | Page 4 contains a 5.1 heading ending mid-phrase; several other 5.x headings are incomplete. | `PatentDisclosurePlanner._generate_section` derives a heading from the first body sentence and slices it with `[:24]`; the heading is not an independent semantic planning field. |
| `TECHNICAL_SECTION_BODY_MISSING` | DOCX paragraph order has heading 5.15 immediately followed by 5.16 although structured section 05-15 contains four paragraphs. | `_is_figure_section` accepts the generic character `图`. A technical heading containing `图像` is therefore routed as an attached-figure section and its body is skipped. |
| `FIGURE_DESCRIPTION_SECTION_EMPTY` | Heading 6 is immediately followed by heading 7, although structured section 06 contains a figure-description paragraph. | The same broad figure-section predicate inserts figures at the earlier false-positive 5.x heading, then suppresses the actual section-6 body because figures were already inserted. |
| `TECHNICAL_TOKEN_SPLIT` | Rendered pages contain `FlowV AE`, `V AE+FM` and `plain-V AE`. | Generated prose is persisted without normalization against a case-derived terminology registry; the existing language gate does not enforce token integrity. |
| `DUPLICATE_TERM_EXPANSION` | Figure 3 caption contains `流匹配（流匹配）`. | Caption/title generation has no bilingual-term deduplication gate. |
| `DANGLING_ARROW` | Figure 4 has an incoming arrow with no visible source node; figure 5 also shows an arrow entering the first node from outside the graph. | Figure planning does not declare required graph topology and the renderer is not checked against the planned nodes and edges. |
| `FIGURE_NARRATIVE_CONTRADICTION` | Body text states that numerical ordinary-differential-equation solving is unnecessary, while figure 3 contains an `ODE 积分` operation. | Figure semantics are selected by case/domain keyword branches instead of being checked against linked current-case facts and narrative assertions. |
| `EQUATION_INTEGRITY_UNGUARDED` | The structured result declares eq1–eq10 and the Word-COM baseline render visually shows ten equations, but the V7 gate only checks count/presence and cannot detect token, operator, parenthesis or structural loss. | No canonical equation signature is compared with actual OMML and rendered formula geometry. A deliberately truncated equation can pass the historic gate. |
| `PRODUCTION_CASE_HARDCODE` | Production figure planning contains FlowVAE/FiLM/rotor/motor/torque/flux/voltage and LDM-specific branches and graph structures. | Output planning is controlled by case/domain vocabulary instead of case-local evidence/facts. |
| `STANDARD_PIPELINE_PROVIDER_MISSING` | CLI/Web `checkpoint-continue` instantiate `RealCaseWorkflow(settings)` without a provider; the B→C path can silently take a deterministic fallback. | Provider construction is not centralized and the workflow does not fail closed at an LLM-required checkpoint. |
| `CROSS_CASE_FIXED_VOCAB_DEPENDENCY` | Cross-case checking relies substantially on `CONCEPT_FAMILIES` and sibling fingerprints. | Unknown vocabulary and factually wrong content inside a broad known family are not reliably tested against the current case's evidence fingerprint. |
| `PROJECT_METADATA_STALE` | `PROJECT_STATUS.md` reports V2-P2, 65 tests and REAL-PAPER-001; the actual V7 test collection is 31. | Status and delivery metadata were not updated from runtime facts. |
| `MANIFEST_LOCATION_AMBIGUOUS` | No manifest is present in the V7 output package; the canonical runtime manifest is under `workspace/private_cases/REAL-PAPER-002-V7-REBUILD/real_case_manifest.json`. | Delivery-snapshot and runtime-state roles are not documented or represented in the package. |
| `SOURCE_LANGUAGE_STALE` | The manifest reports `UNKNOWN`, while the case evidence JSONL contains English `raw_text` and `normalized_text`. | Language detection is not reliably refreshed into final delivery metadata. The patent output language remains independently configured as `zh-CN`. |

## Acceptance implications

V7.1 must fail closed unless the standard CLI/Web path has a provider for LLM-required stages; every substantive section has routed body content; headings, terms, equations and graphs pass structural validation; all figures agree with linked evidence; a PDF render audit passes; the production hardcode audit reports zero forbidden case/domain branching; and a clean rebuild reaches `DELIVERY_READY` through the standard production entry point.
