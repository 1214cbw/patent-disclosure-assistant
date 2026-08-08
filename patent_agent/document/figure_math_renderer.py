"""FigureMathRenderer with target-height scaling for figure compositing.

Uses matplotlib mathtext rendered at high DPI, then scaled to match
Chinese text height. Supports SMALL/NORMAL/EMPHASIS math roles.
"""
from __future__ import annotations

import io
from pathlib import Path
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image


# ── Typography Config ───────────────────────────────────────────

@dataclass
class FigureTypographyConfig:
    """Controls math-to-Chinese visual ratio in figures."""
    # Reference Chinese body text height in pixels (measured from PIL render)
    chinese_body_height_px: int = 23  # 22pt Microsoft YaHei

    # Math scale ratios relative to Chinese body height
    math_small_scale: float = 1.00      # Single variables: x, z_0, alpha, lambda
    math_normal_scale: float = 1.08     # Short expressions: z_0 -> z_t, epsilon_theta
    math_emphasis_scale: float = 1.22   # Key formulas: Z=(1-lambda)Z_1+lambda*Z_2

    # Rendering quality
    render_dpi: int = 300
    oversample_factor: float = 3.0  # Render at Nx target size, then downscale
    min_fontsize: int = 10
    max_fontsize: int = 36


# ── Math role classification ────────────────────────────────────

def classify_math_role(expression_key: str) -> str:
    """Classify a canonical math key into SMALL, NORMAL, or EMPHASIS."""
    # EMPHASIS: full interpolation formula
    if expression_key in ("Z_interpolation",):
        return "emphasis"

    # SMALL: single variables, simple subscripts, Greek letters
    small_keys = {
        "z_0", "z_t", "z_N", "z_{t-1}",
        "Z_1", "Z_2", "Z_t",
        "h_c", "h_bm", "h_bs",
        "alpha", "lambda", "epsilon",
        "x", "x'",
    }
    if expression_key in small_keys:
        return "small"

    # NORMAL: compound expressions
    return "normal"


def get_scale_for_role(role: str, config: FigureTypographyConfig) -> float:
    return {
        "small": config.math_small_scale,
        "normal": config.math_normal_scale,
        "emphasis": config.math_emphasis_scale,
    }.get(role, config.math_normal_scale)


# ── Canonical math expressions (unchanged) ──────────────────────

CANONICAL_MATH: dict[str, str] = {
    "z_0": r"$z_0$",
    "z_t": r"$z_t$",
    "z_N": r"$z_N$",
    "z_{t-1}": r"$z_{t-1}$",
    "Z_1": r"$Z_1$",
    "Z_2": r"$Z_2$",
    "Z_t": r"$Z_t$",
    "h_c": r"$h_c$",
    "h_bm": r"$h_{bm}$",
    "h_bs": r"$h_{bs}$",
    "alpha": r"$\alpha$",
    "lambda": r"$\lambda$",
    "epsilon": r"$\varepsilon$",
    "epsilon_theta(zt,t)": r"$\varepsilon_\theta(z_t,t)$",
    "x": r"$x$",
    "x'": r"$x'$",
    "1<=t<=T": r"$1 \leq t \leq T$",
    "lambda_in_01": r"$\lambda \in [0,1]$",
    "Z_interpolation": r"$Z=(1-\lambda)Z_1+\lambda Z_2$",
    "diffusion_flow": r"$z_0 \rightarrow z_t \rightarrow \cdots \rightarrow z_N$",
    "reverse_flow": r"$z_N \rightarrow \cdots \rightarrow z_t \rightarrow \cdots \rightarrow z_0$",
    "encode_flow": r"$x \rightarrow z_0$",
    "decode_flow": r"$z_0 \rightarrow x'$",
    "t_range": r"$t=1,2,\ldots,N$",
}


class FigureMathRenderer:
    """Render math with target-height scaling to match Chinese text size."""

    def __init__(self, config: FigureTypographyConfig | None = None):
        self.config = config or FigureTypographyConfig()
        self._cache: dict[str, Image.Image] = {}

    def set_chinese_height(self, px: int):
        """Update reference Chinese body height for scaling."""
        self.config.chinese_body_height_px = px

    def render(self, canonical_key: str, role: str | None = None) -> Image.Image | None:
        """Render a canonical math expression, scaled to target height."""
        if role is None:
            role = classify_math_role(canonical_key)

        cache_key = f"{canonical_key}_{role}_{self.config.chinese_body_height_px}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        expression = CANONICAL_MATH.get(canonical_key)
        if expression is None:
            return None

        try:
            img = self._render_scaled(expression, role)
            self._cache[cache_key] = img
            return img
        except Exception:
            return None

    def render_latex(self, latex: str, role: str = "small") -> Image.Image | None:
        """Render a raw LaTeX expression, scaled to target height."""
        if not latex.startswith("$"):
            latex = f"${latex}$"
        cache_key = f"custom_{latex}_{role}_{self.config.chinese_body_height_px}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            img = self._render_scaled(latex, role)
            self._cache[cache_key] = img
            return img
        except Exception:
            return None

    def _render_scaled(self, expression: str, role: str) -> Image.Image:
        """Render mathtext at oversampled size, then scale to target height."""
        cfg = self.config
        target_h = cfg.chinese_body_height_px * get_scale_for_role(role, cfg)

        # Render at oversampled size for quality
        oversample = cfg.oversample_factor
        render_fontsize = 20  # Base fontsize for mathtext

        # Create figure and render
        fig, ax = plt.subplots(figsize=(6, 1.5), dpi=cfg.render_dpi)
        ax.axis("off")
        text = ax.text(0.5, 0.5, expression, fontsize=render_fontsize,
                       ha="center", va="center", transform=ax.transAxes)
        fig.canvas.draw()
        renderer_obj = fig.canvas.get_renderer()
        bbox = text.get_window_extent(renderer=renderer_obj)
        bbox_inches = bbox.transformed(fig.dpi_scale_trans.inverted())
        plt.close(fig)

        # Calculate rendered math height in pixels
        rendered_h_px = bbox.height  # Already in display pixels
        if rendered_h_px <= 0:
            rendered_h_px = target_h * oversample

        # Determine scale factor
        scale = target_h / max(1, rendered_h_px)

        # If math is already close to target, no need to oversample
        if 0.8 <= scale <= 1.25:
            oversample = 1.0
            scale = 1.0 if scale > 0.95 else scale

        # Render at appropriate size
        effective_fontsize = render_fontsize * oversample
        fig2, ax2 = plt.subplots(
            figsize=(bbox_inches.width * 1.3, bbox_inches.height * 1.3),
            dpi=cfg.render_dpi,
        )
        ax2.axis("off")
        ax2.text(0.5, 0.5, expression, fontsize=effective_fontsize,
                 ha="center", va="center", transform=ax2.transAxes)

        buf = io.BytesIO()
        fig2.savefig(buf, format="png", dpi=cfg.render_dpi, transparent=True,
                      bbox_inches="tight", pad_inches=0.03)
        plt.close(fig2)
        buf.seek(0)

        img = Image.open(buf).convert("RGBA")

        # Scale to target height
        actual_scale = target_h / max(1, img.size[1])
        if abs(actual_scale - 1.0) > 0.02:
            new_w = max(1, int(img.size[0] * actual_scale))
            new_h = max(1, int(img.size[1] * actual_scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)

        return img

    def render_all_to_files(self, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        result = {}
        for key in CANONICAL_MATH:
            role = classify_math_role(key)
            img = self.render(key, role)
            if img is not None:
                path = output_dir / f"math_{key}.png"
                img.save(path)
                result[key] = path
        return result


def paste_math(canvas: Image.Image, math_img: Image.Image,
               position: tuple[int, int]) -> tuple[int, int]:
    """Paste a math image onto canvas at given position."""
    w, h = math_img.size
    canvas.paste(math_img, position, math_img)
    return w, h
