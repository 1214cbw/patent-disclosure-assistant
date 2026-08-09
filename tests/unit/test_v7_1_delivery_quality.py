from pathlib import Path

import pytest

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec
from patent_agent.core.config import Settings
from patent_agent.real_case import RealCaseManager
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


def test_figure_graph_rejects_reported_render_collisions():
    figure = make_figure()
    rendered = {"FIG-001": {
        "node_ids": ["N1", "N2"],
        "edge_ids": ["N1->N2"],
        "collisions": [{"type": "arrow-node"}],
    }}
    result = FigureGraphValidator().validate([figure], rendered)
    assert "RENDERED_GRAPH_COLLISION" in codes(result)


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


def test_standard_workflow_factory_injects_provider_for_b_to_c(monkeypatch, tmp_path: Path):
    from patent_agent import llm
    from patent_agent.workflow import build_real_case_workflow

    settings = Settings(
        project_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        template_root=Path(__file__).resolve().parents[2] / "templates",
        output_root=tmp_path / "output",
        patent_llm_mode="external-approved",
        llm_base_url="https://provider.invalid/v1",
        llm_api_key="test-only",
        llm_model="test-model",
    )
    manager = RealCaseManager(tmp_path)
    manifest = manager.create(
        "REAL-PROVIDER-1", authorized=True, llm_mode="external-approved",
        external_llm_approved=True,
    )
    manifest.current_checkpoint = "B"
    manager.save(manifest)
    sentinel = object()
    monkeypatch.setattr(llm, "OpenAICompatibleProvider", lambda settings, model=None: sentinel)
    workflow = build_real_case_workflow(settings, "REAL-PROVIDER-1")
    assert workflow.provider is sentinel


def test_standard_workflow_factory_fails_closed_without_required_provider(tmp_path: Path):
    from patent_agent.workflow import build_real_case_workflow

    settings = Settings(
        project_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        template_root=Path(__file__).resolve().parents[2] / "templates",
        output_root=tmp_path / "output",
        patent_llm_mode="disabled",
    )
    manager = RealCaseManager(tmp_path)
    manifest = manager.create("REAL-PROVIDER-2", authorized=True)
    manifest.current_checkpoint = "B"
    manager.save(manifest)
    with pytest.raises(RuntimeError, match="LLM_PROVIDER_REQUIRED_FOR_CHECKPOINT_B_TO_C"):
        build_real_case_workflow(settings, "REAL-PROVIDER-2")


def test_cross_case_gate_detects_out_of_vocabulary_contamination():
    from patent_agent.v7.cross_case import CrossCaseContaminationValidator, EvidenceFingerprint

    fingerprint = EvidenceFingerprint(
        technical_tokens=frozenset({"thermal", "sensor", "calibration"}),
        fact_ids=frozenset({"F1"}), evidence_ids=frozenset({"E1"}),
    )
    disclosure = type("Disclosure", (), {"sections": [
        type("Section", (), {"title": "5.1", "paragraphs": [
            type("Paragraph", (), {"text": "Quantum annealing selects the result."})()
        ]})()
    ]})()
    result = CrossCaseContaminationValidator(set(), {}, fingerprint).validate(disclosure=disclosure)
    assert not result.passed
    assert "quantum" in result.foreign_concepts


def test_cross_case_gate_detects_wrong_fact_inside_broad_concept_family():
    from patent_agent.v7.cross_case import CrossCaseContaminationValidator, EvidenceFingerprint

    fingerprint = EvidenceFingerprint(
        technical_tokens=frozenset({"ambient", "sensor", "calibration"}),
        fact_ids=frozenset({"F1"}), evidence_ids=frozenset({"E1"}),
    )
    disclosure = type("Disclosure", (), {"sections": [
        type("Section", (), {"title": "5.1 Sensor calibration", "paragraphs": [
            type("Paragraph", (), {"text": "Cryogenic sensor calibration is performed."})()
        ]})()
    ]})()
    result = CrossCaseContaminationValidator(set(), {}, fingerprint).validate(disclosure=disclosure)
    assert not result.passed
    assert "cryogenic" in result.foreign_concepts


def test_case_fingerprint_covers_all_source_derived_fields_and_hyphen_variants():
    from patent_agent.v7.cross_case import build_case_evidence_fingerprint

    understanding = type("Understanding", (), {
        "model_dump": lambda self: {
            "facts": [{"fact_id": "F1", "statement": "finite-element analysis"}],
            "parameters": [{"name": "I-max current limitation"}],
            "experiments": [{"text": "multilayer perceptron implementation"}],
        },
        "facts": [type("Fact", (), {"fact_id": "F1", "evidence_ids": ["E1"]})()],
    })()
    fingerprint = build_case_evidence_fingerprint(understanding)
    assert {"finiteelement", "imax", "multilayer", "perceptron"} <= set(
        fingerprint.technical_tokens
    )


def test_inline_math_registry_is_derived_from_current_equations():
    from patent_agent.document.math_detector import MathSpanDetector
    from patent_agent.document.math_registry import normalize_symbol_aliases, symbols_from_equations

    detector = MathSpanDetector(symbols_from_equations(["i_d^2 + i_q^2 <= I_max^2"]))
    spans = detector.convert_paragraph("运行条件(id, iq)满足Imax约束。")
    latex = [item["latex"] for item in spans if item["type"] == "inline_math"]
    assert "i_{d}" in latex
    assert "i_{q}" in latex
    assert "I_{max}" in latex
    assert normalize_symbol_aliases(
        "输入(id, iq)，满足Imax。", ["i_d^2 + i_q^2 <= I_max^2"]
    ) == "输入(i_d, i_q)，满足I_max。"


def test_language_gate_rejects_untranslated_category_key_in_heading():
    from patent_agent.v7.language_gate import ChinesePatentLanguageValidator

    disclosure = type("Disclosure", (), {
        "title": "一种中文方法",
        "sections": [type("Section", (), {
            "title": "7. 实施例一：machine_specification详细说明",
            "paragraphs": [type("Paragraph", (), {"text": "本实施例具有完整中文正文。"})()],
        })()],
    })()
    result = ChinesePatentLanguageValidator().validate_disclosure(disclosure)
    assert not result.passed
    assert any("章节标题含未中文化类别词" in issue for issue in result.issues)


def test_docx_equation_audit_compares_canonical_omml_signature(tmp_path: Path):
    import zipfile
    from lxml import etree
    from patent_agent.document.equation_engine import latex_to_omml
    from patent_agent.document.equation_engine.omml_renderer import NSMAP
    from patent_agent.v7_1.delivery import audit_docx_equations

    word_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = etree.Element(
        "{%s}document" % word_ns, nsmap={"w": word_ns, "m": NSMAP["m"]}
    )
    body = etree.SubElement(document, "{%s}body" % word_ns)
    body.append(latex_to_omml(r"L=(x+y)^2", display=True))
    path = tmp_path / "equations.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", etree.tostring(document))
    report = audit_docx_equations(path, [{"id": "eq1", "latex": r"L=(x+y)^2"}])
    assert report["status"] == "PASS"
    damaged = audit_docx_equations(path, [{"id": "eq1", "latex": r"L=(x+y)^3"}])
    assert damaged["status"] == "FAIL"
    assert damaged["signature_mismatches"] == ["eq1"]


def test_pdf_render_audit_rejects_blank_page(tmp_path: Path):
    import fitz
    from patent_agent.v7_1.delivery import audit_pdf_render

    path = tmp_path / "blank.pdf"
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()
    report = audit_pdf_render(path, equation_count=0, figure_count=0)
    assert report["status"] == "FAIL"
    assert report["errors"][0]["code"] == "PDF_BLANK_PAGE"


def test_production_hardcode_audit_has_no_forbidden_branching():
    from scripts.production_hardcode_audit import audit

    report = audit(Path(__file__).resolve().parents[2])
    assert report["summary"]["forbidden"] == 0
    assert report["summary"]["pass"] is True


def test_language_gate_does_not_count_latex_commands_as_english_prose():
    from patent_agent.v7.language_gate import ChinesePatentLanguageValidator

    text = r"非线性方程写为 \(\mathbf{K}(\mathbf{A})\mathbf{A}=\mathbf{J}\)，并进行求解。"
    assert ChinesePatentLanguageValidator().validate_paragraph(text)[0] is True
