from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


def set_run_font(run, latin: str = "Times New Roman", east_asia: str = "宋体", size: float = 12, bold: bool = False):
    run.font.name = latin
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east_asia)
    run.font.size = Pt(size)
    run.bold = bold


def configure_styles(document):
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    normal.paragraph_format.space_after = Pt(0)
    for name, size, color in (("Title", 20, RGBColor(0, 0, 0)), ("Heading 1", 16, RGBColor(0, 0, 0)), ("Heading 2", 14, RGBColor(0, 0, 0))):
        style = document.styles[name]
        style.font.name = "Arial"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = color
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(6)
    if "Patent Caption" not in document.styles:
        caption = document.styles.add_style("Patent Caption", WD_STYLE_TYPE.PARAGRAPH)
        caption.font.name = "Times New Roman"
        caption._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        caption.font.size = Pt(10.5)
    return document

