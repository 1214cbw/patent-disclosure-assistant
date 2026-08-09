"""Auxiliary evidence-local rules for polysemous technical translations.

The entries are vocabulary data, not case selectors. A rule is applied only
when its role pattern is present in the current paragraph evidence and its
contrary role is absent.
"""

TRANSLATION_ROLE_RULES = (
    {
        "source_role_patterns": (
            r"\bgenerator\b.{0,30}\bsurrogate\b",
            r"\bsurrogate\b.{0,30}\bgenerator\b",
        ),
        "contrary_role_patterns": (
            r"\belectric(?:al)?\s+generator\b",
            r"\bgenerator\s+(?:machine|motor)\b",
        ),
        "replacements": (("发电机", "生成模型"),),
    },
)
