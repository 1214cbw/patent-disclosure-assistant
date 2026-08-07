from __future__ import annotations

from html import escape
from pathlib import Path
import textwrap
from PIL import Image, ImageDraw, ImageFont

from patent_agent.core.models import FigureSpec


def _font(size: int):
    for candidate in (Path(r"C:\Windows\Fonts\msyh.ttc"), Path(r"C:\Windows\Fonts\simhei.ttf"), Path(r"C:\Windows\Fonts\simsun.ttc")):
        if candidate.exists(): return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _wrap_label(label: str, width: int = 23) -> list[str]:
    return textwrap.wrap(
        label,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [label]


class PatentFigureRenderer:
    def render(self, figure: FigureSpec, output_dir: Path) -> FigureSpec:
        output_dir.mkdir(parents=True, exist_ok=True)
        width, box_h, gap, margin = 900, 108, 56, 60
        height = margin * 2 + len(figure.nodes) * box_h + max(0, len(figure.nodes) - 1) * gap
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        font = _font(26); small = _font(20)
        boxes = {}
        for index, node in enumerate(figure.nodes):
            y = margin + index * (box_h + gap)
            box = (120, y, width - 120, y + box_h); boxes[node.id] = box
            draw.rectangle(box, outline="black", width=3)
            label = "\n".join(_wrap_label(node.label))
            bbox = draw.multiline_textbbox((0, 0), label, font=font, spacing=8, align="center")
            draw.multiline_text(
                ((width - (bbox[2]-bbox[0]))/2, y + (box_h - (bbox[3]-bbox[1]))/2 - 4),
                label,
                fill="black",
                font=font,
                spacing=8,
                align="center",
            )
        for edge in figure.edges:
            if edge.source not in boxes or edge.target not in boxes: continue
            src, dst = boxes[edge.source], boxes[edge.target]
            x = width // 2; y1 = src[3]; y2 = dst[1]
            draw.line((x, y1, x, y2 - 10), fill="black", width=3)
            draw.polygon([(x, y2), (x-9, y2-14), (x+9, y2-14)], fill="black")
            if edge.label: draw.text((x + 12, (y1+y2)//2), edge.label, fill="black", font=small)
        png = output_dir / f"figure_{figure.number:02d}.png"; image.save(png, dpi=(300, 300))
        svg = output_dir / f"figure_{figure.number:02d}.svg"
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>', '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="black"/></marker></defs>']
        for node in figure.nodes:
            x1,y1,x2,y2=boxes[node.id]
            lines = _wrap_label(node.label)
            line_height = 34
            first_y = (y1+y2)/2 - ((len(lines)-1) * line_height)/2 + 9
            tspans = "".join(
                f'<tspan x="{width/2}" y="{first_y + index * line_height}">{escape(line)}</tspan>'
                for index, line in enumerate(lines)
            )
            parts += [f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="white" stroke="black" stroke-width="3"/>', f'<text text-anchor="middle" font-family="Microsoft YaHei, SimSun" font-size="26">{tspans}</text>']
        for edge in figure.edges:
            if edge.source in boxes and edge.target in boxes:
                src,dst=boxes[edge.source],boxes[edge.target]; parts.append(f'<line x1="{width/2}" y1="{src[3]}" x2="{width/2}" y2="{dst[1]-5}" stroke="black" stroke-width="3" marker-end="url(#arrow)"/>')
        parts.append("</svg>"); svg.write_text("\n".join(parts), encoding="utf-8")
        return figure.model_copy(update={"png_path": str(png), "svg_path": str(svg)})
