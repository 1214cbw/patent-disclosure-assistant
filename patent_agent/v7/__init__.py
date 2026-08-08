"""Patent Agent V7 - Generalization Hardening.

Native-Chinese disclosure generation with case isolation:

- ChinesePatentLanguageValidator (language gate before stage save)
- PatentDisclosurePlanner (facts -> technical chain -> full disclosure, in Chinese)
- CrossCaseContaminationValidator / PlaceholderLeakValidator / FigureSemanticValidator
- FigurePlannerV7 (concept-driven, case-local figure specs)
- run_disclosure_gates (single entry for all pre-finalize gates)

Every case artifact carries case_id; no cross-case content may flow into
another case's output. Evidence keeps its source language; final patent
content is zh-CN (PATENT_OUTPUT_LANGUAGE=zh-CN).
"""
