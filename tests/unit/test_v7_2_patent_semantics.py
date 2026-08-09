from __future__ import annotations

from types import SimpleNamespace

from patent_agent.v7.disclosure_planner import _align_period_qualifier
from patent_agent.agents.technical_understanding_v2 import _retrieve_task_context
from patent_agent.v7_2.semantics import (
    EmbodimentPlan,
    EmbodimentStep,
    EvidenceBoundEmbodimentPlanner,
    InventionCoreGraph,
    InventionEdge,
    InventionNode,
    PatentSemanticsValidator,
    RequiredFeature,
    ScenarioRole,
    SemanticFact,
    SemanticRegistry,
    SemanticRole,
    TechnicalRole,
    TechnicalRoleEntry,
    infer_invention_type,
)


def _node(node_id: str, feature: str, role=SemanticRole.TECHNICAL_STEP):
    return InventionNode(
        node_id=node_id,
        semantic_role=role,
        fact_ids=[f"fact-{node_id}"],
        evidence_ids=[f"ev-{node_id}"],
        input_types=["input"] if node_id == "N1" else [f"out-{int(node_id[1:]) - 1}"],
        output_types=[f"out-{node_id[1:]}"],
        required=True,
        required_feature_ids=[feature],
        scenario=ScenarioRole.DESIGN,
    )


def _graph() -> InventionCoreGraph:
    nodes = [_node("N1", "F1"), _node("N2", "F2"), _node("N3", "F3")]
    return InventionCoreGraph(
        nodes=nodes,
        edges=[
            InventionEdge(source="N1", target="N2", data_or_control_flow="out-1", evidence_ids=["ev-N2"]),
            InventionEdge(source="N2", target="N3", data_or_control_flow="out-2", evidence_ids=["ev-N3"]),
        ],
        input_objects=["input"],
        output_objects=["out-3"],
        required_feature_ids=["F1", "F2", "F3"],
    )


def _step(index: int, *, role=SemanticRole.TECHNICAL_STEP, scenario=ScenarioRole.DESIGN,
          inputs=None, outputs=None, terms=None, alternatives=None, parameters=None,
          evidence=True, processing=None) -> EmbodimentStep:
    return EmbodimentStep(
        step_id=f"S{index}",
        title=f"步骤{index}",
        purpose="执行受支持的技术操作",
        inputs=inputs if inputs is not None else (["input"] if index == 1 else [f"out-{index - 1}"]),
        processing=processing or f"根据事实fact-N{index}执行处理",
        outputs=outputs if outputs is not None else [f"out-{index}"],
        fact_ids=[f"fact-N{index}"],
        evidence_ids=[f"ev-N{index}"] if evidence else [],
        next_step=f"S{index + 1}" if index < 3 else None,
        scenario=scenario,
        semantic_role=role,
        required_feature_ids=[f"F{index}"],
        technical_terms=terms or [],
        alternatives=alternatives or [],
        parameters=parameters or [],
    )


def _plan(steps=None, *, title="完整技术方法的实施过程", primary=True,
          validation_steps=None, pending=None) -> EmbodimentPlan:
    steps = steps or [_step(1), _step(2), _step(3)]
    return EmbodimentPlan(
        embodiment_id="EMB-001",
        title=title,
        embodiment_type="method",
        is_primary=primary,
        scenario=ScenarioRole.DESIGN,
        input_objects=["input"],
        output_objects=["out-3"],
        ordered_steps=steps,
        required_feature_ids=["F1", "F2", "F3"],
        supporting_feature_ids=[],
        fact_ids=sorted({fact for step in steps for fact in step.fact_ids}),
        evidence_ids=sorted({ev for step in steps for ev in step.evidence_ids}),
        validation_steps=validation_steps or [],
        pending_confirmations=pending or [],
        final_technical_result="out-3",
    )


def _features():
    return [
        RequiredFeature(feature_id=f"F{i}", fact_ids=[f"fact-N{i}"], evidence_ids=[f"ev-N{i}"])
        for i in range(1, 4)
    ]


def _registry(**kwargs):
    values = {
        "supported_scenarios": [ScenarioRole.DESIGN, ScenarioRole.VALIDATION],
        "technical_roles": [],
        "supported_alternatives": [],
        "supported_parameters": [],
        "source_texts": ["supported technical input output processing"],
    }
    values.update(kwargs)
    return SemanticRegistry(**values)


def _codes(report):
    return {finding.code for finding in report.findings}


def _validate(plans, **kwargs):
    return PatentSemanticsValidator().validate(
        embodiments=plans,
        graph=kwargs.pop("graph", _graph()),
        required_features=kwargs.pop("required_features", _features()),
        registry=kwargs.pop("registry", _registry()),
        **kwargs,
    )


def test_fact_cluster_not_embodiment():
    report = _validate([_plan([_step(1)], title="数据事实")])
    assert "PRIMARY_EMBODIMENT_INCOMPLETE" in _codes(report)


def test_loss_function_not_independent_embodiment():
    report = _validate([_plan([_step(1, role=SemanticRole.FORMULA_ONLY)], title="损失函数")])
    assert "PROHIBITED_EMBODIMENT_ROLE" in _codes(report)


def test_parameter_set_not_independent_embodiment():
    report = _validate([_plan([_step(1, role=SemanticRole.PARAMETER_SET)], title="参数设置")])
    assert "PROHIBITED_EMBODIMENT_ROLE" in _codes(report)


def test_machine_spec_not_independent_embodiment():
    report = _validate([_plan([_step(1, role=SemanticRole.MACHINE_SPEC)], title="设备规格")])
    assert "PROHIBITED_EMBODIMENT_ROLE" in _codes(report)


def test_limitation_not_embodiment():
    report = _validate([_plan([_step(1, role=SemanticRole.LIMITATION)], title="局限性说明")])
    assert "PROHIBITED_EMBODIMENT_ROLE" in _codes(report)


def test_experiment_not_automatically_embodiment():
    report = _validate([_plan([_step(1, role=SemanticRole.EXPERIMENT)], title="实验设置")])
    assert "PROHIBITED_EMBODIMENT_ROLE" in _codes(report)


def test_comparison_baseline_not_invention_component():
    registry = _registry(technical_roles=[
        TechnicalRoleEntry(term="BaselineNet", role=TechnicalRole.COMPARISON_BASELINE, evidence_ids=["ev-val"])
    ])
    report = _validate([_plan([_step(1), _step(2, terms=["BaselineNet"]), _step(3)])], registry=registry)
    assert "BASELINE_PROMOTED_TO_INVENTION" in _codes(report)


def test_unsupported_text_data_generalization():
    step = _step(2, processing="输入可为图像、文本或其它类型的数据")
    report = _validate([_plan([_step(1), step, _step(3)])])
    assert "UNSUPPORTED_GENERALIZATION" in _codes(report)


def test_offline_design_to_online_control_scenario_drift():
    step = _step(2, scenario=ScenarioRole.ONLINE_CONTROL, processing="每个控制周期实时采集信号")
    report = _validate([_plan([_step(1), step, _step(3)])])
    assert "SCENARIO_DRIFT" in _codes(report)


def test_unsupported_sensor_invention():
    step = _step(2, terms=["position_sensor"], processing="利用位置传感器采集输入")
    report = _validate([_plan([_step(1), step, _step(3)])])
    assert "UNSUPPORTED_GENERALIZATION" in _codes(report)


def test_unsupported_alternative_model():
    step = _step(2, alternatives=["Kriging"])
    report = _validate([_plan([_step(1), step, _step(3)])])
    assert "UNSUPPORTED_ALTERNATIVE" in _codes(report)


def test_unsupported_parameter_example():
    step = _step(2, parameters=["lambda=0.1"])
    report = _validate([_plan([_step(1), step, _step(3)])])
    assert "UNSUPPORTED_PARAMETER" in _codes(report)


def test_section5_section7_one_to_one_mirroring():
    plans = [
        _plan([_step(1)], title="模块一"),
        _plan([_step(2)], title="模块二", primary=False),
        _plan([_step(3)], title="模块三", primary=False),
    ]
    report = _validate(plans, section5_fact_clusters=[{"fact-N1"}, {"fact-N2"}, {"fact-N3"}])
    assert "EMBODIMENT_SECTION_MIRRORING" in _codes(report)


def test_primary_embodiment_missing_core_feature():
    plan = _plan([_step(1), _step(2)])
    report = _validate([plan])
    assert "PRIMARY_EMBODIMENT_INCOMPLETE" in _codes(report)


def test_primary_embodiment_broken_step_chain():
    report = _validate([_plan([_step(1), _step(2, inputs=["orphan"]), _step(3)])])
    assert "BROKEN_STEP_CHAIN" in _codes(report)


def test_primary_embodiment_missing_final_output():
    plan = _plan([_step(1), _step(2), _step(3, outputs=[])])
    plan.output_objects = []
    plan.final_technical_result = ""
    report = _validate([plan])
    assert "PRIMARY_OUTPUT_MISSING" in _codes(report)


def test_duplicate_non_distinct_embodiments():
    first = _plan()
    second = _plan(primary=False)
    second.embodiment_id = "EMB-002"
    report = _validate([first, second])
    assert "EMBODIMENT_NOT_DISTINCT" in _codes(report)


def test_valid_single_complete_embodiment():
    assert _validate([_plan()]).status == "PASS"


def test_valid_multiple_materially_distinct_embodiments():
    alternate = _plan(primary=False, title="替代结构的完整实施过程")
    alternate.embodiment_id = "EMB-002"
    alternate.ordered_steps[1].processing = "执行具有实质差异的替代连接操作"
    alternate.ordered_steps[1].fact_ids = ["fact-alt"]
    alternate.ordered_steps[1].evidence_ids = ["ev-alt"]
    alternate.fact_ids.append("fact-alt")
    alternate.evidence_ids.append("ev-alt")
    alternate.material_distinctions = ["alternative connection"]
    assert _validate([_plan(), alternate]).status == "PASS"


def test_claim_feature_missing_embodiment_support():
    features = _features() + [RequiredFeature(feature_id="F4", fact_ids=["fact-N4"], evidence_ids=["ev-N4"])]
    report = _validate([_plan()], required_features=features)
    assert "CLAIM_FEATURE_WITHOUT_EMBODIMENT_SUPPORT" in _codes(report)


def test_ai_model_input_output_scene_link_missing():
    step = _step(2, role=SemanticRole.TECHNICAL_MODULE, outputs=[])
    report = _validate([_plan([_step(1), step, _step(3)])], invention_type="algorithm-software")
    assert "AI_INPUT_OUTPUT_SCENE_LINK_MISSING" in _codes(report)


def test_comparison_baseline_allowed_in_validation():
    registry = _registry(technical_roles=[
        TechnicalRoleEntry(term="BaselineNet", role=TechnicalRole.COMPARISON_BASELINE, evidence_ids=["ev-val"])
    ])
    validation = _step(3, role=SemanticRole.VALIDATION, terms=["BaselineNet"])
    plan = _plan(validation_steps=[validation])
    assert _validate([plan], registry=registry).status == "PASS"


def test_limitation_allowed_as_excluded_scope_not_embodiment():
    plan = _plan()
    plan.excluded_content = ["thermal analysis not evaluated"]
    assert _validate([plan]).status == "PASS"


def test_pending_parameter_not_hallucinated():
    plan = _plan(pending=["lambda value requires inventor confirmation"])
    assert _validate([plan]).status == "PASS"


def test_end_to_end_embodiment_pass():
    report = _validate([_plan()], section5_fact_clusters=[{"fact-N1"}, {"fact-N2"}, {"fact-N3"}])
    assert report.status == "PASS"
    assert report.required_feature_coverage == {"F1": "S1", "F2": "S2", "F3": "S3"}


def test_v7_1_style_fragmented_sixteen_embodiments_fail():
    prohibited = [
        SemanticRole.MACHINE_SPEC, SemanticRole.DATA_REPRESENTATION,
        SemanticRole.TECHNICAL_MODULE, SemanticRole.FORMULA_ONLY,
        SemanticRole.PARAMETER_SET, SemanticRole.EXPERIMENT,
        SemanticRole.VALIDATION_METRIC, SemanticRole.LIMITATION,
    ]
    plans = []
    for index in range(16):
        plan = _plan([_step(1, role=prohibited[index % len(prohibited)])], primary=index == 0)
        plan.embodiment_id = f"EMB-{index + 1:03d}"
        plans.append(plan)
    assert _validate(plans).status == "FAIL"


def _semantic_fact(index: int, category: str, statement: str) -> SemanticFact:
    return SemanticFact(
        fact_id=f"FCT-{index}", category=category, statement=statement,
        evidence_ids=[f"EV-{index}"],
    )


def test_cross_domain_ai_image_detection_planning():
    facts = [
        _semantic_fact(1, "data_acquisition", "Acquire industrial inspection images"),
        _semantic_fact(2, "model_processing", "Process image features with a trained detector"),
        _semantic_fact(3, "technical_output", "Output a defect location and class"),
    ]
    bundle = EvidenceBoundEmbodimentPlanner().plan_from_facts(facts, invention_type="algorithm-software")
    assert bundle.embodiments[0].is_primary and len(bundle.embodiments[0].ordered_steps) == 3


def test_cross_domain_mechanical_device_planning():
    facts = [
        _semantic_fact(1, "component", "Provide a base and a movable clamping member"),
        _semantic_fact(2, "connection", "Connect the clamping member to the base by a guide"),
        _semantic_fact(3, "operation", "Move the clamping member to secure a workpiece"),
    ]
    bundle = EvidenceBoundEmbodimentPlanner().plan_from_facts(facts, invention_type="apparatus-system")
    assert bundle.embodiments[0].final_technical_result


def test_cross_domain_material_process_planning():
    facts = [
        _semantic_fact(1, "raw_material", "Provide precursor A and precursor B"),
        _semantic_fact(2, "process_condition", "Mix and heat the precursors under the disclosed condition"),
        _semantic_fact(3, "product", "Obtain the composite material product"),
    ]
    bundle = EvidenceBoundEmbodimentPlanner().plan_from_facts(facts, invention_type="process-material")
    assert bundle.embodiments[0].output_objects


def test_invention_type_is_inferred_from_current_case_fact_categories():
    facts = [
        _semantic_fact(1, "component", "Provide first and second structural members"),
        _semantic_fact(2, "connection", "Connect the members through a movable joint"),
        _semantic_fact(3, "operation", "Operate the joined members to process a workpiece"),
    ]
    assert infer_invention_type(facts) == "apparatus-system"


def test_reviewed_strategy_evidence_fills_a1_fact_summary_gap():
    understanding = SimpleNamespace(facts=[SimpleNamespace(
        fact_id="F1", category="data", statement="Prepare supported input data",
        evidence_ids=["EV-1"], review_status="LOCKED",
    )], alternatives=[])
    strategy = SimpleNamespace(independent_claim_core=[
        SimpleNamespace(text="Prepare supported input data", evidence_ids=["EV-1"]),
        SimpleNamespace(text="Produce the supported final result", evidence_ids=["EV-2"]),
    ])
    bundle = EvidenceBoundEmbodimentPlanner().plan(understanding, strategy)
    assert "STRATEGY-FEATURE-002" in bundle.embodiments[0].fact_ids
    assert bundle.embodiments[0].evidence_ids == ["EV-1", "EV-2"]


def test_claim_support_can_resolve_evidence_outside_compact_fact_list():
    from patent_agent.v7.disclosure_planner import _collect_evidence_ids
    understanding = SimpleNamespace(
        facts=[SimpleNamespace(evidence_ids=["EV-FACT"])],
        steps=[SimpleNamespace(text=SimpleNamespace(evidence_ids=["EV-STEP"]))],
    )
    assert _collect_evidence_ids(understanding) == {"EV-FACT", "EV-STEP"}


def test_planner_prefers_reviewed_method_chain_over_fact_category_sequence():
    understanding = SimpleNamespace(
        facts=[SimpleNamespace(
            fact_id="F-IMPL", category="implementation",
            statement="Implementation environment detail", evidence_ids=["EV-I"],
            review_status="LOCKED",
        )],
        steps=[
            SimpleNamespace(step_id="STEP-1", text=SimpleNamespace(
                text="Prepare the technical input", evidence_ids=["EV-1"])),
            SimpleNamespace(step_id="STEP-2", text=SimpleNamespace(
                text="Process the input into a candidate", evidence_ids=["EV-2"])),
            SimpleNamespace(step_id="STEP-3", text=SimpleNamespace(
                text="Evaluate the candidate and obtain the final result", evidence_ids=["EV-3"])),
        ],
        inputs=[SimpleNamespace(text="Starting technical object")],
        outputs=[SimpleNamespace(text="Selected technical result")],
        alternatives=[],
    )
    strategy = SimpleNamespace(independent_claim_core=[])
    bundle = EvidenceBoundEmbodimentPlanner().plan(understanding, strategy)
    primary = bundle.embodiments[0]
    assert [step.fact_ids for step in primary.ordered_steps] == [
        ["STEP-1"], ["STEP-2"], ["STEP-3"]]
    assert primary.input_objects == ["Starting technical object"]
    assert primary.output_objects == ["Selected technical result"]


def test_pending_substantive_primary_step_fails_generated_text_gate():
    report = _validate([_plan()], generated_texts=[
        "S3：本步骤的输入、处理及输出待发明人补充。"
    ])
    assert "PRIMARY_EMBODIMENT_INCOMPLETE" in _codes(report)


def test_pending_nonprimary_section_detail_does_not_make_primary_incomplete():
    report = _validate([_plan()], generated_texts=[
        "[SECTION:05-04] 本环节的后续网络输出细节待发明人补充。"
    ])
    assert "PRIMARY_EMBODIMENT_INCOMPLETE" not in _codes(report)


def test_generated_multiphysics_prediction_requires_source_support():
    report = _validate([_plan()], generated_texts=[
        "该代理模型用于电磁、热等多物理场性能预测。"
    ])
    assert "UNSUPPORTED_GENERALIZATION" in _codes(report)


def test_source_supported_multiphysics_prediction_is_not_fixed_lexicon_blocked():
    registry = _registry(source_texts=["该方法执行电磁、热等多物理场性能预测。"])
    report = _validate([_plan()], registry=registry, generated_texts=[
        "该方法执行电磁、热等多物理场性能预测。"
    ])
    assert "UNSUPPORTED_GENERALIZATION" not in _codes(report)


def test_generated_unsupported_dimensionality_fails():
    report = _validate([_plan()], generated_texts=[
        "[SECTION:07-01] S1：采用三维参数化模板处理输入。"
    ])
    assert "UNSUPPORTED_PARAMETER" in _codes(report)


def test_final_step_cannot_claim_a_nonexistent_downstream_step():
    report = _validate([_plan()], generated_texts=[
        "[SECTION:07-01] S3：获得最终输出，并将其作为后续步骤的输入。"
    ])
    assert "PRIMARY_EMBODIMENT_INCOMPLETE" in _codes(report)


def test_reviewed_training_branch_is_ordered_before_candidate_generation():
    understanding = SimpleNamespace(
        facts=[], alternatives=[], inputs=[], outputs=[],
        steps=[
            SimpleNamespace(step_id="GEN", text=SimpleNamespace(
                text="Generate candidate objects", evidence_ids=["EV-G"])),
            SimpleNamespace(step_id="TRAIN", text=SimpleNamespace(
                text="Train the predictor on the prepared dataset", evidence_ids=["EV-T"])),
        ],
    )
    bundle = EvidenceBoundEmbodimentPlanner().plan(
        understanding, SimpleNamespace(independent_claim_core=[]))
    assert [step.fact_ids for step in bundle.embodiments[0].ordered_steps] == [["TRAIN"], ["GEN"]]


def test_background_domain_qualifier_is_removed_only_when_source_absent():
    from patent_agent.v7.disclosure_planner import _remove_unsupported_domain_expansion
    text = "采用有限元进行多物理场性能评估。"
    assert _remove_unsupported_domain_expansion(text, "finite-element evaluation") == "采用有限元进行性能评估。"
    assert _remove_unsupported_domain_expansion(text, "multiphysics evaluation") == text


def test_offline_search_output_cannot_be_promoted_to_control_strategy():
    report = _validate([_plan()], generated_texts=[
        "[SECTION:07-01] S2：离线搜索得到最优控制策略。"
    ])
    assert "SCENARIO_DRIFT" in _codes(report)


def test_generated_parameter_must_match_paragraph_local_evidence():
    registry = _registry(source_texts=["Another section mentions π/4."])
    report = _validate([_plan()], registry=registry, generated_texts=[{
        "text": "[SECTION:05-02] 本环节采用π/4和π/8。",
        "source_text": "This paragraph supports a half pole pitch without exact radians.",
    }])
    assert "UNSUPPORTED_PARAMETER" in _codes(report)


def test_generated_parameter_passes_when_local_evidence_supports_it():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:05-02] 图像尺寸为512×512像素。",
        "source_text": "Topology images are 512x512 pixels.",
    }])
    assert "UNSUPPORTED_PARAMETER" not in _codes(report)


def test_embodiment_step_number_is_not_treated_as_parameter():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:07-01] S3：训练模型并输出潜在样本。",
        "source_text": "Train the model and output latent samples.",
    }])
    assert "UNSUPPORTED_PARAMETER" not in _codes(report)


def test_generated_downstream_training_relation_requires_local_evidence():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:07-01] S3：所得样本用于后续FiLM模型训练。",
        "source_text": "Train flow matching to generate new latent samples.",
    }])
    assert "UNSUPPORTED_GENERALIZATION" in _codes(report)


def test_parameter_punctuation_variation_does_not_create_false_failure():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:05-08] 目标工况为8000 r/min。",
        "source_text": "the 8000-r/min target condition",
    }])
    assert "UNSUPPORTED_PARAMETER" not in _codes(report)


def test_ratio_cannot_be_silently_converted_to_derived_percentages():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:05-09] 按7:2:1划分，即70%、20%和10%。",
        "source_text": "The dataset is split at a ratio of 7:2:1.",
    }])
    assert "UNSUPPORTED_PARAMETER" in _codes(report)


def test_speculative_option_remains_unsupported_when_marked_pending():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:05-08] 设计向量可包含绕组配置等参数，具体组成待发明人补充。",
        "source_text": "The outer-loop objective uses a design vector u.",
    }])
    assert "UNSUPPORTED_ALTERNATIVE" in _codes(report)


def test_two_dimensional_pixel_matrix_is_supported_by_image_evidence():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:05-02] 采用512×512像素的二维图像矩阵。",
        "source_text": "Topology images use a 512x512 pixel representation.",
    }])
    assert "UNSUPPORTED_PARAMETER" not in _codes(report)


def test_period_qualifier_is_aligned_to_local_evidence():
    assert _align_period_qualifier(
        "在完整60°电周期内评估。", "complete 60 degree mechanical period"
    ) == "在完整60°机械周期内评估。"


def test_specific_target_condition_cannot_expand_to_full_speed_range():
    report = _validate([_plan()], generated_texts=[{
        "text": "[SECTION:05-08] 该约束保证设计在全转速范围内均可行。",
        "source_text": "The constraint applies at the 8000-r/min target condition.",
    }])
    assert "UNSUPPORTED_GENERALIZATION" in _codes(report)


def test_experiments_become_validation_steps_not_primary_steps():
    grounded = lambda text, evidence: SimpleNamespace(
        text=text, evidence_ids=evidence, review_status="ACCEPTED")
    understanding = SimpleNamespace(
        facts=[],
        steps=[SimpleNamespace(step_id="step-1", text=grounded("Process input into output.", ["ev-core"]))],
        experiments=[grounded("Validate the output against an independent test.", ["ev-val"])],
        alternatives=[], inputs=[], outputs=[], parameters=[], equations=[],
        technical_field=[], technical_problems=[], system_overview=[], components=[],
        data_flows=[], control_flows=[], technical_effects=[], uncertainties=[],
    )
    strategy = SimpleNamespace(independent_claim_core=[])
    bundle = EvidenceBoundEmbodimentPlanner().plan(understanding, strategy)
    assert len(bundle.embodiments[0].ordered_steps) == 1
    assert len(bundle.embodiments[0].validation_steps) == 1
    assert bundle.embodiments[0].validation_steps[0].semantic_role == SemanticRole.VALIDATION


def test_whole_source_context_keeps_late_pages_and_excludes_references():
    chunks = [
        SimpleNamespace(evidence_id="early", section_title="Method", page=1,
                        block_type="paragraph", raw_text="early method"),
        SimpleNamespace(evidence_id="late", section_title="Validation", page=12,
                        block_type="paragraph", raw_text="late validation"),
        SimpleNamespace(evidence_id="ref", section_title="References", page=13,
                        block_type="paragraph", raw_text="citation noise"),
    ]
    store = SimpleNamespace(all=lambda scope: chunks)
    context = _retrieve_task_context(store, max_chars=1000)
    ids = {item["evidence_id"] for item in context["evidence"]}
    assert ids == {"early", "late"}
