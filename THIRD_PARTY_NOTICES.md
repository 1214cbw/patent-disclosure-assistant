# Third-Party Notices

No third-party source code is copied into this project.

Architecture research was performed against the following MIT-licensed repositories on 2026-08-07:

| Project | Commit inspected | Decision | Use |
|---|---|---|---|
| patent-disclosure-skill | `67e0cd0718dc6b0cd839719d04f73a79e3601624` | ADAPT | Workflow concepts only; its LaTeX-to-PNG formula implementation is explicitly excluded. |
| ARIS | `2f00c5175503d1a75d43141575ff75889d4b68af` | ADAPT | Stage artifacts, checkpoint discipline, claim-feature matrices and review concepts. |
| Patent-assistant | `7123187a1e071b402c4e87ff6d2ce8d1aff825e4` | REFERENCE_ONLY | Chapter version history and local UI concepts. |
| PQAI | `56342aaac5d9bf626f9413e5e49819e70709ce2f` | REFERENCE_ONLY | Future prior-art provider integration; no runtime dependency in V1. |

The native OMML equation engine is migrated from the locally developed `patent_equation_poc` project in the same workspace and remains covered by its regression tests.

