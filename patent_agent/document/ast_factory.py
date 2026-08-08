"""AST factory: converts structured disclosure/claims models to PatentDocumentAST."""
from __future__ import annotations

from patent_agent.core.models import ClaimTree, DisclosureDraft
from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode


def disclosure_to_ast(
    case_id: str,
    draft: DisclosureDraft,
) -> PatentDocumentAST:
    """Convert a DisclosureDraft to PatentDocumentAST with proper figure & equation placement.

    Sections are detected by content keywords (V7: the legacy_demo_mode branch
    with hardcoded 6./8. numbering and demo control sentences was removed).
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

        # Content-based detection (V7)
        is_figure_section = _is_figure_section(heading)
        is_tech_section = _is_tech_section(heading)

        if not is_figure_section:
            for paragraph in paragraphs:
                nodes.append(PatentNode(type="paragraph", value=paragraph))

        if is_tech_section and equation_nodes and not inserted_equations:
            if equation_nodes:
                nodes.append(PatentNode(type="paragraph", value="本技术方案涉及的关键公式如下："))
            nodes.extend(equation_nodes)
            # Patent-standard equation reference (式（1）); when the first
            # equation declares symbols, the first symbol is rendered as
            # inline math (genuine OMML, never fabricated prose).
            reference_children: list[PatentNode] = [
                PatentNode(type="text", value="其中，"),
            ]
            first_symbol = next(iter((draft.equations[0].symbols or {})), None) \
                if draft.equations else None
            if first_symbol:
                reference_children.append(PatentNode(type="inline_math", latex=first_symbol))
                reference_children.append(PatentNode(type="text", value=" 等关键参数的含义如"))
            else:
                reference_children.append(PatentNode(type="text", value="本技术方案的关键参数关系如"))
            reference_children.append(
                PatentNode(type="equation_reference", target=equation_nodes[0].target))
            reference_children.append(
                PatentNode(type="text", value="所示，各符号含义详见具体实施方式。"))
            nodes.append(PatentNode(type="paragraph", children=reference_children))
            inserted_equations = True

        if is_figure_section and figure_nodes and not inserted_figures:
            if figure_nodes:
                nodes.append(PatentNode(
                    type="paragraph",
                    value=f"本技术方案包含以下{len(figure_nodes)}幅附图：",
                ))
            # V6.7: no forced page breaks between figures - dynamic
            # pagination keeps each Figure+Caption on one page (see
            # DocumentRenderer keep_with_next) without creating blank
            # pages after the figure block.
            for figure_node in figure_nodes:
                nodes.append(figure_node)
            inserted_figures = True

    # Fallback: if no figure section was found, append figures at the end
    if figure_nodes and not inserted_figures:
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
