"""BlankPageValidator V6.7 - detect unexpected blank pages in the rendered
disclosure document.

A page is UNEXPECTED_BLANK_PAGE when it carries no body text, no image,
no caption and no equation - i.e. nothing that belongs to the document
content. Blank pages are caused by forced page breaks after a figure block
(the figure moved to the next page, leaving an empty page behind); V6.7
removes those breaks, so a clean render reports zero blank pages.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class BlankPageFinding:
    page: int
    code: str          # "UNEXPECTED_BLANK_PAGE"
    detail: str


class BlankPageValidator:
    """Analyze a PDF export of the disclosure for blank pages."""

    def analyze(self, pdf_path: str | Path) -> dict:
        """Per-page content summary of the PDF.

        Returns {"pages": [...], "blank_pages": [...], "pass": bool}.
        """
        doc = fitz.open(str(pdf_path))
        try:
            pages = []
            for i, page in enumerate(doc):
                # Body content = text blocks EXCLUDING the page-number
                # footer (a page that carries only its page number is
                # still a blank page).
                h = page.rect.height
                body_parts = []
                footer_parts = []
                for block in page.get_text("blocks"):
                    text = block[4].strip()
                    if not text:
                        continue
                    if block[3] > h * 0.88 and text.isdigit():
                        footer_parts.append(text)
                    else:
                        body_parts.append(text)
                text = "\n".join(body_parts)
                images = page.get_images(full=True)
                n_images = len(images)
                text_len = len(text)
                has_caption = any(
                    line.strip().startswith("图") and
                    line.strip()[1:2].isdigit()
                    for line in text.splitlines()
                )
                blank = text_len == 0 and n_images == 0
                pages.append({
                    "page": i + 1,
                    "text_len": text_len,
                    "image_count": n_images,
                    "footer": "".join(footer_parts),
                    "has_caption": has_caption,
                    "blank": blank,
                    "preview": text[:80].replace("\n", " | "),
                })
            blank_pages = [p["page"] for p in pages if p["blank"]]
            return {
                "pdf": str(pdf_path),
                "total_pages": len(pages),
                "blank_pages": blank_pages,
                "pages": pages,
                "pass": not blank_pages,
            }
        finally:
            doc.close()

    def validate(self, pdf_path: str | Path) -> list[BlankPageFinding]:
        """Return one UNEXPECTED_BLANK_PAGE finding per blank page."""
        analysis = self.analyze(pdf_path)
        findings = []
        for page_info in analysis["pages"]:
            if page_info["blank"]:
                findings.append(BlankPageFinding(
                    page=page_info["page"],
                    code="UNEXPECTED_BLANK_PAGE",
                    detail="页面无正文、无图片、无图题（强制分页残留）",
                ))
        return findings

    @staticmethod
    def findings_to_dict(findings: list[BlankPageFinding]) -> list[dict]:
        return [asdict(f) for f in findings]
