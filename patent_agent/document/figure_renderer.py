"""Patent figure renderer V6.6 - stable layout with bbox tracking.

Every drawn element records a BBox; after the initial placement a
collision pass runs and the layout auto-reflows (bigger gaps / wider
columns / larger canvas) until clean or the attempt budget is spent.
Each render writes a layout report JSON next to the PNG for validation.

Uses matplotlib mathtext for math expressions and PIL for Chinese text.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .figure_layout import BBox, CollisionDetector, LayoutElement, LayoutReport


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


def _layout_report_path(output_dir: Path, number: int) -> Path:
    return output_dir / f"figure_{number:02d}_layout.json"


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
    if len(expr) > 25 and '=' in expr:
        return "emphasis"
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
    FONT_SIZE = 22
    MATH_FONT_SIZE = 20
    MAX_REFLOW_ATTEMPTS = 10

    def render(self, figure, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)

        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        layout = getattr(figure, 'layout', 'auto') or 'auto'

        # ── Source figure: preserve as-is (no baked title) ──
        source_png = getattr(figure, 'png_path', '') or ''
        if source_png and Path(source_png).exists() and len(nodes) <= 1 and not edges:
            return self._render_source_figure(figure, output_dir)

        if layout == 'auto':
            layout = self._detect_layout(nodes, edges)
        if layout == 'branch_merge':
            return self._render_branch_merge(figure, output_dir)
        elif layout == 'two_column':
            return self._render_two_column(figure, output_dir)
        else:
            return self._render_vertical(figure, output_dir)

    # ── Common setup ───────────────────────────────────────────

    def _setup_fonts(self):
        main_font = _get_chinese_font(self.FONT_SIZE)
        small_font = _get_chinese_font(16)
        temp = ImageDraw.Draw(Image.new('RGB', (1, 1), 'white'))
        global _chinese_body_height
        cn_bbox = temp.textbbox((0, 0), "中", font=main_font)
        _chinese_body_height = cn_bbox[3] - cn_bbox[1]
        _get_math_renderer().set_chinese_height(_chinese_body_height)
        return main_font, small_font, temp

    def _measure_node(self, node, font, draw) -> dict:
        """Measure a node: parse label, compute box_w/box_h and per-line items."""
        label = getattr(node, 'label', str(node))
        segs = _parse_label(label)
        items = []  # (kind, content, w, h)
        total_h = 0
        max_w = self.MIN_BOX_WIDTH
        for typ, content in segs:
            if typ == 'text':
                for line in content.split('\n'):
                    if not line.strip():
                        items.append(('gap', '', 0, 8))
                        total_h += 8
                        continue
                    bbox = draw.textbbox((0, 0), line, font=font)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                    items.append(('text', line, w, h))
                    max_w = max(max_w, w + 10)
                    total_h += h + 8
            else:
                img = _render_math_expr(content)
                if img:
                    items.append(('math', content, img.size[0], img.size[1]))
                    max_w = max(max_w, img.size[0] + 10)
                    total_h += img.size[1] + 6
        box_w = max(self.MIN_BOX_WIDTH, max_w + self.H_PADDING * 2)
        box_h = max(self.MIN_BOX_HEIGHT, total_h + self.V_PADDING * 2)
        return {'id': getattr(node, 'id', ''), 'segs': segs, 'items': items,
                'box_w': box_w, 'box_h': box_h, 'label': label}

    def _draw_node_content(self, img, draw, pn, x, y, font, elements: list[LayoutElement], node_id: str, column: str = "") -> None:
        """Draw node box + centered content; record text/math element bboxes."""
        x2, y2 = x + pn['box_w'], y + pn['box_h']
        draw.rectangle((x, y, x2, y2), outline='black', width=2, fill='white')
        elements.append(LayoutElement('node', BBox(x, y, pn['box_w'], pn['box_h']), node_id=node_id, column=column))
        cx = x + pn['box_w'] // 2
        seg_y = y + self.V_PADDING
        for kind, content, w, h in pn['items']:
            if kind == 'gap':
                seg_y += h
                continue
            if kind == 'text':
                lx = cx - w // 2
                draw.text((lx, seg_y), content, fill='black', font=font)
                elements.append(LayoutElement('text', BBox(lx, seg_y, w, h), node_id=node_id, content=content, column=column))
                seg_y += h + 8
            elif kind == 'math':
                math_img = _render_math_expr(content)
                if math_img:
                    mx = cx - w // 2
                    if mx < x + 4: mx = x + 4
                    img.paste(math_img, (mx, int(seg_y)), math_img)
                    elements.append(LayoutElement('math', BBox(mx, seg_y, w, h), node_id=node_id, content=content, column=column))
                    seg_y += h + 6

    # ── Reflow helper ──────────────────────────────────────────

    def _reflow(self, attempt: int, gap: int, canvas_w: int, canvas_h: int,
                max_gap: int, grow: int) -> tuple[int, int, int]:
        """Increase gaps on collision; grow canvas; return new (gap, w, h)."""
        gap = min(gap + grow, max_gap)
        return gap, canvas_w, canvas_h

    def _write_outputs(self, figure, img, report: LayoutReport, output_dir: Path):
        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300, 300))
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text(self._make_svg(figure, report), encoding='utf-8')
        report_path = output_dir / f"figure_{figure.number:02d}_layout.json"
        report.save(report_path)
        return figure.model_copy(update={'png_path': str(png_path), 'svg_path': str(svg_path)})

    @staticmethod
    def _make_svg(figure, report: LayoutReport) -> str:
        w, h = report.canvas.get('w', 800), report.canvas.get('h', 600)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<defs><marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">',
            '<polygon points="0 0, 10 3.5, 0 7" fill="black"/></marker></defs>']
        if report.title_bbox:
            tx, ty, tw, th = report.title_bbox
            parts.append(f'<text x="{tx + tw // 2}" y="{ty + th}" text-anchor="middle" '
                         f'font-family="Microsoft YaHei" font-size="16">{escape(figure.title)}</text>')
        for el in report.elements:
            bx, by, bw, bh = el.bbox.to_list()
            if el.kind == 'node':
                parts.append(f'<rect x="{bx:.0f}" y="{by:.0f}" width="{bw:.0f}" height="{bh:.0f}" '
                             f'fill="white" stroke="black" stroke-width="2"/>')
            elif el.kind == 'text':
                parts.append(f'<text x="{bx + bw / 2:.0f}" y="{by + bh:.0f}" text-anchor="middle" '
                             f'font-family="Microsoft YaHei" font-size="22">{escape(el.content)}</text>')
        for el in report.elements:
            if el.kind == 'arrow':
                pts = [el.bbox.center_x, el.bbox.center_y]
                parts.append(f'<line x1="{pts[0]:.0f}" y1="{pts[1]:.0f}" x2="{pts[0]:.0f}" y2="{pts[1]:.0f}" '
                             f'stroke="black" stroke-width="2"/>')
        parts.append('</svg>')
        return '\n'.join(parts)

    # ── Source figure ──────────────────────────────────────────

    def _render_source_figure(self, figure, output_dir: Path):
        """Copy a real source PNG, preserving aspect ratio, no baked title."""
        from PIL import Image as PILImage
        src_path = Path(figure.png_path)
        img = PILImage.open(src_path).convert('RGB')

        max_w = 1400
        if img.size[0] > max_w:
            ratio = max_w / img.size[0]
            img = img.resize((max_w, int(img.size[1] * ratio)), PILImage.LANCZOS)

        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300, 300))

        w, h = img.size
        report = LayoutReport(
            figure_id=figure.id, number=figure.number, layout='source',
            canvas={'w': w, 'h': h},
            elements=[LayoutElement('source_image', BBox(0, 0, w, h),
                                    node_id='R01', content=str(src_path.name))],
        )
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
            f'<image href="{src_path.name}" width="{w}" height="{h}" x="0" y="0"/>'
            f'</svg>', encoding='utf-8')
        report_path = output_dir / f"figure_{figure.number:02d}_layout.json"
        report.save(report_path)

        return figure.model_copy(update={
            'png_path': str(png_path), 'svg_path': str(svg_path),
            'layout_report': str(report_path),
        })

    @staticmethod
    def _detect_layout(nodes, edges) -> str:
        """Detect layout type from edge connections (legacy fallback)."""
        if not edges:
            return 'vertical'
        in_degree = {}
        for e in edges:
            tgt = getattr(e, 'target', '')
            in_degree[tgt] = in_degree.get(tgt, 0) + 1
        if any(d >= 2 for d in in_degree.values()):
            return 'branch_merge'
        bridge_edges = [e for e in edges if getattr(e, 'label', '')]
        if bridge_edges and len(nodes) >= 8:
            return 'two_column'
        return 'vertical'

    # ── Vertical layout ────────────────────────────────────────

    def _render_vertical(self, figure, output_dir: Path):
        main_font, small_font, temp = self._setup_fonts()
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        processed = [self._measure_node(n, main_font, temp) for n in nodes]

        gap = self.NODE_GAP
        elements: list[LayoutElement] = []
        detector = CollisionDetector(pad=2.0)
        attempts = 0
        report = LayoutReport(figure_id=figure.id, number=figure.number, layout='vertical')

        while attempts < self.MAX_REFLOW_ATTEMPTS:
            canvas_w = max(800, max(n['box_w'] for n in processed) + self.MARGIN * 3)
            total_h = sum(n['box_h'] for n in processed) + max(0, len(processed) - 1) * gap
            canvas_h = self.MARGIN * 2 + total_h + 90
            cx = canvas_w // 2
            img = Image.new('RGB', (canvas_w, canvas_h), 'white')
            draw = ImageDraw.Draw(img)
            elements = []
            boxes: dict[str, tuple[int, int, int, int]] = {}
            y = self.MARGIN + 50
            for pn in processed:
                x = cx - pn['box_w'] // 2
                self._draw_node_content(img, draw, pn, x, y, main_font, elements, pn['id'])
                boxes[pn['id']] = (x, y, x + pn['box_w'], y + pn['box_h'])
                y += pn['box_h'] + gap
            # arrows
            for edge in edges:
                src, tgt = getattr(edge, 'source', ''), getattr(edge, 'target', '')
                if src in boxes and tgt in boxes:
                    self._draw_straight_arrow(draw, boxes[src], boxes[tgt], elements, src, tgt)
            # title
            tb = temp.textbbox((0, 0), figure.title, font=small_font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            draw.text((cx - tw // 2, 14), figure.title, fill='black', font=small_font)
            report.title_bbox = [cx - tw // 2, 14, tw, th]
            report.canvas = {'w': canvas_w, 'h': canvas_h}
            report.elements = elements
            report.collisions = detector.detect(elements)
            attempts += 1
            report.reflow_attempts = attempts
            if not report.collisions:
                break
            gap = min(gap + 16, 120)

        return self._write_outputs(figure, img, report, output_dir)

    # ── Two-column layout (Fig.3) ──────────────────────────────

    def _render_two_column(self, figure, output_dir: Path):
        main_font, small_font, temp = self._setup_fonts()
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        left_ids = list(getattr(figure, 'left_node_ids', []) or [])
        right_ids = list(getattr(figure, 'right_node_ids', []) or [])
        node_map = {n.id: n for n in nodes}
        if left_ids and right_ids:
            left_nodes = [node_map[i] for i in left_ids if i in node_map]
            right_nodes = [node_map[i] for i in right_ids if i in node_map]
        else:
            # fallback: id prefix T/G
            left_nodes = [n for n in nodes if n.id.startswith('T')] or nodes[:len(nodes) // 2]
            right_nodes = [n for n in nodes if n.id.startswith('G')] or nodes[len(nodes) // 2:]
        if not right_nodes and left_nodes:
            right_nodes = []
        processed_l = [self._measure_node(n, main_font, temp) for n in left_nodes]
        processed_r = [self._measure_node(n, main_font, temp) for n in right_nodes]

        row_gap = 40
        col_gap = 60
        elements: list[LayoutElement] = []
        detector = CollisionDetector(pad=2.0)
        attempts = 0
        report = LayoutReport(figure_id=figure.id, number=figure.number, layout='two_column')

        while attempts < self.MAX_REFLOW_ATTEMPTS:
            left_w = max((n['box_w'] for n in processed_l), default=200)
            right_w = max((n['box_w'] for n in processed_r), default=200)
            canvas_w = max(900, left_w + right_w + col_gap + self.MARGIN * 3)
            left_h = sum(n['box_h'] for n in processed_l) + max(0, len(processed_l) - 1) * row_gap
            right_h = sum(n['box_h'] for n in processed_r) + max(0, len(processed_r) - 1) * row_gap
            canvas_h = max(left_h, right_h) + self.MARGIN * 2 + 90

            img = Image.new('RGB', (canvas_w, canvas_h), 'white')
            draw = ImageDraw.Draw(img)
            elements = []
            lboxes: dict[str, tuple[int, int, int, int]] = {}
            rboxes: dict[str, tuple[int, int, int, int]] = {}

            # Left column (training)
            lx = self.MARGIN
            ly = self.MARGIN + 50
            for pn in processed_l:
                self._draw_node_content(img, draw, pn, lx, ly, main_font, elements, pn['id'], 'left')
                lboxes[pn['id']] = (lx, ly, lx + pn['box_w'], ly + pn['box_h'])
                ly += pn['box_h'] + row_gap

            # Right column (generation)
            rx = canvas_w - self.MARGIN - right_w
            ry = self.MARGIN + 50
            for pn in processed_r:
                self._draw_node_content(img, draw, pn, rx, ry, main_font, elements, pn['id'], 'right')
                rboxes[pn['id']] = (rx, ry, rx + pn['box_w'], ry + pn['box_h'])
                ry += pn['box_h'] + row_gap

            boxes = {**lboxes, **rboxes}
            # Within-column edges: straight arrows
            for edge in edges:
                src, tgt = getattr(edge, 'source', ''), getattr(edge, 'target', '')
                if src in boxes and tgt in boxes:
                    in_same_col = (src in lboxes and tgt in lboxes) or (src in rboxes and tgt in rboxes)
                    if in_same_col:
                        self._draw_straight_arrow(draw, boxes[src], boxes[tgt], elements, src, tgt)
                    elif getattr(edge, 'label', ''):
                        # Cross-column bridge routed through the inter-column gap
                        gap_mid_x = (self.MARGIN + left_w + rx) // 2
                        self._draw_bridge_arrow(draw, boxes[src], boxes[tgt], gap_mid_x,
                                                elements, src, tgt, edge.label, small_font)

            # Title
            tb = temp.textbbox((0, 0), figure.title, font=small_font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            draw.text(((canvas_w - tw) // 2, 14), figure.title, fill='black', font=small_font)
            report.title_bbox = [(canvas_w - tw) // 2, 14, tw, th]
            report.canvas = {'w': canvas_w, 'h': canvas_h}
            report.elements = elements
            report.collisions = detector.detect(elements)
            attempts += 1
            report.reflow_attempts = attempts
            if not report.collisions:
                break
            if attempts % 3 == 0:
                col_gap = min(col_gap + 30, 140)
            row_gap = min(row_gap + 14, 110)

        return self._write_outputs(figure, img, report, output_dir)

    # ── Branch-merge layout (Fig.4) ────────────────────────────

    def _render_branch_merge(self, figure, output_dir: Path):
        main_font, small_font, temp = self._setup_fonts()
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        processed = [self._measure_node(n, main_font, temp) for n in nodes]

        input_gap = 36
        row_gap = 50
        elements: list[LayoutElement] = []
        detector = CollisionDetector(pad=2.0)
        attempts = 0
        report = LayoutReport(figure_id=figure.id, number=figure.number, layout='branch_merge')

        while attempts < self.MAX_REFLOW_ATTEMPTS:
            n = len(processed)
            cx = 0
            if n >= 4:
                inputs_w = processed[0]['box_w'] + processed[1]['box_w'] + input_gap
                merge_w = processed[2]['box_w']
                output_w = processed[3]['box_w']
                canvas_w = max(900, inputs_w, merge_w, output_w) + self.MARGIN * 2
                cx = canvas_w // 2
                input_h = max(processed[0]['box_h'], processed[1]['box_h'])
                canvas_h = (self.MARGIN + 50 + input_h + row_gap + processed[2]['box_h']
                            + row_gap + processed[3]['box_h'] + self.MARGIN + 40)
            else:
                canvas_w, canvas_h = 900, 800
                cx = canvas_w // 2

            img = Image.new('RGB', (canvas_w, canvas_h), 'white')
            draw = ImageDraw.Draw(img)
            elements = []
            boxes: dict[str, tuple[int, int, int, int]] = {}
            y = self.MARGIN + 50

            if n >= 2:
                left_w = processed[0]['box_w']
                left_x = cx - left_w - input_gap // 2
                right_x = cx + input_gap // 2
                for idx, (pn, x) in enumerate([(processed[0], left_x), (processed[1], right_x)]):
                    self._draw_node_content(img, draw, pn, x, y, main_font, elements, pn['id'], 'input')
                    boxes[pn['id']] = (x, y, x + pn['box_w'], y + pn['box_h'])
                y += max(processed[0]['box_h'], processed[1]['box_h']) + row_gap
            if n >= 3:
                mx = cx - processed[2]['box_w'] // 2
                self._draw_node_content(img, draw, processed[2], mx, y, main_font, elements, processed[2]['id'], 'center')
                boxes[processed[2]['id']] = (mx, y, mx + processed[2]['box_w'], y + processed[2]['box_h'])
                y += processed[2]['box_h'] + row_gap
            if n >= 4:
                ox = cx - processed[3]['box_w'] // 2
                self._draw_node_content(img, draw, processed[3], ox, y, main_font, elements, processed[3]['id'], 'output')
                boxes[processed[3]['id']] = (ox, y, ox + processed[3]['box_w'], y + processed[3]['box_h'])

            # Edges: inputs -> merge (elbow), merge -> output (straight)
            for edge in edges:
                src, tgt = getattr(edge, 'source', ''), getattr(edge, 'target', '')
                if src not in boxes or tgt not in boxes:
                    continue
                s, t = boxes[src], boxes[tgt]
                if s[0] == t[0] and s[1] == t[1]:
                    continue
                if abs((s[0] + s[2]) // 2 - (t[0] + t[2]) // 2) > 5:
                    self._draw_elbow_arrow(draw, s, t, elements, src, tgt)
                else:
                    self._draw_straight_arrow(draw, s, t, elements, src, tgt)

            # Title
            tb = temp.textbbox((0, 0), figure.title, font=small_font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            draw.text(((canvas_w - tw) // 2, 14), figure.title, fill='black', font=small_font)
            report.title_bbox = [(canvas_w - tw) // 2, 14, tw, th]
            report.canvas = {'w': canvas_w, 'h': canvas_h}
            report.elements = elements
            report.collisions = detector.detect(elements)
            attempts += 1
            report.reflow_attempts = attempts
            if not report.collisions:
                break
            if attempts % 3 == 0:
                input_gap = min(input_gap + 30, 160)
            row_gap = min(row_gap + 18, 130)

        return self._write_outputs(figure, img, report, output_dir)

    # ── Arrow helpers (record per-segment bboxes for collision detection) ──

    @staticmethod
    def _record_arrow(elements: list[LayoutElement], segs: list[tuple[float, float, float, float]], src: str, tgt: str) -> None:
        """Record one arrow LayoutElement per line segment.

        Each segment bbox is padded by 1px (line width 2) so zero-width
        segments still count, while boundary-touching endpoints don't.
        """
        for (x1, y1, x2, y2) in segs:
            bx = min(x1, x2)
            by = min(y1, y2)
            bw = abs(x2 - x1) + 2
            bh = abs(y2 - y1) + 2
            elements.append(LayoutElement('arrow', BBox(bx - 1, by - 1, bw, bh),
                                          node_id=f"{src}->{tgt}"))

    def _draw_straight_arrow(self, draw, s, t, elements, src, tgt):
        sx = (s[0] + s[2]) // 2
        sy = s[3]
        tx = (t[0] + t[2]) // 2
        ty = t[1]
        draw.line([(sx, sy), (sx, ty - 8)], fill='black', width=2)
        arr = 8
        draw.polygon([(tx, ty), (tx - arr, ty - arr * 2), (tx + arr, ty - arr * 2)], fill='black')
        self._record_arrow(elements, [(sx, sy, sx, ty)], src, tgt)

    def _draw_elbow_arrow(self, draw, s, t, elements, src, tgt):
        sx = (s[0] + s[2]) // 2
        sy = s[3]
        tx = (t[0] + t[2]) // 2
        ty = t[1]
        mid_y = (sy + ty) // 2
        draw.line([(sx, sy), (sx, mid_y), (tx, mid_y), (tx, ty - 8)], fill='black', width=2)
        arr = 8
        draw.polygon([(tx, ty), (tx - arr, ty - arr * 2), (tx + arr, ty - arr * 2)], fill='black')
        self._record_arrow(elements, [(sx, sy, sx, mid_y), (sx, mid_y, tx, mid_y), (tx, mid_y, tx, ty)], src, tgt)

    def _draw_bridge_arrow(self, draw, s, t, gap_mid_x, elements, src, tgt, label, small_font):
        """Cross-column edge routed through the inter-column gap.

        Path: source right edge -> gap -> vertical in gap -> target left edge.
        Each segment is recorded separately so the arrow bbox never spans
        whole columns (no false collisions).
        """
        s_cy = (s[1] + s[3]) // 2
        t_cy = (t[1] + t[3]) // 2
        s_rx = s[2]
        t_lx = t[0]
        draw.line([(s_rx, s_cy), (gap_mid_x, s_cy)], fill='black', width=2)
        draw.line([(gap_mid_x, s_cy), (gap_mid_x, t_cy)], fill='black', width=2)
        draw.line([(gap_mid_x, t_cy), (t_lx - 6, t_cy)], fill='black', width=2)
        arr = 8
        draw.polygon([(t_lx, t_cy), (t_lx - arr, t_cy - arr), (t_lx - arr, t_cy + arr)], fill='black')
        self._record_arrow(elements, [
            (s_rx, s_cy, gap_mid_x, s_cy),
            (gap_mid_x, s_cy, gap_mid_x, t_cy),
            (gap_mid_x, t_cy, t_lx, t_cy),
        ], src, tgt)
        if label:
            tb = small_font.getbbox(label) or (0, 0, 0, 0)
            lw, lh = tb[2] - tb[0], tb[3] - tb[1]
            lx = gap_mid_x - lw // 2
            ly = t_cy - lh - 8
            if ly < s_cy and s_cy - ly < lh + 4:
                ly = s_cy + 6
            draw.text((lx, ly), label, fill='black', font=small_font)
            elements.append(LayoutElement('text', BBox(lx, ly, lw, lh), node_id=f"{src}->{tgt}", content=label, column='bridge'))
