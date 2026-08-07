"""Patent figure renderer with proper Chinese font support and dynamic layout.

Generates clean black-on-white patent-style flowcharts as PNG + SVG.
Auto-detects Chinese fonts and adjusts node sizes to prevent text clipping.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


# ── Font Detection ──────────────────────────────────────────────

def _detect_chinese_fonts() -> list[Path]:
    """Detect available Chinese fonts on the system."""
    candidates = []
    font_dirs = [
        Path(r"C:\Windows\Fonts"),
        Path("/usr/share/fonts"),
        Path("/System/Library/Fonts"),
    ]
    font_names = [
        "msyh.ttc", "msyhbd.ttc",  # Microsoft YaHei
        "simhei.ttf",              # SimHei
        "simsun.ttc", "simsunb.ttf",  # SimSun
        "NotoSansCJKsc-Regular.otf",
        "SourceHanSansSC-Regular.otf",
        "wqy-microhei.ttc",
    ]
    for font_dir in font_dirs:
        if not font_dir.exists():
            continue
        for name in font_names:
            path = font_dir / name
            if path.exists():
                candidates.append(path)
        # Also glob for any CJK font
        for pattern in ["*msyh*", "*simhei*", "*simsun*", "*Noto*CJK*", "*wqy*"]:
            for match in font_dir.glob(pattern):
                if match not in candidates:
                    candidates.append(match)

    return candidates


# Cache font detection
_FONT_PATHS: list[Path] | None = None


def _get_chinese_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a Chinese-capable font at the specified size."""
    global _FONT_PATHS
    if _FONT_PATHS is None:
        _FONT_PATHS = _detect_chinese_fonts()

    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue

    # Fallback: try PIL default (won't render Chinese correctly)
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _estimate_text_size(
    text: str, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw | None = None
) -> tuple[int, int]:
    """Estimate rendered text dimensions."""
    if draw is None:
        # Create a temporary image for measurement
        img = Image.new("RGB", (1, 1), "white")
        draw = ImageDraw.Draw(img)

    lines = text.split("\n")
    max_width = 0
    total_height = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        max_width = max(max_width, w)
        total_height += h + 4  # 4px line spacing

    return max_width, total_height


def _wrap_text_cn(text: str, max_chars_per_line: int = 14) -> list[str]:
    """Wrap Chinese text to fit within max characters per line."""
    lines = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        # For Chinese text, each char is roughly equal width
        while len(paragraph) > max_chars_per_line:
            # Find a good break point
            break_at = max_chars_per_line
            lines.append(paragraph[:break_at])
            paragraph = paragraph[break_at:]
        if paragraph:
            lines.append(paragraph)
    return lines


# ── Renderer ────────────────────────────────────────────────────

class PatentFigureRenderer:
    """Render patent-style figures with proper Chinese text handling."""

    # Layout constants (scalable)
    MIN_BOX_WIDTH = 140
    MIN_BOX_HEIGHT = 56
    H_PADDING = 28
    V_PADDING = 20
    NODE_GAP = 44
    MARGIN = 50
    MAX_CHARS_PER_LINE = 16

    def render(self, figure, output_dir: Path):
        """Render a FigureSpec to PNG and SVG files.

        Returns the figure spec with png_path and svg_path populated.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Calculate layout
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []

        # Font setup
        main_font = _get_chinese_font(22)
        small_font = _get_chinese_font(16)

        # Create temp image for measurement
        temp_img = Image.new("RGB", (100, 100), "white")
        temp_draw = ImageDraw.Draw(temp_img)

        # Process node labels: wrap text and calculate required box sizes
        processed_nodes = []
        for node in nodes:
            label = getattr(node, "label", str(node))
            wrapped = _wrap_text_cn(label, self.MAX_CHARS_PER_LINE)
            # Estimate size
            max_w = 0
            total_h = 0
            for line in wrapped:
                bbox = temp_draw.textbbox((0, 0), line, font=main_font)
                max_w = max(max_w, bbox[2] - bbox[0])
                total_h += bbox[3] - bbox[1] + 6
            box_w = max(self.MIN_BOX_WIDTH, max_w + self.H_PADDING * 2)
            box_h = max(self.MIN_BOX_HEIGHT, total_h + self.V_PADDING * 2)
            processed_nodes.append({
                "id": getattr(node, "id", ""),
                "label": label,
                "wrapped": wrapped,
                "box_w": box_w,
                "box_h": box_h,
            })

        # Calculate canvas dimensions
        canvas_width = max(
            800,
            max(n["box_w"] for n in processed_nodes) + self.MARGIN * 4,
        )
        total_nodes_height = sum(n["box_h"] for n in processed_nodes)
        total_gap = max(0, len(processed_nodes) - 1) * self.NODE_GAP
        canvas_height = self.MARGIN * 2 + total_nodes_height + total_gap + 100

        # Center all boxes horizontally
        center_x = canvas_width // 2

        # ── Render PNG ──
        img = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(img)

        boxes = {}
        y = self.MARGIN + 40  # extra top space for title
        for pn in processed_nodes:
            x1 = center_x - pn["box_w"] // 2
            y1 = y
            x2 = x1 + pn["box_w"]
            y2 = y1 + pn["box_h"]
            boxes[pn["id"]] = (x1, y1, x2, y2)

            # Draw box
            draw.rectangle((x1, y1, x2, y2), outline="black", width=2, fill="white")

            # Draw text centered
            total_text_h = sum(
                temp_draw.textbbox((0, 0), line, font=main_font)[3] -
                temp_draw.textbbox((0, 0), line, font=main_font)[1] + 6
                for line in pn["wrapped"]
            )
            text_y = y1 + (pn["box_h"] - total_text_h) // 2
            for line in pn["wrapped"]:
                bbox = temp_draw.textbbox((0, 0), line, font=main_font)
                line_w = bbox[2] - bbox[0]
                line_h = bbox[3] - bbox[1]
                line_x = center_x - line_w // 2
                draw.text((line_x, text_y), line, fill="black", font=main_font)
                text_y += line_h + 6

            y = y2 + self.NODE_GAP

        # Draw edges (arrows between boxes)
        for edge in edges:
            src_id = getattr(edge, "source", "")
            tgt_id = getattr(edge, "target", "")
            if src_id not in boxes or tgt_id not in boxes:
                continue
            src = boxes[src_id]
            tgt = boxes[tgt_id]
            # Arrow from bottom of source to top of target
            x = center_x
            y1 = src[3]
            y2 = tgt[1]
            # Line
            draw.line((x, y1, x, y2 - 8), fill="black", width=2)
            # Arrowhead
            arrow_size = 8
            draw.polygon(
                [(x, y2), (x - arrow_size, y2 - arrow_size * 2),
                 (x + arrow_size, y2 - arrow_size * 2)],
                fill="black",
            )
            # Edge label if present
            edge_label = getattr(edge, "label", "")
            if edge_label:
                label_w = temp_draw.textbbox((0, 0), edge_label[:20], font=small_font)[2]
                draw.text(
                    (x + 12, (y1 + y2) // 2 - 10),
                    edge_label[:20],
                    fill="black",
                    font=small_font,
                )

        # Add figure title at top
        title = getattr(figure, "title", "")
        if title:
            title_bbox = temp_draw.textbbox((0, 0), title, font=small_font)
            title_w = title_bbox[2] - title_bbox[0]
            draw.text(
                (center_x - title_w // 2, 14),
                title,
                fill="black",
                font=small_font,
            )

        # Save PNG
        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300, 300))

        # ── Render SVG ──
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<defs>',
            '<marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">',
            '<polygon points="0 0, 10 3.5, 0 7" fill="black"/>',
            '</marker>',
            '</defs>',
        ]

        # SVG title
        if title:
            svg_parts.append(
                f'<text x="{center_x}" y="24" text-anchor="middle" '
                f'font-family="Microsoft YaHei, SimHei, sans-serif" font-size="16">{escape(title)}</text>'
            )

        # SVG nodes
        for pn in processed_nodes:
            x1, y1, x2, y2 = boxes[pn["id"]]
            svg_parts.append(
                f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" '
                f'fill="white" stroke="black" stroke-width="2"/>'
            )
            # Calculate text position
            total_h = len(pn["wrapped"]) * 28
            text_start_y = y1 + (pn["box_h"] - total_h) // 2 + 20
            for i, line in enumerate(pn["wrapped"]):
                svg_parts.append(
                    f'<text x="{center_x}" y="{text_start_y + i * 28}" '
                    f'text-anchor="middle" font-family="Microsoft YaHei, SimHei, sans-serif" '
                    f'font-size="22">{escape(line)}</text>'
                )

        # SVG edges
        for edge in edges:
            src_id = getattr(edge, "source", "")
            tgt_id = getattr(edge, "target", "")
            if src_id not in boxes or tgt_id not in boxes:
                continue
            src = boxes[src_id]
            tgt = boxes[tgt_id]
            x = center_x
            y1, y2 = src[3], tgt[1]
            svg_parts.append(
                f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2-5}" '
                f'stroke="black" stroke-width="2" marker-end="url(#arrowhead)"/>'
            )
            edge_label = getattr(edge, "label", "")
            if edge_label:
                svg_parts.append(
                    f'<text x="{x+12}" y="{(y1+y2)//2}" '
                    f'font-family="Microsoft YaHei, SimHei, sans-serif" font-size="16">{escape(edge_label[:20])}</text>'
                )

        svg_parts.append("</svg>")
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text("\n".join(svg_parts), encoding="utf-8")

        # Return updated figure spec
        return figure.model_copy(update={
            "png_path": str(png_path),
            "svg_path": str(svg_path),
        })
