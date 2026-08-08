"""SourceFigureContentCropper V6.7 - content-aware crop of figures from source PDFs.

Pipeline:

  PDF candidate region
    -> content bbox analysis (vector drawings vs prose text vs caption)
    -> figure content bbox
    -> margin expansion
    -> high-DPI clip render + PIL ink bbox trim
    -> crop

The cropper never trusts a predefined rectangle alone: it locates the
figure body via vector drawings, then excludes surrounding prose (above)
and the original English caption (below) using the PDF text layer, so the
crop cannot silently include text that visually belongs to the document
body instead of the figure.

Golden crops (manually verified regions) are stored in a registry and
used as the primary source when available; the analyzer path still runs
and validates the golden region.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import fitz  # PyMuPDF

from patent_agent.document.figure_layout import BBox


@dataclass
class CropResult:
    png_path: str
    source_pdf: str
    source_page: int
    bbox_pt: list[float]      # crop rect in PDF points
    content_bbox_pt: list[float]  # figure body bbox (pre-margin)
    method: str               # "content_bbox" | "golden"
    size_px: list[int]
    margin_pt: float

    def to_dict(self) -> dict:
        return asdict(self)


# Golden crops verified manually: page index (0-based), column-relative
# candidate rect (x0, y0, x1, y1) in PDF points.
GOLDEN_CROPS: dict[str, dict] = {
    # REAL-PAPER-001 Fig.2 "Annotation of design variables for the
    # first-layer magnetic barrier" (paper page 2, left column).
    # Verified row-level ink analysis: body prose lines end at y=376.9,
    # figure vector cluster spans y[391.9-525.0] x[66.7-287.6] (46
    # drawings, incl. the in-figure hbs1 label at y[477-491]), original
    # English caption "Fig. 2. Annotation..." starts at y=536.2.
    "REAL-PAPER-001:2:fig2": {
        "page": 1,
        "candidate": [55.0, 380.0, 300.0, 540.0],
        "margin_pt": 6.0,
    },
}


class SourceFigureContentCropper:
    """Crop a figure out of a source PDF, excluding surrounding text."""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)

    @staticmethod
    def _dense_cluster_bbox(drawings: list) -> fitz.Rect:
        """BBox of the densest consecutive y-range of vector content.

        Scans 15pt y-bins; keeps bins with >= 2 drawings and merges runs
        separated by <= 1 empty bin. Returns the union bbox of the densest
        run (by drawing count).
        """
        if not drawings:
            return fitz.Rect(0, 0, 0, 0)
        from collections import Counter
        bins = Counter()
        for r in drawings:
            bins[round(r.y0 / 15)] += 1
        runs: list[list[int]] = []
        cur: list[int] = []
        for k in sorted(bins):
            if bins[k] < 2:
                if cur and k - cur[-1] > 2:  # gap > 1 bin ends the run
                    runs.append(cur)
                    cur = []
                continue
            if cur and k - cur[-1] > 2:
                runs.append(cur)
                cur = []
            cur.append(k)
        if cur:
            runs.append(cur)
        if not runs:
            return fitz.Rect(0, 0, 0, 0)
        best = max(runs, key=lambda run: sum(bins[k] for k in run))
        y0 = best[0] * 15
        y1 = (best[-1] + 1) * 15
        in_run = [r for r in drawings if y0 <= r.y0 < y1]
        bbox = in_run[0]
        for r in in_run[1:]:
            bbox |= r
        return bbox

    # ── analysis ────────────────────────────────────────────────

    def analyze_page(self, page_index: int, candidate: list[float]) -> dict:
        """Content bbox analysis of a candidate region.

        Returns {drawing_bbox_pt, prose_bbox_pt, caption_bbox_pt} so the
        caller can see exactly what surrounds the figure.
        """
        doc = fitz.open(str(self.pdf_path))
        try:
            page = doc[page_index]
            rect = fitz.Rect(*candidate)
            # vector content = the figure body (patent figures are vector-drawn).
            # Isolate the dense cluster: decorative rules (page headers,
            # section underlines) are sparse, the figure body is dense.
            drawings = [d["rect"] for d in page.get_drawings()
                        if d["rect"].intersects(rect) and d["rect"].width > 0.5]
            drawing_bbox = self._dense_cluster_bbox(drawings)
            # text layer inside the candidate region, split into
            # "prose" (blocks that span most of the column width) and
            # "captions" (blocks whose text mentions a figure marker).
            # NOTE: use full-page blocks then filter by y, because a clip
            # can cut the first letters of a caption ("Fig." -> "g 2").
            blocks = page.get_text("blocks")
            prose: list[tuple[float, float, float, float]] = []
            captions: list[tuple[float, float, float, float]] = []
            for b in blocks:
                if not b[4].strip():
                    continue
                by0, by1 = b[1], b[3]
                if by1 < rect.y0 or by0 > rect.y1:
                    continue  # outside candidate y-range
                bw = b[2] - b[0]
                text = b[4].strip()
                if re.match(r"^\s*(Fig|Figure)\s*\.?\s*\d", text):
                    captions.append((b[0], b[1], b[2], b[3]))
                elif bw > (rect.x1 - rect.x0) * 0.4:
                    # wide block => body text line, not an in-figure label
                    prose.append((b[0], b[1], b[2], b[3]))
            # word-level ink bottom: the lowest BODY-TEXT line above the
            # figure. Block bboxes wrap around the figure and span other
            # columns, and drawing bboxes may include leader lines that start
            # inside the prose, so classify lines instead: a body-text line
            # is >= 3 words spanning > 60pt. In-figure labels (e.g. "hbs1")
            # are single narrow words and never qualify.
            prose_ink_bottom: float | None = None
            draw_y0, draw_y1 = drawing_bbox.y0, drawing_bbox.y1
            if drawing_bbox.height > 0:
                by_row: dict[int, list] = {}
                for w in page.get_text("words"):
                    if w[0] >= rect.x1 or w[1] > draw_y1:
                        continue  # other column / below the figure body
                    by_row.setdefault(round(w[1] / 4) * 4, []).append(w)
                for y, ws in by_row.items():
                    if len(ws) < 3:
                        continue
                    xspan = max(w[2] for w in ws) - min(w[0] for w in ws)
                    if xspan <= 60:
                        continue  # in-figure label, not a prose line
                    bottom = max(w[3] for w in ws)
                    if prose_ink_bottom is None or bottom > prose_ink_bottom:
                        prose_ink_bottom = bottom
            return {
                "drawing_bbox_pt": list(drawing_bbox),
                "prose_bbox_pt": prose,
                "prose_ink_bottom_pt": prose_ink_bottom,
                "caption_bbox_pt": captions,
            }
        finally:
            doc.close()

    def figure_bbox(self, page_index: int, candidate: list[float],
                    margin_pt: float) -> tuple[list[float], str]:
        """Figure content bbox = drawing bbox + margin, clamped to exclude
        prose above and original caption below.

        Prose blocks may wrap around the figure (paragraph bbox can span the
        whole column including the figure zone), so only blocks entirely
        ABOVE the drawing body are treated as residue to remove.
        """
        analysis = self.analyze_page(page_index, candidate)
        db = analysis["drawing_bbox_pt"]
        if not db or db[2] - db[0] <= 0 or db[3] - db[1] <= 0:
            raise ValueError(f"no vector figure content found in candidate {candidate}")
        draw_y0, draw_y1 = db[1], db[3]
        x0, y0, x1, y1 = db
        x0 -= margin_pt
        y0 -= margin_pt
        x1 += margin_pt
        y1 += margin_pt
        # clamp: never extend into the original caption line
        if analysis["caption_bbox_pt"]:
            cap_y0 = min(c[1] for c in analysis["caption_bbox_pt"])
            y1 = min(y1, cap_y0 - 1.0)
        # clamp: never extend into body-text words entirely above the drawing.
        # (word-level, not block-level: blocks wrap around the figure and
        # would push y0 below the figure body, producing an inverted rect)
        ink_bottom = analysis.get("prose_ink_bottom_pt")
        if ink_bottom:
            y0 = max(y0, ink_bottom + 1.0)
        return [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)], "content_bbox"

    # ── crop ────────────────────────────────────────────────────

    def crop(self, page_index: int, bbox_pt: list[float], *,
             dpi: int = 300, output: str | Path) -> CropResult:
        """Clip-render the bbox at high DPI and trim to ink content."""
        doc = fitz.open(str(self.pdf_path))
        try:
            page = doc[page_index]
            rect = fitz.Rect(*bbox_pt)
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=rect)
            img = _pil_from(pix)
            # The clip already carries the margin expansion; a tiny trim pad
            # only absorbs anti-aliasing edge noise.
            trimmed = _trim_white(img, pad_px=6)
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            trimmed.save(out_path)
            return CropResult(
                png_path=str(out_path),
                source_pdf=str(self.pdf_path),
                source_page=page_index + 1,  # 1-based for provenance
                bbox_pt=[round(v, 1) for v in bbox_pt],
                content_bbox_pt=[],
                method="content_bbox",
                size_px=[trimmed.width, trimmed.height],
                margin_pt=12.0,
            )
        finally:
            doc.close()

    def crop_golden(self, key: str, *, dpi: int = 300,
                    output: str | Path | None = None) -> CropResult:
        """Crop using a registered golden region (validated by analysis)."""
        golden = GOLDEN_CROPS.get(key)
        if golden is None:
            raise KeyError(f"no golden crop registered for {key!r}")
        bbox, method = self.figure_bbox(golden["page"], golden["candidate"],
                                        golden.get("margin_pt", 12.0))
        result = self.crop(golden["page"], bbox, dpi=dpi, output=output)
        result.method = f"golden+{method}"
        result.content_bbox_pt = list(bbox)
        return result


# ── helpers ─────────────────────────────────────────────────────

def _pil_from(pix) -> "object":
    from PIL import Image
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _trim_white(img, pad_px: int = 4):
    """Trim uniform white borders, keeping pad_px of white margin."""
    from PIL import Image, ImageChops
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if bbox is None:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - pad_px)
    top = max(0, top - pad_px)
    right = min(img.width, right + pad_px)
    bottom = min(img.height, bottom + pad_px)
    return img.crop((left, top, right, bottom))
