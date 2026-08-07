from __future__ import annotations

from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode
from .equation_engine import EquationEngine
from .styles import configure_styles, set_run_font
from .template_manager import TemplateManager


class DocumentRenderer:
    """Deterministic AST-to-DOCX renderer. It never invokes an LLM."""
    def __init__(self, template_root: Path):
        self.templates = TemplateManager(template_root)
        self.equations = EquationEngine()

    def render(self, ast: PatentDocumentAST, output_path: Path, template_path: Path | None = None) -> Path:
        template = template_path or self.templates.ensure_default()
        document = configure_styles(Document(template))
        document.core_properties.title = ast.title
        document.core_properties.subject = f"Patent Agent {ast.kind}"
        for node in ast.nodes:
            self._render_node(document, node)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_path)
        return output_path

    def _render_node(self, document, node: PatentNode):
        if node.type == "heading":
            paragraph = document.add_paragraph(style="Title" if node.level == 0 else f"Heading {min(node.level or 1, 2)}")
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if node.level == 0 else WD_ALIGN_PARAGRAPH.LEFT
            set_run_font(paragraph.add_run(node.value), east_asia="黑体", size=20 if node.level == 0 else 14, bold=True)
        elif node.type == "paragraph":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.first_line_indent = Cm(0.74)
            if node.children:
                for child in node.children: self._render_inline(paragraph, child)
            else:
                set_run_font(paragraph.add_run(node.value))
        elif node.type == "display_equation":
            if node.number is not None: self.equations.insert_numbered(document, node.latex, node.number)
            else: self.equations.insert_display(document, node.latex)
        elif node.type == "figure":
            paragraph = document.add_paragraph(); paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.add_run().add_picture(node.path, width=Cm(13.5))
            caption = document.add_paragraph(style="Patent Caption"); caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # Strip duplicate "图N" prefix from value if present
            import re
            figure_title = node.value or ""
            figure_title = re.sub(r'^图\s*\d+\s*[：:.\s]*', '', figure_title).strip()
            set_run_font(caption.add_run(f"图{node.number}  {figure_title}"), size=10.5)
        elif node.type == "list":
            for child in node.children:
                paragraph = document.add_paragraph(style="List Bullet"); set_run_font(paragraph.add_run(child.value))
        elif node.type == "claim":
            paragraph = document.add_paragraph(); paragraph.paragraph_format.first_line_indent = Cm(0.74)
            set_run_font(paragraph.add_run(f"{node.number}. {node.value}"))
        elif node.type == "inventor_question":
            paragraph = document.add_paragraph(); set_run_font(paragraph.add_run("[待发明人确认] " + node.value), bold=True)
        elif node.type == "page_break": document.add_page_break()

    def _render_inline(self, paragraph, node: PatentNode):
        if node.type == "text": set_run_font(paragraph.add_run(node.value))
        elif node.type == "inline_math": self.equations.insert_inline(paragraph, node.latex)
        elif node.type == "equation_reference": set_run_font(paragraph.add_run(f"式（{self._ref_number(node.target)}）"))
        elif node.type == "figure_reference": set_run_font(paragraph.add_run(f"图{self._ref_number(node.target)}"))
        elif node.type == "source_citation": set_run_font(paragraph.add_run(node.value), size=9)

    @staticmethod
    def _ref_number(target: str) -> int:
        digits = "".join(ch for ch in target if ch.isdigit())
        return int(digits or "0")

