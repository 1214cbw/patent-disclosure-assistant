"""AST factory: converts structured disclosure/claims models to PatentDocumentAST."""
from __future__ import annotations

from patent_agent.core.models import ClaimTree, DisclosureDraft
from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode


def disclosure_to_ast(
    case_id: str,
    draft: DisclosureDraft,
    *,
    legacy_demo_mode: bool = False,
) -> PatentDocumentAST:
    """Convert a DisclosureDraft to PatentDocumentAST with proper figure & equation placement.

    In legacy_demo_mode (for old demo pipeline), uses hardcoded section numbering (6./8.)
    and demo-specific text. Otherwise, detects sections by content keywords.
    """
    nodes: list[PatentNode] = [
        PatentNode(type="heading", value=draft.title, level=0)
    ]

    figure_nodes = []
    for figure in draft.figures:
        # V6.6: omitted figures (e.g. 待用户补充的真实结构图) become an
        # explicit placeholder note, never a fake rendering.
        provenance = getattr(figure, "provenance", "") or "generated"
        if provenance == "omitted" or not figure.png_path:
            figure_nodes.append(PatentNode(
                type="paragraph",
                value=f"图{figure.number}  {figure.title} —— 本图为原始论文结构图，"
                      f"当前版本未嵌入，待用户上传真实截图后补充。",
            ))
            continue
        figure_nodes.append(PatentNode(
            type="figure",
            target=figure.id,
            number=figure.number,
            path=figure.png_path,
            value=figure.title,
        ))
    equation_nodes = [
        PatentNode(
            type="display_equation",
            target=equation.id,
            latex=equation.latex,
            number=index,
        )
        for index, equation in enumerate(draft.equations, 1)
    ]

    inserted_equations = False
    inserted_figures = False

    for heading, paragraphs in draft.sections.items():
        nodes.append(PatentNode(type="heading", value=heading, level=1))

        if legacy_demo_mode:
            # Legacy behavior: use hardcoded section numbers
            if not heading.startswith("8."):
                for paragraph in paragraphs:
                    nodes.append(PatentNode(type="paragraph", value=paragraph))
            if heading.startswith("6.") and not inserted_equations:
                nodes.append(PatentNode(type="paragraph", children=[
                    PatentNode(type="text", value="在控制过程中，电磁转矩 "),
                    PatentNode(type="inline_math", latex="T_e"),
                    PatentNode(type="text", value=" 作为状态量参与控制参数修正。"),
                ]))
                nodes.extend(equation_nodes)
                if equation_nodes:
                    nodes.append(PatentNode(type="paragraph", children=[
                        PatentNode(type="text", value="根据"),
                        PatentNode(type="equation_reference", target=equation_nodes[0].target),
                        PatentNode(type="text", value="计算融合状态量，并据此生成控制参数修正量。"),
                    ]))
                inserted_equations = True
            if heading.startswith("8.") and not inserted_figures:
                if figure_nodes:
                    nodes.append(PatentNode(type="paragraph", children=[
                        PatentNode(type="text", value="该方法形成从多源信号采集到自适应控制指令输出的闭环流程，如"),
                        PatentNode(type="figure_reference", target=figure_nodes[0].target),
                        PatentNode(type="text", value="所示。"),
                    ]))
                for index, figure_node in enumerate(figure_nodes):
                    if index:
                        nodes.append(PatentNode(type="page_break"))
                    nodes.append(figure_node)
                inserted_figures = True
        else:
            # New behavior: content-based detection
            is_figure_section = _is_figure_section(heading)
            is_tech_section = _is_tech_section(heading)

            if not is_figure_section:
                for paragraph in paragraphs:
                    nodes.append(PatentNode(type="paragraph", value=paragraph))

            if is_tech_section and equation_nodes and not inserted_equations:
                if equation_nodes:
                    nodes.append(PatentNode(type="paragraph", value="本技术方案涉及的关键公式如下："))
                nodes.extend(equation_nodes)
                inserted_equations = True

            if is_figure_section and figure_nodes and not inserted_figures:
                if figure_nodes:
                    nodes.append(PatentNode(
                        type="paragraph",
                        value=f"本技术方案包含以下{len(figure_nodes)}幅附图：",
                    ))
                for index, figure_node in enumerate(figure_nodes):
                    if index > 0:
                        nodes.append(PatentNode(type="page_break"))
                    nodes.append(figure_node)
                inserted_figures = True

    # Fallback: if no figure section was found, append figures at the end
    if figure_nodes and not inserted_figures and not legacy_demo_mode:
        nodes.append(PatentNode(type="heading", value="附图", level=1))
        for figure_node in figure_nodes:
            nodes.append(figure_node)
        inserted_figures = True

    return PatentDocumentAST(
        document_id=f"{case_id}-DISCLOSURE",
        kind="disclosure",
        title=draft.title,
        nodes=nodes,
        metadata={
            "case_id": case_id,
            "review_notice": "供发明人及专利专业人员复核",
        },
    )


def claims_to_ast(case_id: str, tree: ClaimTree) -> PatentDocumentAST:
    """Convert a ClaimTree to PatentDocumentAST."""
    nodes = [
        PatentNode(type="heading", value="权利要求草案", level=0),
        PatentNode(
            type="paragraph",
            value="本文件为辅助草案，需由发明人和专利代理师复核。",
        ),
    ]
    for claim in tree.claims:
        nodes.append(
            PatentNode(
                type="claim",
                number=claim.number,
                value=claim.text,
                attrs={
                    "depends_on": claim.depends_on,
                    "scope": claim.scope,
                },
            )
        )
    return PatentDocumentAST(
        document_id=f"{case_id}-CLAIMS",
        kind="claims",
        title=tree.title,
        nodes=nodes,
        metadata={"case_id": case_id},
    )


def _is_figure_section(heading: str) -> bool:
    """Detect if a section heading is the figure description section."""
    keywords = ["附图", "图", "附图说明", "figure", "图示"]
    return any(kw in heading for kw in keywords)


def _is_tech_section(heading: str) -> bool:
    """Detect if a section heading is the technical solution section."""
    keywords = ["技术方案", "具体实施方式", "实施方式", "实施例"]
    return any(kw in heading for kw in keywords)
