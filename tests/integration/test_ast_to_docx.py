from pathlib import Path

from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode
from patent_agent.document import DocumentRenderer, PatentDocxValidator


def test_ast_to_docx_native_math_and_figure(tmp_path: Path):
    from PIL import Image
    image = tmp_path / "figure.png"; Image.new("RGB", (100, 100), "white").save(image)
    ast = PatentDocumentAST(document_id="D", kind="disclosure", title="测试", nodes=[
        PatentNode(type="heading", value="测试", level=0),
        PatentNode(type="paragraph", children=[PatentNode(type="text", value="行内"), PatentNode(type="inline_math", latex="T_e")]),
        PatentNode(type="display_equation", target="EQ-001", latex=r"x=\frac{a}{b}", number=1),
        PatentNode(type="display_equation", target="EQ-002", latex=r"y=\sqrt{x^2}", number=2),
        PatentNode(type="paragraph", children=[PatentNode(type="text", value="根据"), PatentNode(type="equation_reference", target="EQ-001")]),
        PatentNode(type="figure", target="FIG-001", path=str(image), value="测试图", number=1),
        PatentNode(type="paragraph", children=[PatentNode(type="text", value="如"), PatentNode(type="figure_reference", target="FIG-001")]),
    ])
    out = DocumentRenderer(tmp_path / "templates").render(ast, tmp_path / "test.docx")
    report = PatentDocxValidator().inspect_xml(out)
    assert report["omml_count"] == 3
    assert report["inline_omml_count"] == 1
    assert report["image_count"] == 1
    assert report["xml_pass"]

