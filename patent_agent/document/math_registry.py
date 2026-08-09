"""Math-symbol registry helpers.

Production rendering derives its registry from the current document's own
equations.  The historical registry below remains compatibility vocabulary
only and is not used as a production default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MathSymbol:
    """A registered math symbol with its proper LaTeX representation."""
    plain_form: str         # Plain text form found in disclosure
    latex: str              # LaTeX for OMML rendering
    kind: str = "variable"  # variable | greek | expression | subscript
    context_words: list[str] = field(default_factory=list)  # Words that indicate math context
    exclude_words: list[str] = field(default_factory=list)  # Words that indicate NOT math


def symbols_from_equations(equations: list[str]) -> list[MathSymbol]:
    """Build a case-local inline-math registry from canonical equations."""
    by_plain: dict[str, MathSymbol] = {}
    identifier = re.compile(
        r"[A-Za-zΑ-ωα-ω]+(?:_\{?[A-Za-z0-9Α-ωα-ω*+\-]+\}?)?"
    )
    for equation in equations:
        expression = str(equation or "").strip()
        if not expression:
            continue
        by_plain.setdefault(expression, MathSymbol(
            plain_form=expression, latex=expression, kind="expression"
        ))
        for token in identifier.findall(expression):
            if token in {"sqrt", "max", "min"}:
                continue
            latex = re.sub(r"_([A-Za-z0-9Α-ωα-ω*+\-]+)$", r"_{\1}", token)
            kind = "subscript" if "_" in token else (
                "greek" if re.fullmatch(r"[Α-ωα-ω]+", token) else "variable"
            )
            by_plain.setdefault(token, MathSymbol(token, latex, kind=kind))
            if "_" in token:
                collapsed = token.replace("_{", "").replace("}", "").replace("_", "")
                if len(collapsed) >= 2:
                    by_plain.setdefault(collapsed, MathSymbol(collapsed, latex, kind="subscript"))
    return list(by_plain.values())


def normalize_symbol_aliases(text: str, equations: list[str]) -> str:
    """Restore explicit subscript notation using only current-case equations."""
    value = str(text)
    replacements = []
    for symbol in symbols_from_equations(equations):
        if symbol.kind != "subscript" or "_" in symbol.plain_form:
            continue
        canonical = re.sub(r"_\{([^{}]+)\}", r"_\1", symbol.latex)
        replacements.append((symbol.plain_form, canonical))
    for alias, canonical in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        value = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
            canonical,
            value,
        )
    return value


# REAL-PAPER-001 Math Symbol Registry
# Based on original paper evidence and formula visual verification
REAL_PAPER_001_SYMBOLS: list[MathSymbol] = [
    # ── Design Variables ──
    MathSymbol(
        plain_form="hc", latex="h_c", kind="variable",
        context_words=["变量", "设计", "距离", "参数", "design", "distance"],
    ),
    MathSymbol(
        plain_form="hbm", latex="h_{bm}", kind="subscript",
        context_words=["变量", "设计", "厚度", "参数", "thickness", "磁障"],
    ),
    MathSymbol(
        plain_form="hbs", latex="h_{bs}", kind="subscript",
        context_words=["变量", "设计", "厚度", "参数", "thickness", "侧"],
    ),
    MathSymbol(
        plain_form="Alpha", latex="\\alpha", kind="greek",
        context_words=["变量", "设计", "角度", "参数", "angle", "开口"],
    ),

    # ── Greek Letters ──
    MathSymbol(
        plain_form="α", latex="\\alpha", kind="greek",
        context_words=["插值", "系数", "角度", "interpolation", "angle"],
    ),
    MathSymbol(
        plain_form="λ", latex="\\lambda", kind="greek",
        context_words=["插值", "系数", "interpolation", "coefficient"],
    ),

    # ── Latent Variables ──
    # Plain form aliases (both "z0" and "z_0" covered)
    MathSymbol(
        plain_form="z0", latex="z_0", kind="subscript",
        context_words=["潜在", "变量", "表示", "latent", "variable"],
        exclude_words=["FID"],
    ),
    MathSymbol(
        plain_form="z_0", latex="z_0", kind="subscript",
        context_words=["潜在", "变量", "latent"],
    ),
    MathSymbol(
        plain_form="zt", latex="z_t", kind="subscript",
        context_words=["潜在", "变量", "时间", "加噪", "latent", "timestep"],
    ),
    MathSymbol(
        plain_form="z_t", latex="z_t", kind="subscript",
        context_words=["潜在", "变量", "时间", "加噪", "latent", "timestep"],
    ),
    MathSymbol(
        plain_form="zN", latex="z_N", kind="subscript",
        context_words=["潜在", "变量", "噪声", "noise", "latent"],
    ),
    MathSymbol(
        plain_form="z_N", latex="z_N", kind="subscript",
        context_words=["潜在", "变量", "噪声", "noise", "latent"],
    ),
    MathSymbol(
        plain_form="z_{t-1}", latex="z_{t-1}", kind="expression",
        context_words=["潜在", "前一步", "去噪"],
    ),

    # ── Capital Latent Variables ──
    MathSymbol(
        plain_form="Z1", latex="Z_1", kind="subscript",
        context_words=["潜在", "变量", "第一个", "latent", "first"],
    ),
    MathSymbol(
        plain_form="Z_1", latex="Z_1", kind="subscript",
        context_words=["潜在", "变量", "第一个", "latent", "first"],
    ),
    MathSymbol(
        plain_form="Z2", latex="Z_2", kind="subscript",
        context_words=["潜在", "变量", "第二个", "latent", "second"],
    ),
    MathSymbol(
        plain_form="Z_2", latex="Z_2", kind="subscript",
        context_words=["潜在", "变量", "第二个", "latent", "second"],
    ),
    MathSymbol(
        plain_form="Z_t", latex="Z_t", kind="subscript",
        context_words=["潜在", "变量", "latent"],
    ),

    # ── Scalar Variables ──
    MathSymbol(
        plain_form="x", latex="x", kind="variable",
        context_words=["输入", "图像", "input", "image", "拓扑"],
        exclude_words=["index", "max", "U-Net"],
    ),
    MathSymbol(
        plain_form="t", latex="t", kind="variable",
        context_words=["时间", "步", "timestep", "time"],
        exclude_words=["U-Net", "t-SNE", "output", "current", "latent"],
    ),
    MathSymbol(
        plain_form="N", latex="N", kind="variable",
        context_words=["时间步", "步数", "扩散", "总", "total", "timestep"],
        exclude_words=["GAN", "U-Net", "when", "CNN"],
    ),
    MathSymbol(
        plain_form="T", latex="T", kind="variable",
        context_words=["时间步", "总步数", "total", "timestep"],
        exclude_words=["GPT", "BERT", "NOT"],
    ),
    MathSymbol(
        plain_form="Z", latex="Z", kind="variable",
        context_words=["潜在", "变量", "插值", "latent", "interpolation"],
    ),

    # ── Expressions ──
    MathSymbol(
        plain_form="1≤t≤T", latex="1 \\leq t \\leq T", kind="expression",
        context_words=["范围", "range", "timestep"],
    ),
    MathSymbol(
        plain_form="λ∈[0,1]", latex="\\lambda \\in [0,1]", kind="expression",
        context_words=["范围", "插值", "系数", "range", "interpolation"],
    ),
    MathSymbol(
        plain_form="Z=(1-λ)Z1+λZ2",
        latex="Z = (1-\\lambda) Z_1 + \\lambda Z_2",
        kind="expression",
        context_words=["插值", "公式", "interpolation", "formula"],
    ),
]

# Symbols that should NEVER be converted to math
EXCLUDED_ACRONYMS = {
    "GAN", "VAE", "LDM", "U-Net", "CNN", "RNN", "LSTM",
    "RGB", "FID", "PCA", "t-SNE", "PMa-SynRM", "IPMSM", "PMSM",
    "MSE", "Adam", "SGD", "ReLU", "DDPM", "DDIM",
}

# Symbols that are units (keep upright, not math-italic)
UNITS = {"mm", "cm", "m", "A", "V", "W", "Hz", "kHz", "rpm", "°"}


def build_symbol_map(symbols: list[MathSymbol]) -> dict[str, MathSymbol]:
    """Build a lookup map from plain form to MathSymbol."""
    return {s.plain_form: s for s in symbols}


def get_regex_pattern(symbols: list[MathSymbol]) -> str:
    """Build a regex pattern that matches registered math symbols.

    Uses word boundaries and context to avoid false positives.
    """
    # Sort by length (longest first) to avoid partial matches
    sorted_symbols = sorted(symbols, key=lambda s: len(s.plain_form), reverse=True)
    patterns = []
    for s in sorted_symbols:
        form = re.escape(s.plain_form)
        if s.kind == "expression":
            # Expressions can appear inline, match the full expression
            patterns.append(form)
        elif s.kind in ("greek",):
            # Greek letters match as-is
            patterns.append(form)
        else:
            # Variables need word boundaries
            patterns.append(r'\b' + form + r'\b')
    return '|'.join(patterns)


def should_be_math(
    token: str,
    context: str,
    symbol_map: dict[str, MathSymbol],
) -> bool:
    """Determine if a token should be converted to inline math."""
    if token in EXCLUDED_ACRONYMS:
        return False
    if token in UNITS:
        return False
    symbol = symbol_map.get(token)
    if symbol is None:
        return False
    # Check exclude words
    ctx_lower = context.lower()
    for excl in symbol.exclude_words:
        if excl.lower() in ctx_lower:
            return False
    return True
