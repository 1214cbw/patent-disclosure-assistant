"""V7.0 generalization-hardening tests.

Covers: native-Chinese output contract (source language != output language),
language gate before stage save, 9-section disclosure completeness,
fact-restructuring (facts are grounding input, not paragraphs), cross-case
isolation (artifact/figure/formula), unsupported-paragraph and placeholder
gates, figure semantic grounding, case-local latest artifact, save_stage
double-JSON regression, and REAL-PAPER-002 (flow matching) vs REAL-PAPER-001
(LDM) figure concept routing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from patent_agent.core.models import (
    ComponentKnowledge,
    EquationKnowledge,
    EvidenceStatus,
    GroundedDisclosure,
    GroundedParagraph,
    GroundedProtectionStrategy,
    GroundedSection,
    GroundedStatement,
    InventorQuestion,
    MethodStepKnowledge,
    ParameterKnowledge,
    ReviewStatus,
    TechnicalFact,
    TechnicalUnderstandingResult,
)
from patent_agent.core.state import CaseStore
from patent_agent.v7.completeness import (
    DisclosureCompletenessValidator,
    PatentTitleValidator,
    UnsupportedParagraphValidator,
)
from patent_agent.v7.cross_case import (
    CrossCaseContaminationValidator,
    FigureSemanticValidator,
    FormulaScopeValidator,
    PlaceholderLeakValidator,
    build_case_evidence_fingerprint,
    case_concepts_from_understanding,
)
from patent_agent.v7.disclosure_planner import (
    PatentDisclosurePlanner,
    _text_retry,
    cluster_facts,
)
from patent_agent.v7.figure_planner import FigurePlannerV7
from patent_agent.v7.gates import V7GateError, run_disclosure_gates
from patent_agent.v7.language_gate import ChinesePatentLanguageValidator
from patent_agent.review.traceability import build_traceability

CJK_LINE = "本发明涉及一种基于流匹配的电机转子拓扑生成方法，其特征在于通过代理模型进行多目标优化。"
EN_LINE = "The proposed method uses a flow matching model to generate motor rotor topologies, and a surrogate model predicts the performance metrics for multi-objective optimization."


# ── fixtures ────────────────────────────────────────────────────────────────

def _fact(fact_id: str, text: str) -> TechnicalFact:
    return TechnicalFact(
        fact_id=fact_id, statement=text, category="方法",
        evidence_ids=[f"E-{fact_id}"],
        status=EvidenceStatus.SOURCE_FACT, confidence=0.9,
        review_status=ReviewStatus.LOCKED,
    )


def _stmt(text: str, evidence: list[str] | None = None) -> GroundedStatement:
    return GroundedStatement(
        text=text, evidence_ids=evidence or ["E-1"],
        status=EvidenceStatus.SOURCE_FACT, confidence=0.9,
        review_status=ReviewStatus.LOCKED,
    )


def _para(pid: str, section_id: str, text: str,
          fact_ids: list[str] | None = None) -> GroundedParagraph:
    return GroundedParagraph(
        paragraph_id=pid, section_id=section_id, text=text,
        evidence_ids=["E-1"], fact_ids=fact_ids or ["F-1"],
        derived_from=fact_ids or ["F-1"],
        status=EvidenceStatus.SOURCE_FACT, review_status=ReviewStatus.LOCKED,
    )


def flow_matching_understanding() -> TechnicalUnderstandingResult:
    """A REAL-PAPER-002-like understanding: flow matching + FiLM surrogate +
    NSGA-II. NO diffusion/U-Net content (the 002 paper never mentions it)."""
    facts = [
        _fact("F-001", "The dataset is built from parameterized rotor topologies sampled by Latin hypercube sampling."),
        _fact("F-002", "A latent space flow matching model is trained to generate new rotor topology images."),
        _fact("F-003", "A feature-wise linear modulation (FiLM) surrogate predicts torque and flux linkage."),
        _fact("F-004", "A NSGA-II based multi-objective optimization searches the current vector (Id, Iq) subject to voltage and flux constraints."),
        _fact("F-005", "Candidate designs are verified by magnetostatic finite element analysis and screened."),
    ]
    return TechnicalUnderstandingResult(
        technical_field=[_stmt("永磁辅助同步磁阻电机转子拓扑优化设计")],
        technical_problems=[_stmt("现有生成模型难以兼顾生成质量与代理精度，多目标优化计算代价高")],
        system_overview=[_stmt("基于潜在空间流匹配与特征线性调制代理模型的耦合优化框架")],
        components=[ComponentKnowledge(component_id="C-1", name="流匹配生成器",
                                       description=_stmt("生成候选拓扑"))],
        steps=[MethodStepKnowledge(step_id="S-1", text=_stmt("构建参数化数据集")),
               MethodStepKnowledge(step_id="S-2", text=_stmt("训练流匹配生成模型")),
               MethodStepKnowledge(step_id="S-3", text=_stmt("构建FiLM代理模型")),
               MethodStepKnowledge(step_id="S-4", text=_stmt("多目标优化设计"))],
        data_flows=[], control_flows=[],
        inputs=[_stmt("设计变量电流矢量")], outputs=[_stmt("最优转子拓扑")],
        parameters=[ParameterKnowledge(parameter_id="P-1",
                                       name="电流矢量(Id, Iq)", evidence_ids=["E-1"],
                                       status=EvidenceStatus.SOURCE_FACT)],
        equations=[EquationKnowledge(equation_id="EQ-001",
                                     original_expression="FiLM(z)=gamma*z+beta",
                                     normalized_latex=r"\gamma \cdot z + \beta",
                                     evidence_ids=["E-1"],
                                     status=EvidenceStatus.SOURCE_FACT)],
        technical_effects=[_stmt("兼顾生成质量与优化效率")],
        experiments=[], alternatives=[],
        uncertainties=[InventorQuestion(question_id="Q-1", text="关键参数取值？", priority="P0")],
        facts=facts,
    )


def ldm_understanding() -> TechnicalUnderstandingResult:
    """A REAL-PAPER-001-like understanding: latent diffusion + VAE + U-Net."""
    facts = [
        _fact("F-101", "The RGB topology image is encoded to a latent vector z0 by a VAE encoder."),
        _fact("F-102", "A latent diffusion model with U-Net denoising generates new topologies via forward and reverse diffusion."),
        _fact("F-103", "The decoder reconstructs the generated topology image from the latent."),
    ]
    return TechnicalUnderstandingResult(
        technical_field=[_stmt("电机转子潜在扩散生成")],
        technical_problems=[_stmt("现有方法难以生成高质量拓扑")],
        system_overview=[_stmt("VAE与潜在扩散模型结合的生成框架")],
        components=[ComponentKnowledge(component_id="C-1", name="VAE编码器",
                                       description=_stmt("编码"))],
        steps=[MethodStepKnowledge(step_id="S-1", text=_stmt("潜在扩散生成训练"))],
        data_flows=[], control_flows=[],
        inputs=[_stmt("RGB拓扑图像")], outputs=[_stmt("生成拓扑图像")],
        parameters=[ParameterKnowledge(parameter_id="P-1",
                                       name="扩散时间步t", evidence_ids=["E-1"],
                                       status=EvidenceStatus.SOURCE_FACT)],
        equations=[EquationKnowledge(equation_id="EQ-101",
                                     original_expression="L=E||eps-eps_hat||^2",
                                     normalized_latex=r"\mathcal{L}=\|\varepsilon-\hat{\varepsilon}\|^2",
                                     evidence_ids=["E-1"],
                                     status=EvidenceStatus.SOURCE_FACT)],
        technical_effects=[_stmt("生成高质量拓扑")],
        experiments=[], alternatives=[],
        uncertainties=[InventorQuestion(question_id="Q-1", text="训练数据规模？", priority="P0")],
        facts=facts,
    )


def nine_section_disclosure(
    title: str = "基于流匹配的电机转子拓扑生成方法",
    *,
    unsupported_embodiment: bool = False,
    contaminated_invention: str | None = None,
) -> GroundedDisclosure:
    """Full 9-section Chinese disclosure with dynamic 5.N subsections derived
    from deterministic fact clustering (no hardcoded titles)."""
    clusters = cluster_facts(flow_matching_understanding().facts)
    sections = [
        GroundedSection(section_id="01", title="1. 发明名称",
                        paragraphs=[_para("D-01", "01", title)]),
        GroundedSection(section_id="02", title="2. 技术领域",
                        paragraphs=[_para("D-02", "02", "本发明涉及电机转子拓扑优化设计技术领域。")]),
        GroundedSection(section_id="03", title="3. 背景技术",
                        paragraphs=[_para("D-03", "03", "现有技术中，生成模型与代理模型相互割裂，优化计算代价高。")]),
        GroundedSection(section_id="04", title="4. 发明内容",
                        paragraphs=[_para("D-04", "04",
                                          contaminated_invention or "本发明的目的在于提供一种耦合优化设计方法。")]),
    ]
    # 5. 技术方案详细说明 wrapper + dynamic 5.N chain subsections
    sections.append(GroundedSection(
        section_id="05", title="5. 技术方案详细说明",
        paragraphs=[_para("D-05", "05",
                          "本发明技术方案的实施包括以下技术环节，各环节的详细说明如下：",
                          fact_ids=[getattr(f, "fact_id", "") for f in
                                    flow_matching_understanding().facts])]))
    for index, _cluster in enumerate(clusters, 1):
        sections.append(GroundedSection(
            section_id=f"05-{index:02d}", title=f"5.{index} 技术环节{index}",
            paragraphs=[_para(f"D-05-{index}", f"05-{index:02d}",
                              "本环节通过参数化建模与采样构建数据集，形成生成模型的输入。",
                              fact_ids=[getattr(f, "fact_id", "") for f in _cluster])],
        ))
    sections.append(GroundedSection(
        section_id="06", title="6. 附图说明",
        paragraphs=[_para("D-06", "06", "图1 本发明技术方案总体流程图。", fact_ids=["F-001"])]))
    if unsupported_embodiment:
        sections.append(GroundedSection(
            section_id="07", title="7. 具体实施方式",
            paragraphs=[GroundedParagraph(
                paragraph_id="D-07", section_id="07",
                text="本实施例采用某参数，具体数值未知。",
                evidence_ids=[], fact_ids=[], derived_from=[],
                status=EvidenceStatus.SOURCE_FACT,
                review_status=ReviewStatus.LOCKED)]))
    else:
        sections.append(GroundedSection(
            section_id="07", title="7. 具体实施方式",
            paragraphs=[_para("D-07", "07", "实施例一：构建参数化数据集，采用拉丁超立方采样。",
                              fact_ids=["F-001"])]))
    sections.append(GroundedSection(
        section_id="08", title="8. 建议重点向专利代理机构说明的技术内容",
        paragraphs=[_para("D-08", "08", "核心发明点在于流匹配生成与代理模型耦合。")]))
    sections.append(GroundedSection(
        section_id="09", title="9. 待发明人或代理机构进一步确认的信息",
        paragraphs=[_para("D-09", "09", "关键参数取值待发明人确认。")]))
    return GroundedDisclosure(title=title, sections=sections)


def _strategy() -> GroundedProtectionStrategy:
    return GroundedProtectionStrategy(
        inventive_concept="基于潜在空间流匹配与特征线性调制代理模型的耦合优化",
        independent_claim_core=[
            _stmt("构建参数化转子拓扑数据集"),
            _stmt("训练流匹配生成模型生成候选拓扑"),
            _stmt("构建特征线性调制代理模型预测性能"),
            _stmt("基于NSGA-II进行多目标优化"),
        ],
        dependent_claim_features=[], optional_features=[],
        broad_terms=[], narrow_terms=[], parameters_to_avoid_locking=[],
        alternative_embodiments_needed=[], support_gaps=[],
        risks=[], inventor_questions=["关键参数取值待确认"],
        scope_strategy="Balanced",
    )


def _gate_run(disclosure, *, own_concepts=None, unsupported=None):
    return run_disclosure_gates(
        case_id="REAL-X", disclosure=disclosure, claims=None, figures=[],
        language_validator=ChinesePatentLanguageValidator(),
        completeness_validator=DisclosureCompletenessValidator(),
        unsupported_validator=unsupported or UnsupportedParagraphValidator(),
        contamination_validator=CrossCaseContaminationValidator(
            own_concepts or {"flow_matching", "surrogate", "optimization"},
            {"REAL-PAPER-001": {"latent_diffusion", "vae"}}),
        placeholder_validator=PlaceholderLeakValidator(),
    )


# ── language gate ───────────────────────────────────────────────────────────

def test_patent_output_language_chinese():
    """Whole-English prose paragraphs fail the language gate; Chinese passes."""
    validator = ChinesePatentLanguageValidator()
    assert validator.validate_texts([CJK_LINE]).passed
    result = validator.validate_texts([EN_LINE])
    assert not result.passed
    assert result.english_paragraphs


def test_english_source_chinese_output():
    """English facts feed a Chinese disclosure: the output gate passes, and
    concept detection still works on the English source."""
    understanding = flow_matching_understanding()
    concepts = case_concepts_from_understanding(understanding)
    assert "flow_matching" in concepts and "surrogate" in concepts
    assert "latent_diffusion" not in concepts
    disclosure = nine_section_disclosure()
    assert ChinesePatentLanguageValidator().validate_disclosure(disclosure).passed


def test_language_gate_allows_first_occurrence_terms():
    """中文（English，缩写） first-occurrence terms are allowed, not leaks."""
    text = ("本发明基于流匹配（Flow Matching）与特征线性调制（FiLM）技术，"
            "采用永磁辅助同步磁阻电机（PMa-SynRM）作为研究对象。")
    assert ChinesePatentLanguageValidator().validate_texts([text]).passed


# ── gate before save ────────────────────────────────────────────────────────

def test_language_gate_before_stage_save():
    """An English-bodied disclosure raises LANGUAGE_GATE_FAILED - it must
    never reach a saved stage."""
    english = GroundedDisclosure(
        title="基于流匹配的生成方法",
        sections=[GroundedSection(section_id="04", title="4. 发明内容",
                                  paragraphs=[_para("D-1", "04", EN_LINE)])])
    with pytest.raises(V7GateError) as exc:
        _gate_run(english)
    assert exc.value.code == "LANGUAGE_GATE_FAILED"


def test_title_gate_failed_blocks():
    """A title with >25 CJK chars fails PatentTitleValidator."""
    result = PatentTitleValidator().validate(
        "一种基于潜在空间流匹配与特征线性调制代理模型的永磁辅助同步磁阻电机转子拓扑耦合优化设计方法及其系统")
    assert not result.passed
    assert result.length > 25


# ── completeness ────────────────────────────────────────────────────────────

def test_disclosure_required_sections():
    """The full 9-section schema passes; a stripped disclosure is incomplete."""
    assert DisclosureCompletenessValidator().validate(nine_section_disclosure()).passed
    partial = GroundedDisclosure(
        title="x", sections=[GroundedSection(section_id="06", title="6. 技术方案",
                                             paragraphs=[])])
    result = DisclosureCompletenessValidator().validate(partial)
    assert not result.passed
    assert "发明内容" in result.missing and "附图说明" in result.missing


def test_fact_not_directly_disclosure_paragraph():
    """Facts are restructuring input: the solution section is a dynamic 5.N
    technical chain with fact links - never a verbatim fact dump."""
    disclosure = nine_section_disclosure()
    solution_titles = [s.title for s in disclosure.sections
                       if s.section_id.startswith("05-")]
    assert len(solution_titles) >= 2          # multiple chain subsections
    assert all(t.startswith("5.") for t in solution_titles)
    # verbatim English facts as disclosure paragraphs must fail the gate
    dump = GroundedDisclosure(
        title="基于流匹配的生成方法",
        sections=[GroundedSection(section_id="05-01", title="5.1 数据构建",
                                  paragraphs=[_para("D-1", "05-01", EN_LINE)])])
    assert not ChinesePatentLanguageValidator().validate_disclosure(dump).passed


# ── unsupported / placeholder ───────────────────────────────────────────────

def test_unsupported_paragraph_gate():
    """Core-section paragraphs without fact/evidence links are unsupported."""
    validator = UnsupportedParagraphValidator()
    assert validator.validate(nine_section_disclosure()).passed
    bad = nine_section_disclosure(unsupported_embodiment=True)
    result = validator.validate(bad)
    assert not result.passed
    with pytest.raises(V7GateError) as exc:
        _gate_run(bad, unsupported=validator)
    assert exc.value.code == "UNSUPPORTED_DISCLOSURE_PARAGRAPH"


def test_placeholder_leak():
    """Demo/template phrases must never leak into real-case output."""
    validator = PlaceholderLeakValidator()
    assert validator.validate(disclosure=nine_section_disclosure()).passed
    leaked = GroundedDisclosure(
        title="x",
        sections=[GroundedSection(section_id="04", title="4. 发明内容",
                                  paragraphs=[_para("D-1", "04",
                                                    "通过融合状态量进行控制参数修正。")])])
    assert not validator.validate(disclosure=leaked).passed


# ── cross-case isolation ────────────────────────────────────────────────────

def test_cross_case_artifact_isolation():
    """Case A output containing case B's exclusive concepts is blocked."""
    own = case_concepts_from_understanding(flow_matching_understanding())
    validator = CrossCaseContaminationValidator(
        own, {"REAL-PAPER-001": {"latent_diffusion", "vae"}})
    assert validator.validate(
        disclosure=nine_section_disclosure()).passed
    contaminated = nine_section_disclosure(
        contaminated_invention="通过U-Net反向扩散去噪生成新拓扑。")
    result = validator.validate(disclosure=contaminated)
    assert not result.passed
    assert "latent_diffusion" in result.foreign_concepts
    with pytest.raises(V7GateError) as exc:
        _gate_run(contaminated, own_concepts=own)
    assert exc.value.code == "CROSS_CASE_CONTAMINATION"


def test_fixed_family_signal_yields_to_current_raw_source_evidence():
    """A comparison concept found only in raw current-case evidence is not
    foreign merely because compact A1 facts omitted it."""
    from types import SimpleNamespace
    evidence = SimpleNamespace(all=lambda: [SimpleNamespace(
        evidence_id="EV-RAW-1",
        raw_text="A generative adversarial network is evaluated only as a baseline.",
        normalized_text="",
    )])
    fingerprint = build_case_evidence_fingerprint(
        flow_matching_understanding(), evidence)
    validator = CrossCaseContaminationValidator(
        case_concepts_from_understanding(flow_matching_understanding()),
        {"SIBLING": {"generative_gan"}}, fingerprint)
    disclosure = nine_section_disclosure(
        contaminated_invention="生成对抗网络仅用于比较验证。")
    assert validator.validate(disclosure=disclosure).passed


def test_generated_figure_accepts_direct_current_evidence_provenance():
    from types import SimpleNamespace
    from patent_agent.core.models import FigureNode, FigureSpec
    evidence = SimpleNamespace(all=lambda: [SimpleNamespace(
        evidence_id="EV-RAW-2", raw_text="Supported component relation.",
        normalized_text="",
    )])
    fingerprint = build_case_evidence_fingerprint(
        flow_matching_understanding(), evidence)
    figure = FigureSpec(
        id="FIG-DIRECT", number=1, type="system", title="组件关系图",
        nodes=[FigureNode(id="N1", label="组件", evidence_ids=["EV-RAW-2"])],
        edges=[], source_ids=["EV-RAW-2"], source_fact_ids=[], provenance="generated",
    )
    validator = CrossCaseContaminationValidator(
        case_concepts_from_understanding(flow_matching_understanding()), {}, fingerprint)
    assert validator.validate(figures=[figure]).passed


def test_cross_case_figure_isolation():
    """A figure carrying another case's concept keyword is figure-semantic
    contamination."""
    own = case_concepts_from_understanding(flow_matching_understanding())
    validator = FigureSemanticValidator(own)
    figures = FigurePlannerV7("REAL-002", flow_matching_understanding()).plan()
    assert validator.validate(figures).passed
    from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec
    bad = FigureSpec(id="FIG-X", number=9, type="flowchart",
                     title="潜在扩散模型架构图",
                     nodes=[FigureNode(id="N1", label="U-Net反向去噪")],
                     edges=[], source_ids=[])
    result = validator.validate([bad])
    assert not result.passed


def test_cross_case_formula_isolation():
    """A display equation outside the case's own registry is blocked."""
    understanding = flow_matching_understanding()
    registry = {item.equation_id for item in understanding.equations}
    validator = FormulaScopeValidator(registry)
    assert validator.validate(understanding.equations).passed
    from patent_agent.core.models import EquationSpec
    foreign = EquationSpec(id="EQ-999", latex=r"\frac{1}{\sqrt{2\pi}}e^{-x^2/2}",
                           role="derived", source_ids=[])
    result = validator.validate([foreign])
    assert not result.passed
    assert "EQ-999" in result.foreign_concepts


# ── figure semantic grounding ───────────────────────────────────────────────

def test_figure_semantic_grounding():
    """FigurePlannerV7 stamps every generated figure with case fingerprint
    and derives figures from the case's own concepts (never another case's
    template)."""
    figures = FigurePlannerV7("REAL-002", flow_matching_understanding()).plan()
    assert 2 <= len(figures) <= 8
    for figure in figures:
        assert figure.case_id == "REAL-002"
        provenance = figure.provenance or "generated"
        if provenance in ("extracted", "omitted", "uploaded"):
            continue
        assert figure.source_feature_ids   # grounded on own evidence
        assert figure.semantic_keywords
    titles = " ".join(f.title for f in figures)
    assert "流匹配" in titles or "总体流程" in titles


def test_real_paper_002_no_ldm_concepts():
    """REAL-PAPER-002 (flow matching) must NEVER get diffusion/U-Net figures."""
    understanding = flow_matching_understanding()
    figures = FigurePlannerV7("REAL-002", understanding).plan()
    joined = " ".join(
        f.title + " " + " ".join(n.label for n in f.nodes)
        for f in figures).lower()
    for forbidden in ("diffusion", "扩散", "u-net", "unet", "反向去噪", "潜在扩散"):
        assert forbidden not in joined
    concepts = case_concepts_from_understanding(understanding)
    assert "latent_diffusion" not in concepts
    # caption language gate passes on the generated set
    assert ChinesePatentLanguageValidator().validate_figure_captions(figures).passed


def test_real_paper_001_regression():
    """REAL-PAPER-001 (LDM) regression: diffusion evidence still yields the
    LDM figure set - CASE-001 must not break."""
    figures = FigurePlannerV7("REAL-001", ldm_understanding()).plan()
    joined = " ".join(f.title for f in figures)
    assert "潜在扩散" in joined
    assert len(figures) == 4
    assert [f.number for f in figures] == [1, 2, 3, 4]


# ── case-local artifacts & save_stage ───────────────────────────────────────

def test_case_local_latest_artifact(tmp_path: Path):
    """latest_stage_path returns the NEWEST version of THIS case only."""
    store = CaseStore(tmp_path)
    store.create("REAL-A", "A")
    store.create("REAL-B", "B")
    store.save_stage("REAL-A", "p1_disclosure", {"v": 1})
    store.save_stage("REAL-A", "p1_disclosure", {"v": 2})
    store.save_stage("REAL-B", "p1_disclosure", {"v": 99})
    latest = json.loads(store.latest_stage_path("REAL-A", "p1_disclosure")
                        .read_text(encoding="utf-8"))
    assert latest == {"v": 2}
    assert json.loads(store.latest_stage_path("REAL-B", "p1_disclosure")
                      .read_text(encoding="utf-8")) == {"v": 99}


def test_save_stage_no_double_json(tmp_path: Path):
    """save_stage writes a payload exactly once - a saved file must parse as
    the payload, never as a double-encoded JSON string."""
    store = CaseStore(tmp_path)
    store.create("REAL-DJ", "DJ")
    payload = {"sections": [{"title": "4. 发明内容", "paragraphs": ["中文段落"]}], "n": 3}
    path = store.save_stage("REAL-DJ", "p1_disclosure", payload)
    raw = path.read_text(encoding="utf-8")
    assert "\\\"" not in raw            # no escaped quotes => no double encoding
    assert json.loads(raw) == payload
    # str payloads (already-serialized JSON) are written verbatim
    text_path = store.save_stage("REAL-DJ", "p1_disclosure",
                                 json.dumps({"x": 1}, ensure_ascii=False))
    assert json.loads(text_path.read_text(encoding="utf-8")) == {"x": 1}


# ── manifest language separation ────────────────────────────────────────────

def test_source_language_output_language_separation(tmp_path: Path):
    """English source chunks are detected as en while the patent output
    language stays zh-CN (manifest contract)."""
    from patent_agent.workflow.real_case_pipeline import _detect_languages
    en_chunks = tmp_path / "en_chunks.jsonl"
    en_chunks.write_text("\n".join(json.dumps({
        "evidence_id": f"E{i}", "raw_text": text
    }) for i, text in enumerate([
        "The proposed latent space flow matching model generates rotor topologies with high fidelity.",
        "A feature-wise linear modulation surrogate predicts torque and flux linkage for NSGA-II optimization.",
    ])), encoding="utf-8")
    assert _detect_languages(en_chunks) == ["en"]
    assert _detect_languages(tmp_path / "missing.jsonl") == []
    zh_chunks = tmp_path / "zh_chunks.jsonl"
    zh_chunks.write_text(json.dumps({"evidence_id": "E1",
                                     "raw_text": "本发明提供一种基于流匹配的转子拓扑生成方法。"}),
                         encoding="utf-8")
    assert _detect_languages(zh_chunks) == ["zh-CN"]


# ── 002 complete disclosure via deterministic plan ──────────────────────────

def test_real_paper_002_complete_disclosure():
    """build_plan yields the full 9-section schema for the 002-style case and
    passes completeness - including dynamic 5.N solution subsections derived
    from fact clustering (no hardcoded 002 titles)."""
    understanding = flow_matching_understanding()
    strategy = _strategy()
    figures = FigurePlannerV7("REAL-002", understanding).plan()
    clusters = cluster_facts(understanding.facts)
    plan = PatentDisclosurePlanner(provider=None).build_plan(
        understanding, strategy, figures, clusters,
        title="基于流匹配的电机转子拓扑生成方法")
    kinds = [sec["kind"] for sec in plan]
    assert {"title", "field", "background", "invention", "solution_parent",
            "figures", "embodiment", "agency", "questions"} <= set(kinds)
    solution = [sec for sec in plan if sec["kind"] == "solution"]
    assert len(solution) >= 2
    for sec in solution:
        assert sec["section_id"].startswith("05-")
    parent = next(sec for sec in plan if sec["kind"] == "solution_parent")
    assert parent["title"] == "5. 技术方案详细说明"
    # every cluster fact is represented in some solution subsection
    planned_ids = {getattr(f, "fact_id", "")
                   for sec in solution for f in sec["facts"]}
    all_ids = {getattr(f, "fact_id", "") for f in understanding.facts}
    assert planned_ids == all_ids
    assert not DisclosureCompletenessValidator().validate(
        nine_section_disclosure()).missing


# ── direct LLM call resilience (V7 hardening) ───────────────────────────────

class _FlakyProvider:
    """Fake provider: fails n times with LLMConnectionFailed, then returns text."""

    def __init__(self, fail_count: int = 1):
        self.fail_count = fail_count
        self.calls = 0
        self.system_prompts = []
        self.user_prompts = []

    def generate_text(self, *, system_prompt, user_prompt, context=None):
        self.calls += 1
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        if self.calls <= self.fail_count:
            raise RuntimeError("LLM_CONNECTION_FAILED: TimeoutError: simulate")
        return type("R", (), {"text": "生成的中文正文段落。"})()


def test_llm_text_retry_recovers_after_failure():
    """A single connection failure must not crash the disclosure stage - the
    retry helper retries direct provider calls (planner bypasses the
    StructuredLLMService retry loop for free-text generation)."""
    provider = _FlakyProvider(fail_count=2)
    text = _text_retry(provider, system_prompt="规则", user_prompt="请求")
    assert provider.calls == 3
    assert "生成的中文正文" in text
    assert provider.system_prompts == ["规则"] * 3


def test_llm_text_retry_gives_up_and_reraises():
    """After exhausting retries the original error surfaces so the gate
    reports the real failure instead of swallowing it."""
    provider = _FlakyProvider(fail_count=99)
    with pytest.raises(RuntimeError, match="LLM_CONNECTION_FAILED"):
        _text_retry(provider, system_prompt="规则", user_prompt="请求", attempts=2)
    assert provider.calls == 2


# ── language gate: first-occurrence expansions (mandate pattern) ────────────

def test_language_gate_allows_first_occurrence_expansions():
    """中文（English Full Name，缩写） first-occurrence expansions are mandated-
    allowed; the gate must not block paragraphs that are Chinese prose carrying
    them (regression: run-4 LANGUAGE_GATE_FAILED on the generated disclosure)."""
    validator = ChinesePatentLanguageValidator()
    paragraphs = [
        # P1
        "本发明涉及电机设计技术领域，尤其涉及一种用于永磁辅助式同步磁阻电机（Permanent Magnet-assisted "
        "Synchronous Reluctance Machine，PMa-SynRM）的转子拓扑优化技术，具体采用基于深度学习的生成模型"
        "及代理模型对电机转子结构进行自动设计与性能预测。",
        # P2 - FlowV AE artifact + expansion
        "本环节详述本技术方案中集成FlowV AE生成模型与FiLM替代模型的多目标转子拓扑优化实施流程。所述优化"
        "流程针对三层永磁辅助同步磁阻电机（Permanent Magnet-assisted Synchronous Reluctance Motor，"
        "PMa-SynRM）的转子拓扑，起始于参数化转子拓扑数据集的构建阶段。",
        # P3 - multiple expansions in one paragraph
        "在FlowV AE生成阶段，本技术方案采用变分自编码器（Variational Autoencoder，VAE）与流匹配"
        "（Flow Matching，FM）相结合的生成模型。所述FlowV AE模型接收数据集中的拓扑样本作为输入，经训练"
        "后生成具备改善的图像质量与结构多样性的转子拓扑图像；相对于生成对抗网络（Generative Adversarial "
        "Network，GAN）的组合方案，生成质量更优。",
        # P4 - units r/min + NSGA-II expansion
        "最后，基于FlowV AE生成的候选拓扑及FiLM预测的性能指标，通过非支配排序遗传算法II"
        "（Non-dominated Sorting Genetic Algorithm II，NSGA-II）实施多目标优化搜索。以目标转速为"
        "3000 r/min与8000 r/min的三层PMa-SynRM为优化对象，开展三目标优化。",
        # P5 - Feature-wise Linear Modulation expansion
        "本环节描述特征线性调制（Feature-wise Linear Modulation，FiLM）替代模型如何将运行条件嵌入特征"
        "提取网络，以实现对磁链的精确预测。本技术方案采用FiLM机制，将运行条件参数（d轴电流id、q轴电流"
        "iq以及转子角位置θ）作为条件信息，注入到所述替代模型的多层级特征提取过程中。",
        # P8 - expansion as appositive mid-sentence
        "本环节涉及在电磁特性预测任务中采用特征线性调制（Feature-wise Linear Modulation，FiLM）作为"
        "替代模型的核心机制，对输入设计参数进行处理，以获取比传统网络更低的预测误差。",
    ]
    result = validator.validate_texts(paragraphs, context="p1_disclosure")
    assert result.passed, result.issues
    assert result.english_paragraphs == []


def test_language_gate_blocks_english_sentence_still():
    """A whole English sentence must still be blocked after the expansion
    allowance (the gate only strips the mandated parenthetical pattern)."""
    validator = ChinesePatentLanguageValidator()
    assert not validator.validate_paragraph(
        "The proposed method uses a flow matching model to generate motor "
        "rotor topologies, and a surrogate model predicts the performance "
        "metrics for multi-objective optimization.")[0]


def test_language_gate_blocks_english_sentence_inside_parens():
    """An English sentence wrapped in parens WITHOUT an abbreviation-like tail
    is not a first-occurrence expansion and stays blocked."""
    validator = ChinesePatentLanguageValidator()
    text = ("本发明提出一种方法（This method reduces torque ripple by ninety "
            "percent while keeping efficiency high, as the results show）以"
            "降低转矩脉动。")
    assert not validator.validate_paragraph(text)[0]


def test_language_gate_allows_abbrev_dense_prose():
    """Abbreviation-dense Chinese prose (FiLM/GAN/NSGA-II/r/min units) with no
    expansions passes - all tokens are abbreviation-like or units."""
    validator = ChinesePatentLanguageValidator()
    text = ("进一步在三目标搜索场景下进行处理与比较，输出显示基于FlowV AE的组合方案相较于对应的基于"
            "GAN的组合方案，提供了更好的帕累托集收敛性和覆盖性。特别地，在3000 r/min和8000 r/min的工况"
            "转速下，本发明提出的FlowV AE–FiLM框架相对于GAN–FiLM框架，在超体积和反向世代距离两项指标上"
            "均获得了改善。")
    assert validator.validate_paragraph(text)[0]


# ── planner LLM call cache (restart resilience) ─────────────────────────────

def test_llm_text_retry_cache_roundtrip(tmp_path):
    """With a cache dir, a second call with the same prompt returns the cached
    text without invoking the provider (a gate-failed restart replays C
    instantly instead of re-paying all LLM calls)."""
    provider = _FlakyProvider(fail_count=0)
    first = _text_retry(provider, "规则", "请求", cache_dir=tmp_path)
    assert provider.calls == 1
    second = _text_retry(provider, "规则", "请求", cache_dir=tmp_path)
    assert provider.calls == 1          # served from cache
    assert second == first


def test_llm_text_retry_cache_different_prompt_misses(tmp_path):
    provider = _FlakyProvider(fail_count=0)
    _text_retry(provider, "规则", "请求一", cache_dir=tmp_path)
    _text_retry(provider, "规则", "请求二", cache_dir=tmp_path)
    assert provider.calls == 2


# ── traceability (V7 finalize gate) ─────────────────────────────────────────

def _trace_understanding() -> TechnicalUnderstandingResult:
    """Understanding whose evidence union contains both a plain chunk id and
    an EV-<doc>-P00N-<hash> style chunk, plus the facts behind them."""
    u = flow_matching_understanding()
    page_fact = TechnicalFact(
        fact_id="F-PAGE", statement="候选拓扑经有限元验证筛选。", category="方法",
        evidence_ids=["EV-DOC1D2D7D98C9-P006-aaaaaaaa"],
        status=EvidenceStatus.SOURCE_FACT, confidence=0.9,
        review_status=ReviewStatus.LOCKED,
    )
    sibling_fact = TechnicalFact(
        fact_id="F-SIBLING", statement="有限元网格与边界条件设定。", category="方法",
        evidence_ids=["EV-DOC1D2D7D98C9-P006-bbbbbbbb"],
        status=EvidenceStatus.SOURCE_FACT, confidence=0.9,
        review_status=ReviewStatus.LOCKED,
    )
    u.facts = list(u.facts) + [page_fact, sibling_fact]
    return u


def test_traceability_uncited_questions_paragraph_is_linked():
    """V7 section 09 (待发明人或代理机构进一步确认的信息) is a list of
    questions and legitimately carries no fact/evidence citations. An uncited
    paragraph must be LINKED - only citations that fail to resolve are broken
    (this was the finalize blocker for REAL-PAPER-002 run 7)."""
    u = _trace_understanding()
    grounded = _para("DISC-05-P001", "05", "段落", fact_ids=["F-001"])
    question = GroundedParagraph(
        paragraph_id="DISC-09-P001", section_id="09", text="请确认磁链映射模型外推误差范围？",
        evidence_ids=[], fact_ids=[], derived_from=[],
        status=EvidenceStatus.SOURCE_FACT, review_status=ReviewStatus.LOCKED,
    )
    disclosure = GroundedDisclosure(title="基于流匹配的电机转子拓扑生成方法", sections=[
        GroundedSection(section_id="05", title="5. 技术方案详细说明", paragraphs=[grounded]),
        GroundedSection(section_id="09", title="9. 待发明人或代理机构进一步确认的信息",
                        paragraphs=[question]),
    ])
    from patent_agent.core.models import GroundedClaimSet
    report = build_traceability(disclosure, GroundedClaimSet(title="t", claims=[]), u)
    assert report.broken_links == []
    by_id = {link.link_id: link for link in report.links}
    assert by_id["TR-DISC-09-P001"].status == "LINKED"


def test_traceability_resolves_synthetic_validation_fact_ids():
    u = _trace_understanding()
    u.experiments = [_stmt("独立验证实验", ["EV-VALIDATION-001"])]
    paragraph = GroundedParagraph(
        paragraph_id="DISC-07-P001", section_id="07", text="验证步骤V1。",
        evidence_ids=["EV-VALIDATION-001"], fact_ids=["VALIDATION-001"],
        derived_from=["VALIDATION-001"], status=EvidenceStatus.SOURCE_FACT,
        review_status=ReviewStatus.LOCKED,
    )
    disclosure = GroundedDisclosure(title="t", sections=[
        GroundedSection(section_id="07", title="7. 具体实施方式", paragraphs=[paragraph])])
    from patent_agent.core.models import GroundedClaimSet
    report = build_traceability(disclosure, GroundedClaimSet(title="t", claims=[]), u)
    assert report.broken_links == []


def test_traceability_paragraph_with_unresolved_citation_is_broken():
    """A paragraph citing an evidence id outside the understanding's union
    stays BROKEN - the resolve-or-break rule is not weakened."""
    u = _trace_understanding()
    p = GroundedParagraph(
        paragraph_id="DISC-02-P001", section_id="02", text="段落",
        evidence_ids=["EV-DOC1D2D7D98C9-P999-ffffffff"], fact_ids=[],
        derived_from=[],
        status=EvidenceStatus.SOURCE_FACT, review_status=ReviewStatus.LOCKED,
    )
    disclosure = GroundedDisclosure(title="t", sections=[
        GroundedSection(section_id="02", title="2. 技术领域", paragraphs=[p])])
    from patent_agent.core.models import GroundedClaimSet
    report = build_traceability(disclosure, GroundedClaimSet(title="t", claims=[]), u)
    assert "TR-DISC-02-P001" in report.broken_links


def test_traceability_feature_region_match_links_same_page_chunks():
    """LLM-chosen chunk citations on the same source page (EV-<doc>-P006-*)
    cross-reference each other even when the chunk hashes differ: claim
    feature grounded via strategy-level evidence is supported by a paragraph
    citing a sibling chunk of the same page. Empty source_fact_ids alone must
    not break the link (REAL-PAPER-002 CORE-F004)."""
    from patent_agent.core.models import (
        ClaimFeature, GroundedClaimSet, PatentClaimV2)
    u = _trace_understanding()
    para = GroundedParagraph(
        paragraph_id="DISC-05-P003", section_id="05", text="候选拓扑验证段落",
        evidence_ids=["EV-DOC1D2D7D98C9-P006-bbbbbbbb"], fact_ids=[],
        derived_from=[],
        status=EvidenceStatus.SOURCE_FACT, review_status=ReviewStatus.LOCKED,
    )
    disclosure = GroundedDisclosure(title="t", sections=[
        GroundedSection(section_id="05", title="5. 技术方案详细说明", paragraphs=[para])])
    feature = ClaimFeature(
        feature_id="CORE-F004", text="有限元验证筛选候选拓扑。",
        source_fact_ids=[], evidence_ids=["EV-DOC1D2D7D98C9-P006-aaaaaaaa"],
        support_status="SUPPORTED", mandatory=True,
    )
    claim = PatentClaimV2(claim_number=1, claim_type="method", features=[feature],
                          rendered_text="t", draft_strategy="broad")
    claims = GroundedClaimSet(title="t", claims=[claim])
    report = build_traceability(disclosure, claims, u)
    assert report.broken_links == []
    link = next(l for l in report.links
                if l.object_type == "claim_feature" and l.object_id == "CL1:CORE-F004")
    assert link.status == "LINKED"
    assert link.disclosure_paragraph_ids == ["DISC-05-P003"]


def test_traceability_feature_citing_unknown_evidence_is_broken():
    """A claim feature citing evidence outside the union must stay BROKEN."""
    from patent_agent.core.models import (
        ClaimFeature, GroundedClaimSet, PatentClaimV2)
    u = _trace_understanding()
    para = _para("DISC-05-P001", "05", "段落", fact_ids=["F-001"])
    disclosure = GroundedDisclosure(title="t", sections=[
        GroundedSection(section_id="05", title="5. 技术方案详细说明", paragraphs=[para])])
    feature = ClaimFeature(
        feature_id="CORE-F001", text="特征。",
        source_fact_ids=["F-001"], evidence_ids=["EV-DOC1D2D7D98C9-P999-ffffffff"],
        support_status="SUPPORTED", mandatory=True,
    )
    claim = PatentClaimV2(claim_number=1, claim_type="method", features=[feature],
                          rendered_text="t", draft_strategy="broad")
    claims = GroundedClaimSet(title="t", claims=[claim])
    report = build_traceability(disclosure, claims, u)
    assert "TR-CL1-CORE-F001" in report.broken_links
