"""Patent figure renderer with inline math ($...$) support.

Uses matplotlib mathtext for math expressions and PIL for Chinese text.
Separates text and math rendering for proper typography.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ── Font Detection ──────────────────────────────────────────────

def _detect_chinese_fonts() -> list[Path]:
    candidates = []
    font_dirs = [Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts"), Path("/System/Library/Fonts")]
    font_names = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "simsunb.ttf",
                  "NotoSansCJKsc-Regular.otf", "SourceHanSansSC-Regular.otf", "wqy-microhei.ttc"]
    for font_dir in font_dirs:
        if not font_dir.exists(): continue
        for name in font_names:
            path = font_dir / name
            if path.exists(): candidates.append(path)
        for pattern in ["*msyh*", "*simhei*", "*simsun*", "*Noto*CJK*", "*wqy*"]:
            for match in font_dir.glob(pattern):
                if match not in candidates: candidates.append(match)
    return candidates


_FONT_PATHS: list[Path] | None = None


def _get_chinese_font(size: int) -> ImageFont.FreeTypeFont:
    global _FONT_PATHS
    if _FONT_PATHS is None: _FONT_PATHS = _detect_chinese_fonts()
    for path in _FONT_PATHS:
        try: return ImageFont.truetype(str(path), size)
        except Exception: continue
    try: return ImageFont.truetype("arial.ttf", size)
    except Exception: return ImageFont.load_default()


# ── Math rendering (lazy init with Chinese height) ──────────────

_math_renderer = None
_chinese_body_height = None


def _get_math_renderer():
    global _math_renderer
    if _math_renderer is None:
        from .figure_math_renderer import FigureMathRenderer, FigureTypographyConfig
        cfg = FigureTypographyConfig()
        if _chinese_body_height:
            cfg.chinese_body_height_px = _chinese_body_height
        _math_renderer = FigureMathRenderer(config=cfg)
    return _math_renderer


def _classify_expr_role(expr: str) -> str:
    """Classify a LaTeX expression into small/normal/emphasis."""
    # Emphasis: full formulas with = sign or multiple terms with fractions
    if len(expr) > 25 and '=' in expr:
        return "emphasis"
    # Small: single variables, simple subscripts
    if len(expr) <= 12 and not any(c in expr for c in ('\\rightarrow', '\\cdots', '\\leq', '\\in', ',')):
        return "small"
    return "normal"


def _render_math_expr(expr: str) -> Image.Image | None:
    """Render a math expression to a PIL Image at proper scale."""
    r = _get_math_renderer()
    role = _classify_expr_role(expr)
    return r.render_latex(expr, role=role)


# ── Label parsing ────────────────────────────────────────────────

def _parse_label(label: str) -> list[tuple[str, str]]:
    """Parse label into (type, content) segments. type is 'text' or 'math'."""
    segments = []
    pattern = re.compile(r'\$(.+?)\$')
    pos = 0
    for m in pattern.finditer(label):
        if m.start() > pos:
            segments.append(('text', label[pos:m.start()]))
        segments.append(('math', m.group(1)))
        pos = m.end()
    if pos < len(label):
        segments.append(('text', label[pos:]))
    return segments


# ── Renderer ────────────────────────────────────────────────────

class PatentFigureRenderer:
    MIN_BOX_WIDTH = 160
    MIN_BOX_HEIGHT = 60
    H_PADDING = 28
    V_PADDING = 24
    NODE_GAP = 48
    MARGIN = 50
    MAX_CHARS_PER_LINE = 16
    FONT_SIZE = 22
    MATH_FONT_SIZE = 20

    def render(self, figure, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)

        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []

        main_font = _get_chinese_font(self.FONT_SIZE)
        small_font = _get_chinese_font(16)

        img_temp = Image.new("RGB", (100, 100), "white")
        draw_temp = ImageDraw.Draw(img_temp)

        # Compute Chinese body height for math scaling
        global _chinese_body_height
        cn_bbox = draw_temp.textbbox((0, 0), "中文测试变量", font=main_font)
        _chinese_body_height = cn_bbox[3] - cn_bbox[1]

        # Lazy init math renderer with Chinese height
        mr = _get_math_renderer()
        mr.set_chinese_height(_chinese_body_height)

        # Process labels: split into text/math segments
        processed = []
        for node in nodes:
            label = getattr(node, "label", str(node))
            segments = _parse_label(label)

            # Estimate total size
            total_h = 0
            max_w = self.MIN_BOX_WIDTH
            for typ, content in segments:
                if typ == 'text':
                    for line in content.split('\n'):
                        bbox = draw_temp.textbbox((0, 0), line, font=main_font)
                        max_w = max(max_w, bbox[2] - bbox[0] + 10)
                        total_h += bbox[3] - bbox[1] + 8
                else:  # math
                    img = _render_math_expr(content)
                    if img:
                        mw, mh = img.size
                        scale = self.MATH_FONT_SIZE / (self.FONT_SIZE * 0.8)
                        mw = int(mw * scale)
                        mh = int(mh * scale)
                        max_w = max(max_w, mw + 10)
                        total_h += mh + 4

            box_w = max(self.MIN_BOX_WIDTH, max_w + self.H_PADDING * 2)
            box_h = max(self.MIN_BOX_HEIGHT, total_h + self.V_PADDING * 2)

            processed.append({
                "id": getattr(node, "id", ""),
                "segments": segments,
                "box_w": box_w,
                "box_h": box_h,
            })

        # Canvas dimensions
        canvas_width = max(800, max(n["box_w"] for n in processed) + self.MARGIN * 4)
        total_h = sum(n["box_h"] for n in processed)
        total_gap = max(0, len(processed) - 1) * self.NODE_GAP
        canvas_height = self.MARGIN * 2 + total_h + total_gap + 100

        center_x = canvas_width // 2

        # ── Render PNG ──
        img = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(img)

        boxes = {}
        y = self.MARGIN + 40
        for pn in processed:
            x1 = center_x - pn["box_w"] // 2
            y1 = y
            x2 = x1 + pn["box_w"]
            y2 = y1 + pn["box_h"]
            boxes[pn["id"]] = (x1, y1, x2, y2)

            # Draw box
            draw.rectangle((x1, y1, x2, y2), outline="black", width=2, fill="white")

            # Render segments inside box
            seg_y = y1 + self.V_PADDING
            for typ, content in pn["segments"]:
                if typ == 'text':
                    for line in content.split('\n'):
                        if not line.strip():
                            seg_y += 8
                            continue
                        bbox = draw_temp.textbbox((0, 0), line, font=main_font)
                        line_w = bbox[2] - bbox[0]
                        line_h = bbox[3] - bbox[1]
                        lx = center_x - line_w // 2
                        draw.text((lx, seg_y), line, fill="black", font=main_font)
                        seg_y += line_h + 8
                else:  # math
                    math_img = _render_math_expr(content)
                    if math_img:
                        mw, mh = math_img.size
                        scale = self.MATH_FONT_SIZE / (self.FONT_SIZE * 0.75)
                        mw = int(mw * scale)
                        mh = int(mh * scale)
                        math_img = math_img.resize((mw, mh), Image.LANCZOS)
                        mx = center_x - mw // 2
                        if mx < x1 + 4: mx = x1 + 4
                        img.paste(math_img, (mx, int(seg_y)), math_img)
                        seg_y += mh + 4

            # Check not overflowing
            if seg_y > y2 - 4:
                pn["box_h"] = seg_y - y1 + self.V_PADDING
                boxes[pn["id"]] = (x1, y1, x2, y1 + pn["box_h"])

            y = y1 + pn["box_h"] + self.NODE_GAP

        # Redraw if any box resized (re-render)
        # Draw edges
        for edge in edges:
            src_id = getattr(edge, "source", "")
            tgt_id = getattr(edge, "target", "")
            if src_id not in boxes or tgt_id not in boxes: continue
            src = boxes[src_id]; tgt = boxes[tgt_id]
            x = center_x; y1 = src[3]; y2 = tgt[1]
            draw.line((x, y1, x, y2 - 8), fill="black", width=2)
            arrow_size = 8
            draw.polygon([(x, y2), (x - arrow_size, y2 - arrow_size * 2),
                          (x + arrow_size, y2 - arrow_size * 2)], fill="black")

        # Title
        title = getattr(figure, "title", "")
        if title:
            tb = draw_temp.textbbox((0, 0), title, font=small_font)
            draw.text((center_x - (tb[2]-tb[0])//2, 14), title, fill="black", font=small_font)

        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300, 300))

        # ── Render SVG ──
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<defs><marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">',
            '<polygon points="0 0, 10 3.5, 0 7" fill="black"/></marker></defs>',
        ]
        if title:
            svg_parts.append(f'<text x="{center_x}" y="24" text-anchor="middle" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="16">{escape(title)}</text>')
        for pn in processed:
            x1, y1, x2, y2 = boxes[pn["id"]]
            svg_parts.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="white" stroke="black" stroke-width="2"/>')
            seg_y = y1 + self.V_PADDING
            for typ, content in pn["segments"]:
                if typ == 'text':
                    for line in content.split('\n'):
                        if not line.strip(): seg_y += 8; continue
                        svg_parts.append(f'<text x="{center_x}" y="{seg_y+20}" text-anchor="middle" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="{self.FONT_SIZE}">{escape(line)}</text>')
                        seg_y += self.FONT_SIZE + 8
                else:
                    svg_parts.append(f'<text x="{center_x}" y="{seg_y+18}" text-anchor="middle" font-family="STIX, serif" font-size="{self.MATH_FONT_SIZE}" font-style="italic">{escape(content)}</text>')
                    seg_y += self.MATH_FONT_SIZE + 4
        for edge in edges:
            src_id = getattr(edge, "source", ""); tgt_id = getattr(edge, "target", "")
            if src_id in boxes and tgt_id in boxes:
                s = boxes[src_id]; t = boxes[tgt_id]
                svg_parts.append(f'<line x1="{center_x}" y1="{s[3]}" x2="{center_x}" y2="{t[1]-5}" stroke="black" stroke-width="2" marker-end="url(#arrowhead)"/>')
        svg_parts.append("</svg>")
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text("\n".join(svg_parts), encoding="utf-8")

        return figure.model_copy(update={"png_path": str(png_path), "svg_path": str(svg_path)})
