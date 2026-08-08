from pathlib import Path

from patent_agent.core.models import DisclosureDraft, FigureSpec
from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode
from patent_agent.document import DocumentRenderer, PatentDocxValidator
from patent_agent.document.ast_factory import disclosure_to_ast


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


def test_disclosure_ast_no_forced_page_break_between_figures():
    """V6.7: figures must NOT be separated by forced page breaks.

    Pagination is dynamic (Figure+Caption kept together by Word properties);
    a forced break after the figure block creates a blank page.
    """
    figures = [
        FigureSpec(id=f"FIG-{index:03d}", number=index, type="flowchart", title=f"图{index}", nodes=[], edges=[], source_ids=[], png_path=f"figure-{index}.png")
        for index in (1, 2)
    ]
    draft = DisclosureDraft(
        title="测试",
        sections={"8. 附图说明": []},
        equations=[],
        figures=figures,
        inventor_questions=[],
        evidence_ids=[],
    )

    ast = disclosure_to_ast("TEST", draft)
    figure_indexes = [index for index, node in enumerate(ast.nodes) if node.type == "figure"]

    assert len(figure_indexes) == 2
    between = ast.nodes[figure_indexes[0] + 1 : figure_indexes[1]]
    assert all(node.type != "page_break" for node in between), \
        "figure 之间不允许强制分页（会造成空白页）"
