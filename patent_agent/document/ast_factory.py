from __future__ import annotations

from patent_agent.core.models import ClaimTree, DisclosureDraft
from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode


def disclosure_to_ast(case_id: str, draft: DisclosureDraft) -> PatentDocumentAST:
    nodes: list[PatentNode] = [PatentNode(type="heading", value=draft.title, level=0)]
    figure_nodes = [PatentNode(type="figure", target=figure.id, number=figure.number, path=figure.png_path, value=figure.title) for figure in draft.figures]
    equation_nodes = [PatentNode(type="display_equation", target=equation.id, latex=equation.latex, number=index) for index, equation in enumerate(draft.equations, 1)]
    inserted_equations = inserted_figures = False
    for heading, paragraphs in draft.sections.items():
        nodes.append(PatentNode(type="heading", value=heading, level=1))
        if not heading.startswith("8."):
            for paragraph in paragraphs:
                nodes.append(PatentNode(type="paragraph", value=paragraph))
        if heading.startswith("6.") and not inserted_equations:
            nodes.append(PatentNode(type="paragraph", children=[PatentNode(type="text", value="在控制过程中，电磁转矩 "), PatentNode(type="inline_math", latex="T_e"), PatentNode(type="text", value=" 作为状态量参与控制参数修正。")]))
            nodes.extend(equation_nodes)
            if equation_nodes:
                nodes.append(PatentNode(type="paragraph", children=[PatentNode(type="text", value="根据"), PatentNode(type="equation_reference", target=equation_nodes[0].target), PatentNode(type="text", value="计算融合状态量，并据此生成控制参数修正量。")]))
            inserted_equations = True
        if heading.startswith("8.") and not inserted_figures:
            if figure_nodes:
                nodes.append(PatentNode(type="paragraph", children=[PatentNode(type="text", value="该方法形成从多源信号采集到自适应控制指令输出的闭环流程，如"), PatentNode(type="figure_reference", target=figure_nodes[0].target), PatentNode(type="text", value="所示。")]))
            nodes.extend(figure_nodes); inserted_figures = True
    return PatentDocumentAST(document_id=f"{case_id}-DISCLOSURE", kind="disclosure", title=draft.title, nodes=nodes, metadata={"case_id": case_id, "review_notice": "供发明人及专利专业人员复核"})


def claims_to_ast(case_id: str, tree: ClaimTree) -> PatentDocumentAST:
    nodes = [PatentNode(type="heading", value="权利要求草案", level=0), PatentNode(type="paragraph", value="本文件为辅助草案，需由发明人和专利代理师复核。")]
    for claim in tree.claims:
        nodes.append(PatentNode(type="claim", number=claim.number, value=claim.text, attrs={"depends_on": claim.depends_on, "scope": claim.scope}))
    return PatentDocumentAST(document_id=f"{case_id}-CLAIMS", kind="claims", title=tree.title, nodes=nodes, metadata={"case_id": case_id})
