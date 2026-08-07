"""FigureMathRenderer - renders math expressions as high-res images for figures.

Uses matplotlib mathtext to render canonical math expressions (e.g., z_0, \\lambda)
as tightly-cropped PNG images that can be composited into figure layouts.

This separates Chinese text rendering (PIL) from math rendering (mathtext),
ensuring proper subscript, Greek, and math italic rendering in figures.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image


# Canonical math expressions used in REAL-PAPER-001 figures
CANONICAL_MATH: dict[str, str] = {
    # Subscripts
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
    # Greek
    "alpha": r"$\alpha$",
    "lambda": r"$\lambda$",
    "epsilon": r"$\varepsilon$",
    # Complex
    "epsilon_theta(zt,t)": r"$\varepsilon_\theta(z_t,t)$",
    "x": r"$x$",
    "x'": r"$x'$",
    # Expressions
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
    """Render canonical math expressions as high-res images for figure compositing."""

    def __init__(self, dpi: int = 300, fontsize: int = 18):
        self.dpi = dpi
        self.fontsize = fontsize
        self._cache: dict[str, Image.Image] = {}

    def render(self, canonical_key: str) -> Image.Image | None:
        """Render a canonical math expression to a PIL Image.

        Args:
            canonical_key: Key in CANONICAL_MATH dict, e.g., 'z_0', 'lambda'

        Returns:
            PIL Image with transparent background, or None if key not found.
        """
        if canonical_key in self._cache:
            return self._cache[canonical_key]

        expression = CANONICAL_MATH.get(canonical_key)
        if expression is None:
            return None

        try:
            img = self._render_mathtext(expression, canonical_key)
            self._cache[canonical_key] = img
            return img
        except Exception:
            return None

    def render_latex(self, latex: str) -> Image.Image | None:
        """Render a raw LaTeX expression to a PIL Image."""
        if not latex.startswith("$"):
            latex = f"${latex}$"
        try:
            return self._render_mathtext(latex, "custom")
        except Exception:
            return None

    def _render_mathtext(self, expression: str, cache_key: str) -> Image.Image:
        """Internal: render a mathtext expression to PIL Image."""
        # Create a figure just big enough
        fig, ax = plt.subplots(figsize=(0.1, 0.1), dpi=self.dpi)
        ax.axis("off")

        # Render the math text
        text = ax.text(0, 0, expression, fontsize=self.fontsize,
                       ha="left", va="bottom",
                       transform=ax.transAxes)

        # Let matplotlib compute the bounding box
        fig.canvas.draw()
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer())
        bbox = bbox.transformed(fig.dpi_scale_trans.inverted())

        # Add small padding
        pad = 0.02
        bbox = bbox.expanded(1.05, 1.1)

        plt.close(fig)

        # Re-render with tight bounds
        fig, ax = plt.subplots(
            figsize=(bbox.width + pad, bbox.height + pad),
            dpi=self.dpi,
        )
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.text(0.0, 0.0, expression, fontsize=self.fontsize,
                ha="left", va="bottom", transform=ax.transAxes)

        # Save to in-memory buffer
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=self.dpi, transparent=True,
                     bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        buf.seek(0)

        img = Image.open(buf).convert("RGBA")
        return img

    def render_all_to_files(self, output_dir: Path) -> dict[str, Path]:
        """Render all canonical math expressions to PNG files.

        Returns dict mapping canonical_key -> file_path.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        result = {}
        for key in CANONICAL_MATH:
            img = self.render(key)
            if img is not None:
                path = output_dir / f"math_{key}.png"
                img.save(path)
                result[key] = path
        return result

    def preload_all(self) -> None:
        """Pre-render all canonical expressions into cache."""
        for key in CANONICAL_MATH:
            self.render(key)


# Convenience: composite math image into a PIL figure at a specific position
def paste_math(
    canvas: Image.Image,
    math_img: Image.Image,
    position: tuple[int, int],
    max_width: int | None = None,
    max_height: int | None = None,
) -> tuple[int, int]:
    """Paste a math image onto a canvas at the given position.

    Optionally rescales the math image to fit within max dimensions.
    Returns the (width, height) of the pasted image.
    """
    w, h = math_img.size

    # Resize if needed
    if max_width and w > max_width:
        ratio = max_width / w
        w = max_width
        h = int(h * ratio)
        math_img = math_img.resize((w, h), Image.LANCZOS)

    if max_height and h > max_height:
        ratio = max_height / h
        h = max_height
        w = int(w * ratio)
        math_img = math_img.resize((w, h), Image.LANCZOS)

    canvas.paste(math_img, position, math_img)
    return w, h
