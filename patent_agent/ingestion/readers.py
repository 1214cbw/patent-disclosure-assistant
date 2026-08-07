from __future__ import annotations

from pathlib import Path


def read_text(path: Path) -> list[tuple[str, str]]:
    return [("全文", path.read_text(encoding="utf-8"))]


def read_docx(path: Path) -> list[tuple[str, str]]:
    from docx import Document
    document = Document(path)
    blocks = []
    heading = "正文"
    buffer: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if paragraph.style and paragraph.style.name.startswith("Heading"):
            if buffer: blocks.append((heading, "\n".join(buffer))); buffer = []
            heading = text
        else:
            buffer.append(text)
    if buffer: blocks.append((heading, "\n".join(buffer)))
    return blocks


def read_pdf(path: Path) -> list[tuple[str, str]]:
    from pypdf import PdfReader
    return [(f"第{index + 1}页", page.extract_text() or "") for index, page in enumerate(PdfReader(str(path)).pages)]


def read_pptx(path: Path) -> list[tuple[str, str]]:
    from pptx import Presentation
    blocks = []
    for index, slide in enumerate(Presentation(path).slides, 1):
        text = "\n".join(shape.text for shape in slide.shapes if hasattr(shape, "text") and shape.text.strip())
        blocks.append((f"第{index}页", text))
    return blocks

