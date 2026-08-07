# Architecture Decisions

## Third-party evaluation (2026-08-07)

| Project | Decision | Reason |
|---|---|---|
| patent-disclosure-skill | ADAPT | Strong project scanning, invention mining, CNIPA fallback and revision workflow. Its `math_render.py` explicitly renders LaTeX to PNG, so that implementation is rejected in favor of the existing OMML engine. |
| ARIS | ADAPT | Useful staged patent pipeline, persistent artifacts, claim-feature matrix and reviewer loops. This project re-implements those contracts with Pydantic and local case storage. |
| Patent-assistant | REFERENCE_ONLY | Useful FastAPI/SQLite chapter editing and version snapshot concepts, but its prompt-first generation architecture is not used as the core. |
| PQAI | REFERENCE_ONLY | Valid future search provider and MIT licensed, but its model/index stack is heavyweight. V1 uses a provider interface plus manual import and does not transmit private disclosure text automatically. |

No third-party implementation was copied. Commit hashes and notices are recorded in `THIRD_PARTY_NOTICES.md`.

## Core boundary

`Source Materials -> PatentKnowledge -> Invention/Strategy -> Patent AST -> DocumentRenderer -> DOCX -> Validation`

Agents never manipulate OOXML. The renderer never invokes an LLM. Search providers receive explicit search queries or imported public documents, not entire case folders.

