from pathlib import Path

import pytest

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec
from patent_agent.v7_1.quality import (
    BilingualTermValidator,
    DeliveryQualityGate,
    EquationIntegrityValidator,
    FigureGraphValidator,
    FigureNarrativeConsistencyValidator,
    HeadingCompletenessValidator,
    SectionCompletenessValidator,
    TechnicalTerminologyNormalizer,
    TokenIntegrityValidator,
)


def codes(result):
    return {finding.code for finding in result.findings}


@pytest.mark.parametrize(
    ("heading", "code"),
    [
        ("5.1 本环节通过所述多", "TITLE_PREFIX_TRUNCATION"),
        ("5.2 特征调制（代理模型", "TITLE_UNCLOSED_DELIMITER"),
        ("5.3 参数优化以及", "TITLE_INCOMPLETE_SUFFIX"),
    ],
)
def test_heading_completeness_rejects_historic_patterns(heading, code):
    result = HeadingCompletenessValidator().validate([heading])
    assert code in codes(result)


def test_section_completeness_rejects_missing_body_and_consecutive_headings():
    sections = [
        {"section_id": "05-15", "title": "5.15 图像重建", "paragraphs": []},
        {"section_id": "05-16", "title": "5.16 参数筛选", "paragraphs": ["有效技术正文。"]},
    ]
    result = SectionCompletenessValidator(min_body_chars=6).validate(sections)
    assert "TECHNICAL_SECTION_BODY_MISSING" in codes(result)
    assert "CONSECUTIVE_HEADING_WITHOUT_BODY" in codes(result)


def test_figure_description_section_cannot_be_empty():
    result = SectionCompletenessValidator().validate(
        [{"section_id": "06", "title": "6. 附图说明", "paragraphs": []}]
    )
    assert "FIGURE_DESCRIPTION_SECTION_EMPTY" in codes(result)


def test_figure_section_routing_does_not_treat_image_word_as_figure_section():
    from patent_agent.document.ast_factory import _is_figure_section

    assert not _is_figure_section("5.15 图像重建与性能预测")
    assert _is_figure_section("6. 附图说明")


def make_figure(**updates):
    values = dict(
        id="FIG-001",
        number=1,
        type="flowchart",
        title="证据驱动流程图",
        nodes=[FigureNode(id="N1", label="输入"), FigureNode(id="N2", label="输出")],
        edges=[FigureEdge(source="N1", target="N2")],
        source_ids=["FACT-1"],
        purpose="展示输入到输出的处理关系",
        source_type="generated_from_facts",
        source_fact_ids=["FACT-1"],
        required_node_ids=["N1", "N2"],
        required_edge_ids=["N1->N2"],
        optional_node_ids=[],
        caption="输入到输出的处理流程",
    )
    values.update(updates)
    return FigureSpec(**values)


def test_figure_graph_rejects_dangling_arrow_and_missing_requirements():
    figure = make_figure(
        edges=[FigureEdge(source="GHOST", target="N2")],
        required_node_ids=["N1", "N2", "N3"],
        required_edge_ids=["N1->N2"],
    )
    result = FigureGraphValidator().validate([figure])
    assert {"DANGLING_ARROW", "REQUIRED_NODE_MISSING", "REQUIRED_EDGE_MISSING"} <= codes(result)


def test_figure_graph_rejects_renderer_plan_parity_loss():
    figure = make_figure()
    rendered = {"FIG-001": {"node_ids": ["N1"], "edge_ids": []}}
    result = FigureGraphValidator().validate([figure], rendered)
    assert {"RENDERED_NODE_MISSING", "RENDERED_EDGE_MISSING"} <= codes(result)


def test_bilingual_term_validator_rejects_duplicate_expansion():
    result = BilingualTermValidator().validate(["流匹配（流匹配）训练流程"])
    assert "DUPLICATE_TERM_EXPANSION" in codes(result)


def test_case_derived_terminology_repairs_split_token():
    normalizer = TechnicalTerminologyNormalizer.from_source_texts(
        ["FlowVAE combines VAE and flow matching; PMa-SynRM is evaluated."]
    )
    repaired = normalizer.normalize("采用 FlowV AE 与 V AE+FM 进行处理")
    assert "FlowVAE" in repaired
    assert "VAE+FM" in repaired
    assert "FlowV AE" not in repaired
    assert "TECHNICAL_TOKEN_SPLIT" not in codes(TokenIntegrityValidator(normalizer.registry).validate([repaired]))


def test_token_integrity_detects_unrepaired_registered_token():
    normalizer = TechnicalTerminologyNormalizer.from_source_texts(["FlowVAE is trained."])
    result = TokenIntegrityValidator(normalizer.registry).validate(["FlowV AE is used."])
    assert "TECHNICAL_TOKEN_SPLIT" in codes(result)


@pytest.mark.parametrize(
    ("actual", "expected_code"),
    [
        (r"L=x+y", "EQUATION_REQUIRED_TOKEN_MISSING"),
        (r"L=x+y+", "EQUATION_TRAILING_OPERATOR"),
        (r"L=(x+y", "EQUATION_UNBALANCED_DELIMITER"),
    ],
)
def test_equation_integrity_detects_truncation(actual, expected_code):
    result = EquationIntegrityValidator().validate(
        [{"id": "eq1", "latex": r"L=(x+y)^2"}],
        [{"id": "eq1", "latex": actual}],
    )
    assert expected_code in codes(result)


def test_equation_integrity_checks_count_and_order():
    expected = [{"id": "eq1", "latex": "a=b"}, {"id": "eq2", "latex": "c=d"}]
    actual = [{"id": "eq2", "latex": "c=d"}]
    result = EquationIntegrityValidator().validate(expected, actual)
    assert {"EQUATION_COUNT_MISMATCH", "EQUATION_ID_ORDER_MISMATCH"} <= codes(result)


def test_narrative_consistency_rejects_negated_operation_in_figure():
    figure = make_figure(
        nodes=[FigureNode(id="N1", label="ODE integration"), FigureNode(id="N2", label="output")],
        edges=[FigureEdge(source="N1", target="N2")],
    )
    result = FigureNarrativeConsistencyValidator().validate(
        ["The method operates without ODE integration."], [figure]
    )
    assert "FIGURE_NARRATIVE_CONTRADICTION" in codes(result)


def test_delivery_gate_blocks_missing_render_audit(tmp_path: Path):
    result = DeliveryQualityGate().validate(
        component_results=[],
        docx_path=tmp_path / "missing.docx",
        pdf_path=tmp_path / "missing.pdf",
        render_audit=None,
    )
    assert result.status == "FAIL"
    assert "RENDER_AUDIT_MISSING" in codes(result)
