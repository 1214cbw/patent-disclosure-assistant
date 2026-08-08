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

        # ── Source figure: just resize and use ──
        source_png = getattr(figure, 'png_path', '') or ''
        if source_png and Path(source_png).exists() and len(nodes) <= 1 and not edges:
            return self._render_source_figure(figure, output_dir)

        # ── Detect layout type from edges pattern ──
        layout = self._detect_layout(nodes, edges)
        if layout == 'branch_merge':
            return self._render_branch_merge(figure, output_dir)
        elif layout == 'two_column':
            return self._render_two_column(figure, output_dir)
        else:
            return self._render_vertical(figure, output_dir)

    def _render_source_figure(self, figure, output_dir: Path):
        """Simply copy and resize a source PNG as the figure."""
        from PIL import Image as PILImage
        src_path = Path(figure.png_path)
        img = PILImage.open(src_path)

        # Scale to reasonable width for Word (max 1400px)
        max_w = 1400
        if img.size[0] > max_w:
            ratio = max_w / img.size[0]
            img = img.resize((max_w, int(img.size[1] * ratio)), PILImage.LANCZOS)

        # Add title as top margin
        title = getattr(figure, 'title', '')
        title_h = 60 if title else 0
        canvas = PILImage.new('RGB', (img.size[0], img.size[1] + title_h), 'white')
        if title:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            small_font = _get_chinese_font(18)
            bbox = draw.textbbox((0, 0), title, font=small_font)
            tw = bbox[2] - bbox[0]
            draw.text(((canvas.size[0] - tw) // 2, 16), title, fill='black', font=small_font)
        canvas.paste(img, (0, title_h))

        png_path = output_dir / f"figure_{figure.number:02d}.png"
        canvas.save(png_path, dpi=(300, 300))

        # Minimal SVG wrapper
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas.size[0]}" height="{canvas.size[1]}">'
            f'<image href="{src_path.name}" width="{img.size[0]}" height="{img.size[1]}" x="0" y="{title_h}"/>'
            f'</svg>', encoding='utf-8')

        return figure.model_copy(update={'png_path': str(png_path), 'svg_path': str(svg_path)})

    @staticmethod
    def _detect_layout(nodes, edges) -> str:
        """Detect layout type from edge connections."""
        if not edges:
            return 'vertical'

        # Build adjacency
        targets = set()
        sources = set()
        for e in edges:
            src = getattr(e, 'source', '')
            tgt = getattr(e, 'target', '')
            sources.add(src)
            targets.add(tgt)

        # Branch-merge: multiple nodes feed into one node
        in_degree = {}
        for e in edges:
            tgt = getattr(e, 'target', '')
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

        if any(d >= 2 for d in in_degree.values()):
            return 'branch_merge'

        # Two-column: check if there's a clear column break (edge with label bridging columns)
        bridge_edges = [e for e in edges if getattr(e, 'label', '')]
        if bridge_edges and len(nodes) >= 8:
            return 'two_column'

        return 'vertical'

    def _render_branch_merge(self, figure, output_dir: Path):
        """Render branch-merge layout (Fig.4 style)."""
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        main_font = _get_chinese_font(self.FONT_SIZE)
        small_font = _get_chinese_font(16)

        from PIL import Image, ImageDraw
        temp = ImageDraw.Draw(Image.new('RGB', (1, 1), 'white'))
        global _chinese_body_height
        cn_bbox = temp.textbbox((0, 0), "中", font=main_font)
        _chinese_body_height = cn_bbox[3] - cn_bbox[1]
        mr = _get_math_renderer()
        mr.set_chinese_height(_chinese_body_height)

        # Compute node sizes
        processed = []
        for node in nodes:
            label = getattr(node, 'label', str(node))
            segs = _parse_label(label)
            w, h = self._measure_segments(segs, main_font, temp)
            box_w = max(self.MIN_BOX_WIDTH, w + self.H_PADDING * 2)
            box_h = max(self.MIN_BOX_HEIGHT, h + self.V_PADDING * 2)
            processed.append({'id': getattr(node, 'id', ''), 'segs': segs, 'box_w': box_w, 'box_h': box_h})

        # Layout: inputs side by side -> merge node -> output
        # I1 I2 -> I3 -> I4
        n = len(processed)
        if n >= 4:
            # Two inputs side by side
            input_w = processed[0]['box_w'] + processed[1]['box_w'] + 60
            merge_w = processed[2]['box_w']
            output_w = processed[3]['box_w'] if n > 3 else merge_w

            canvas_w = max(input_w, merge_w, output_w) + self.MARGIN * 2
            canvas_w = max(800, canvas_w)

            # Vertical positioning
            input_h = max(processed[0]['box_h'], processed[1]['box_h'])
            gap = 50
            canvas_h = self.MARGIN + input_h + gap + processed[2]['box_h'] + gap
            if n > 3:
                canvas_h += processed[3]['box_h'] + gap
            canvas_h += self.MARGIN + 60
        else:
            canvas_w = 900
            canvas_h = 800

        img = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)

        # Position nodes
        cx = canvas_w // 2
        y = self.MARGIN + 40
        boxes = {}

        # Input nodes side by side
        if n >= 2:
            left_x = cx - processed[0]['box_w'] - 30
            right_x = cx + 30
            for i in [0, 1]:
                x = left_x if i == 0 else right_x
                self._draw_node(draw, img, processed[i], x, y, cx, main_font, temp)
                boxes[processed[i]['id']] = (x, y, x + processed[i]['box_w'], y + processed[i]['box_h'])
            y += max(processed[0]['box_h'], processed[1]['box_h']) + gap

        # Merge node
        if n >= 3:
            mx = cx - processed[2]['box_w'] // 2
            self._draw_node(draw, img, processed[2], mx, y, cx, main_font, temp)
            boxes[processed[2]['id']] = (mx, y, mx + processed[2]['box_w'], y + processed[2]['box_h'])
            y += processed[2]['box_h'] + gap

        # Output node
        if n >= 4:
            ox = cx - processed[3]['box_w'] // 2
            self._draw_node(draw, img, processed[3], ox, y, cx, main_font, temp)
            boxes[processed[3]['id']] = (ox, y, ox + processed[3]['box_w'], y + processed[3]['box_h'])

        # Draw edges (branch-merge)
        for edge in edges:
            src_id = getattr(edge, 'source', '')
            tgt_id = getattr(edge, 'target', '')
            if src_id not in boxes or tgt_id not in boxes:
                continue
            s = boxes[src_id]
            t = boxes[tgt_id]
            sx = (s[0] + s[2]) // 2
            sy = s[3]
            tx = (t[0] + t[2]) // 2
            ty = t[1]
            # Elbow connector
            mid_y = (sy + ty) // 2
            draw.line([(sx, sy), (sx, mid_y), (tx, mid_y), (tx, ty - 8)], fill='black', width=2)
            # Arrowhead
            arr = 8
            draw.polygon([(tx, ty), (tx - arr, ty - arr*2), (tx + arr, ty - arr*2)], fill='black')

        # Title
        title = getattr(figure, 'title', '')
        if title:
            tb = temp.textbbox((0, 0), title, font=small_font)
            draw.text((cx - (tb[2]-tb[0])//2, 14), title, fill='black', font=small_font)

        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300, 300))
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text(self._make_svg(figure, processed, boxes, canvas_w, canvas_h, cx), encoding='utf-8')
        return figure.model_copy(update={'png_path': str(png_path), 'svg_path': str(svg_path)})

    def _render_two_column(self, figure, output_dir: Path):
        """Render two-column layout (Fig.3 training/generation side by side)."""
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        main_font = _get_chinese_font(self.FONT_SIZE)
        small_font = _get_chinese_font(16)

        from PIL import Image, ImageDraw
        temp = ImageDraw.Draw(Image.new('RGB', (1, 1), 'white'))
        global _chinese_body_height
        cn_bbox = temp.textbbox((0, 0), "中", font=main_font)
        _chinese_body_height = cn_bbox[3] - cn_bbox[1]
        mr = _get_math_renderer()
        mr.set_chinese_height(_chinese_body_height)

        # Split nodes into left and right columns
        # Training side: first half, Generation side: second half
        mid = len(nodes) // 2
        left_nodes = nodes[:mid]
        right_nodes = nodes[mid:]

        processed_l = [self._process_node(n, main_font, temp) for n in left_nodes]
        processed_r = [self._process_node(n, main_font, temp) for n in right_nodes]

        col_gap = 60
        left_w = max(n['box_w'] for n in processed_l) if processed_l else 200
        right_w = max(n['box_w'] for n in processed_r) if processed_r else 200
        canvas_w = max(1000, left_w + right_w + col_gap + self.MARGIN * 3)

        left_h = sum(n['box_h'] for n in processed_l) + max(0, len(processed_l)-1) * 40
        right_h = sum(n['box_h'] for n in processed_r) + max(0, len(processed_r)-1) * 40
        canvas_h = max(left_h, right_h) + self.MARGIN * 2 + 80

        img = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)
        cx = canvas_w // 2

        # Left column
        lx = self.MARGIN
        ly = self.MARGIN + 50
        lboxes = {}
        for pn in processed_l:
            self._draw_node(draw, img, pn, lx, ly, lx + pn['box_w']//2, main_font, temp)
            lboxes[pn['id']] = (lx, ly, lx + pn['box_w'], ly + pn['box_h'])
            ly += pn['box_h'] + 40

        # Right column
        rx = canvas_w // 2 + col_gap // 2
        ry = self.MARGIN + 50
        rboxes = {}
        for pn in processed_r:
            self._draw_node(draw, img, pn, rx, ry, rx + pn['box_w']//2, main_font, temp)
            rboxes[pn['id']] = (rx, ry, rx + pn['box_w'], ry + pn['box_h'])
            ry += pn['box_h'] + 40

        boxes = {**lboxes, **rboxes}

        # Draw internal edges within each column
        for edge in edges:
            src_id = getattr(edge, 'source', '')
            tgt_id = getattr(edge, 'target', '')
            if src_id in lboxes and tgt_id in lboxes:
                self._draw_arrow(draw, boxes, src_id, tgt_id)
            elif src_id in rboxes and tgt_id in rboxes:
                self._draw_arrow(draw, boxes, src_id, tgt_id)
            elif src_id in lboxes and tgt_id in rboxes:
                # Bridging edge: draw curved connector
                s, t = boxes[src_id], boxes[tgt_id]
                sx, sy = (s[0]+s[2])//2, s[3]
                tx, ty = (t[0]+t[2])//2, t[1]
                mid_x = (sx + tx) // 2
                draw.line([(sx, sy), (sx, sy+20), (mid_x, sy+20), (mid_x, ty-20), (tx, ty-20), (tx, ty-8)], fill='black', width=2)
                arr = 8
                draw.polygon([(tx, ty), (tx-arr, ty-arr*2), (tx+arr, ty-arr*2)], fill='black')
                # Label
                elabel = getattr(edge, 'label', '')
                if elabel:
                    tb = temp.textbbox((0,0), elabel[:30], font=small_font)
                    draw.text((mid_x - (tb[2]-tb[0])//2, sy+24), elabel[:30], fill='black', font=small_font)

        title = getattr(figure, 'title', '')
        if title:
            tb = temp.textbbox((0,0), title, font=small_font)
            draw.text((cx-(tb[2]-tb[0])//2, 14), title, fill='black', font=small_font)

        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300,300))
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text(self._make_svg(figure, processed_l+processed_r, boxes, canvas_w, canvas_h, cx), encoding='utf-8')
        return figure.model_copy(update={'png_path': str(png_path), 'svg_path': str(svg_path)})

    def _render_vertical(self, figure, output_dir: Path):
        """Standard vertical layout (existing code path)."""
        nodes = figure.nodes
        edges = figure.edges if hasattr(figure, 'edges') else []
        main_font = _get_chinese_font(self.FONT_SIZE)
        small_font = _get_chinese_font(16)
        from PIL import Image, ImageDraw
        temp = ImageDraw.Draw(Image.new('RGB', (1, 1), 'white'))
        global _chinese_body_height
        cn_bbox = temp.textbbox((0, 0), "中", font=main_font)
        _chinese_body_height = cn_bbox[3] - cn_bbox[1]
        mr = _get_math_renderer()
        mr.set_chinese_height(_chinese_body_height)

        processed = [self._process_node(n, main_font, temp) for n in nodes]
        canvas_w = max(800, max(n['box_w'] for n in processed) + self.MARGIN * 3)
        total_h = sum(n['box_h'] for n in processed) + max(0, len(processed)-1) * self.NODE_GAP
        canvas_h = self.MARGIN * 2 + total_h + 80
        cx = canvas_w // 2

        img = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)
        boxes = {}
        y = self.MARGIN + 50
        for pn in processed:
            x = cx - pn['box_w'] // 2
            self._draw_node(draw, img, pn, x, y, cx, main_font, temp)
            boxes[pn['id']] = (x, y, x + pn['box_w'], y + pn['box_h'])
            y += pn['box_h'] + self.NODE_GAP

        for edge in edges:
            self._draw_arrow(draw, boxes, getattr(edge,'source',''), getattr(edge,'target',''))

        title = getattr(figure, 'title', '')
        if title:
            tb = temp.textbbox((0,0), title, font=small_font)
            draw.text((cx-(tb[2]-tb[0])//2, 14), title, fill='black', font=small_font)

        png_path = output_dir / f"figure_{figure.number:02d}.png"
        img.save(png_path, dpi=(300,300))
        svg_path = output_dir / f"figure_{figure.number:02d}.svg"
        svg_path.write_text(self._make_svg(figure, processed, boxes, canvas_w, canvas_h, cx), encoding='utf-8')
        return figure.model_copy(update={'png_path': str(png_path), 'svg_path': str(svg_path)})

    # ── Helpers ──

    def _process_node(self, node, font, draw):
        label = getattr(node, 'label', str(node))
        segs = _parse_label(label)
        w, h = self._measure_segments(segs, font, draw)
        return {'id': getattr(node, 'id', ''), 'segs': segs,
                'box_w': max(self.MIN_BOX_WIDTH, w + self.H_PADDING * 2),
                'box_h': max(self.MIN_BOX_HEIGHT, h + self.V_PADDING * 2)}

    def _measure_segments(self, segs, font, draw):
        total_h, max_w = 0, self.MIN_BOX_WIDTH
        for typ, content in segs:
            if typ == 'text':
                for line in content.split('\n'):
                    bbox = draw.textbbox((0,0), line, font=font)
                    max_w = max(max_w, bbox[2]-bbox[0]+10)
                    total_h += bbox[3]-bbox[1]+8
            else:
                mr = _get_math_renderer()
                img = mr.render_latex(content)
                if img:
                    max_w = max(max_w, img.size[0]+10)
                    total_h += img.size[1]+4
        return max_w, total_h

    def _draw_node(self, draw, img, pn, x, y, cx, font, temp_draw):
        x2, y2 = x + pn['box_w'], y + pn['box_h']
        draw.rectangle((x, y, x2, y2), outline='black', width=2, fill='white')
        seg_y = y + self.V_PADDING
        mr = _get_math_renderer()
        for typ, content in pn['segs']:
            if typ == 'text':
                for line in content.split('\n'):
                    if not line.strip(): seg_y += 8; continue
                    bbox = temp_draw.textbbox((0,0), line, font=font)
                    lw = bbox[2]-bbox[0]
                    lx = cx - lw//2
                    draw.text((lx, seg_y), line, fill='black', font=font)
                    seg_y += bbox[3]-bbox[1]+8
            else:
                math_img = mr.render_latex(content)
                if math_img:
                    mx = cx - math_img.size[0]//2
                    if mx < x+4: mx = x+4
                    img.paste(math_img, (mx, int(seg_y)), math_img)
                    seg_y += math_img.size[1]+4

    @staticmethod
    def _draw_arrow(draw, boxes, src_id, tgt_id):
        if src_id not in boxes or tgt_id not in boxes: return
        s, t = boxes[src_id], boxes[tgt_id]
        sx = (s[0]+s[2])//2; sy = s[3]
        tx = (t[0]+t[2])//2; ty = t[1]
        draw.line([(sx, sy), (sx, ty-8)], fill='black', width=2)
        arr = 8
        draw.polygon([(sx, ty), (sx-arr, ty-arr*2), (sx+arr, ty-arr*2)], fill='black')

    @staticmethod
    def _make_svg(figure, processed, boxes, w, h, cx):
        from html import escape
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<defs><marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">',
            '<polygon points="0 0, 10 3.5, 0 7" fill="black"/></marker></defs>']
        t = getattr(figure, 'title', '')
        if t: parts.append(f'<text x="{cx}" y="24" text-anchor="middle" font-family="Microsoft YaHei" font-size="16">{escape(t)}</text>')
        for pn in processed:
            bid = pn['id']
            if bid in boxes:
                x1,y1,x2,y2 = boxes[bid]
                parts.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="white" stroke="black" stroke-width="2"/>')
        parts.append('</svg>')
        return '\n'.join(parts)

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
