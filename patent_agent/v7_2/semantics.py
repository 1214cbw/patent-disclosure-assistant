"""Evidence-bound invention graph and embodiment semantics.

This module deliberately contains no case names or domain-specific branching.
It converts source-declared fact roles into an invention graph, plans complete
implementation paths, and validates patent semantics independently from Word
layout and language quality.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field


class SemanticRole(str, Enum):
    SCENARIO = "SCENARIO"
    TECHNICAL_STEP = "TECHNICAL_STEP"
    TECHNICAL_MODULE = "TECHNICAL_MODULE"
    DATA_REPRESENTATION = "DATA_REPRESENTATION"
    PARAMETER_SET = "PARAMETER_SET"
    MACHINE_SPEC = "MACHINE_SPEC"
    FORMULA_ONLY = "FORMULA_ONLY"
    CONSTRAINT = "CONSTRAINT"
    EXPERIMENT = "EXPERIMENT"
    VALIDATION = "VALIDATION"
    VALIDATION_METRIC = "VALIDATION_METRIC"
    LIMITATION = "LIMITATION"


class ScenarioRole(str, Enum):
    DESIGN = "DESIGN"
    TRAINING = "TRAINING"
    OFFLINE_OPTIMIZATION = "OFFLINE_OPTIMIZATION"
    ONLINE_INFERENCE = "ONLINE_INFERENCE"
    ONLINE_CONTROL = "ONLINE_CONTROL"
    PHYSICAL_OPERATION = "PHYSICAL_OPERATION"
    MANUFACTURING = "MANUFACTURING"
    MATERIAL_PROCESSING = "MATERIAL_PROCESSING"
    VALIDATION = "VALIDATION"


class TechnicalRole(str, Enum):
    INVENTION_CORE = "INVENTION_CORE"
    OPTIONAL_EMBODIMENT = "OPTIONAL_EMBODIMENT"
    COMPARISON_BASELINE = "COMPARISON_BASELINE"
    PRIOR_ART = "PRIOR_ART"
    VALIDATION_ONLY = "VALIDATION_ONLY"
    EXPERIMENT_ONLY = "EXPERIMENT_ONLY"
    EXTERNAL_TOOL = "EXTERNAL_TOOL"


class SemanticFact(BaseModel):
    fact_id: str
    category: str
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)


class RequiredFeature(BaseModel):
    feature_id: str
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    text: str = ""


class TechnicalRoleEntry(BaseModel):
    term: str
    role: TechnicalRole
    evidence_ids: list[str] = Field(default_factory=list)


class SemanticRegistry(BaseModel):
    supported_scenarios: list[ScenarioRole] = Field(default_factory=list)
    technical_roles: list[TechnicalRoleEntry] = Field(default_factory=list)
    supported_alternatives: list[str] = Field(default_factory=list)
    supported_parameters: list[str] = Field(default_factory=list)
    source_texts: list[str] = Field(default_factory=list)
    source_terms: list[str] = Field(default_factory=list)


class InventionNode(BaseModel):
    node_id: str
    semantic_role: SemanticRole
    fact_ids: list[str]
    input_types: list[str]
    output_types: list[str]
    required: bool = True
    evidence_ids: list[str]
    required_feature_ids: list[str] = Field(default_factory=list)
    scenario: ScenarioRole = ScenarioRole.DESIGN
    technical_terms: list[str] = Field(default_factory=list)
    statement: str = ""


class InventionEdge(BaseModel):
    source: str
    target: str
    data_or_control_flow: str
    evidence_ids: list[str] = Field(default_factory=list)


class InventionCoreGraph(BaseModel):
    nodes: list[InventionNode]
    edges: list[InventionEdge]
    input_objects: list[str]
    output_objects: list[str]
    required_feature_ids: list[str] = Field(default_factory=list)


class EmbodimentStep(BaseModel):
    step_id: str
    title: str
    purpose: str
    inputs: list[str]
    processing: str
    outputs: list[str]
    fact_ids: list[str]
    evidence_ids: list[str]
    next_step: str | None = None
    scenario: ScenarioRole
    semantic_role: SemanticRole
    required_feature_ids: list[str] = Field(default_factory=list)
    technical_terms: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)


class EmbodimentPlan(BaseModel):
    embodiment_id: str
    title: str
    embodiment_type: str
    is_primary: bool
    scenario: ScenarioRole
    input_objects: list[str]
    output_objects: list[str]
    ordered_steps: list[EmbodimentStep]
    required_feature_ids: list[str] = Field(default_factory=list)
    supporting_feature_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    equations: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    validation_steps: list[EmbodimentStep] = Field(default_factory=list)
    alternative_features: list[str] = Field(default_factory=list)
    excluded_content: list[str] = Field(default_factory=list)
    pending_confirmations: list[str] = Field(default_factory=list)
    material_distinctions: list[str] = Field(default_factory=list)
    final_technical_result: str = ""
    completeness_status: str = "PENDING"


class SemanticPlanningBundle(BaseModel):
    graph: InventionCoreGraph
    embodiments: list[EmbodimentPlan]
    required_features: list[RequiredFeature]
    registry: SemanticRegistry
    section5_fact_clusters: list[set[str]] = Field(default_factory=list)
    invention_type: str = "method"


class SemanticFinding(BaseModel):
    code: str
    message: str
    embodiment_id: str = ""
    step_id: str = ""
    severity: str = "HARD"


class PatentSemanticsReport(BaseModel):
    status: str
    findings: list[SemanticFinding]
    component_status: dict[str, str]
    required_feature_coverage: dict[str, str] = Field(default_factory=dict)
    unresolved_hard_drift: int = 0


_PROHIBITED_STANDALONE = {
    SemanticRole.FORMULA_ONLY,
    SemanticRole.PARAMETER_SET,
    SemanticRole.MACHINE_SPEC,
    SemanticRole.EXPERIMENT,
    SemanticRole.VALIDATION,
    SemanticRole.VALIDATION_METRIC,
    SemanticRole.LIMITATION,
    SemanticRole.CONSTRAINT,
    SemanticRole.DATA_REPRESENTATION,
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", value.lower())


def _latin_terms(text: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        if token.lower() not in {"the", "and", "for", "with", "from", "into", "using"}
    }


def _parameters(text: str) -> set[str]:
    return {
        re.sub(r"\s+", "", item.lower())
        for item in re.findall(
            r"(?:[A-Za-z_λ][A-Za-z0-9_λ-]*\s*[=:]\s*)?[-+]?\d+(?:\.\d+)?(?:\s*(?:%|×\d+|[A-Za-z/]+))?",
            text,
        )
        if item.strip()
    }


def _semantic_strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "__dict__"):
        value = vars(value)
    if isinstance(value, dict):
        return [text for item in value.values() for text in _semantic_strings(item)]
    if isinstance(value, (list, tuple, set)):
        return [text for item in value for text in _semantic_strings(item)]
    return []


def _method_stage(statement: str) -> int:
    """Order reviewed method steps by generic dependency role, stably."""
    text = statement.lower()
    if any(term in text for term in ("prepare", "construct", "acquire", "collect", "parameterize")):
        return 10
    if any(term in text for term in ("train", "calibrate", "fit")):
        return 20
    if any(term in text for term in ("generate", "synthesize", "produce candidate")):
        return 30
    if any(term in text for term in ("search", "evaluate", "calculate", "measure", "screen")):
        return 40
    if any(term in text for term in ("optimize", "pareto", "select final")):
        return 50
    return 35


def enrich_registry(bundle: SemanticPlanningBundle, source_texts: Iterable[str]) -> None:
    """Add current raw evidence to a case-local semantic registry in place."""
    texts = [str(text) for text in source_texts if str(text).strip()]
    bundle.registry.source_texts = list(dict.fromkeys(bundle.registry.source_texts + texts))
    bundle.registry.supported_parameters = sorted(set(bundle.registry.supported_parameters) | set().union(*(
        _parameters(text) for text in texts
    )))
    bundle.registry.source_terms = sorted(set(bundle.registry.source_terms) | set().union(*(
        _latin_terms(text) for text in texts
    )))


def _role_for_category(category: str) -> SemanticRole:
    key = _norm(category)
    patterns: list[tuple[tuple[str, ...], SemanticRole]] = [
        (("limitation", "boundary", "caveat", "scope"), SemanticRole.LIMITATION),
        (("benchmark", "comparison", "metric"), SemanticRole.VALIDATION_METRIC),
        (("experiment", "testsetup", "validation", "training"), SemanticRole.EXPERIMENT),
        (("loss", "formula", "equation", "mathematical"), SemanticRole.FORMULA_ONLY),
        (("machinespec", "devicespec", "materialspec"), SemanticRole.MACHINE_SPEC),
        (("parameter", "hyperparameter", "specification", "processcondition"), SemanticRole.PARAMETER_SET),
        (("constraint",), SemanticRole.CONSTRAINT),
        (("representation", "encoding", "preprocess"), SemanticRole.DATA_REPRESENTATION),
        (("architecture", "network", "component", "module", "connection"), SemanticRole.TECHNICAL_MODULE),
        (("context", "scenario", "application"), SemanticRole.SCENARIO),
    ]
    for tokens, role in patterns:
        if any(token in key for token in tokens):
            return role
    return SemanticRole.TECHNICAL_STEP


def infer_invention_type(facts: Iterable[SemanticFact]) -> str:
    """Infer a broad implementation architecture from source-declared fact roles.

    The decision is intentionally category/evidence driven.  It contains no
    case names, named model families, or application-domain vocabulary.
    """
    scores = {
        "algorithm-software": 0,
        "apparatus-system": 0,
        "process-material": 0,
    }
    for fact in facts:
        key = _norm(fact.category)
        if any(token in key for token in (
            "algorithm", "software", "model", "network", "architecture",
            "dataset", "datarepresentation", "encoding", "inference",
        )):
            scores["algorithm-software"] += 2
        if any(token in key for token in (
            "apparatus", "device", "component", "connection", "assembly",
            "hardware", "structure", "operation",
        )):
            scores["apparatus-system"] += 2
        if any(token in key for token in (
            "material", "rawmaterial", "precursor", "composition", "product",
            "processcondition", "manufacturing", "fabrication", "preparation",
        )):
            scores["process-material"] += 2
    best = max(scores, key=scores.get)
    return best if scores[best] else "method"


def _scenario_for(category: str, statement: str, invention_type: str) -> ScenarioRole:
    text = f"{category} {statement}".lower()
    category_key = _norm(category)
    if any(term in category_key for term in ("dataset", "training", "loss")):
        return ScenarioRole.TRAINING
    if any(term in category_key for term in ("optimization", "constraint")):
        return ScenarioRole.OFFLINE_OPTIMIZATION
    if any(term in text for term in ("validation", "experiment", "benchmark", "test set")):
        return ScenarioRole.VALIDATION
    if any(term in text for term in ("manufactur", "assembly", "fabricat")):
        return ScenarioRole.MANUFACTURING
    if invention_type == "process-material":
        return ScenarioRole.MATERIAL_PROCESSING
    if any(term in text for term in ("train", "dataset", "loss")):
        return ScenarioRole.TRAINING
    if any(term in text for term in ("optimization", "design", "candidate")):
        return ScenarioRole.OFFLINE_OPTIMIZATION
    if invention_type == "apparatus-system":
        return ScenarioRole.PHYSICAL_OPERATION
    return ScenarioRole.DESIGN


class EvidenceBoundEmbodimentPlanner:
    """Create one complete primary implementation before considering variants."""

    def plan_from_facts(
        self,
        facts: list[SemanticFact],
        required_features: list[RequiredFeature] | None = None,
        invention_type: str = "method",
        supported_alternatives: list[str] | None = None,
        input_objects: list[str] | None = None,
        output_objects: list[str] | None = None,
    ) -> SemanticPlanningBundle:
        required_features = required_features or [
            RequiredFeature(
                feature_id=f"RF-{index:03d}", fact_ids=[fact.fact_id],
                evidence_ids=fact.evidence_ids, text=fact.statement,
            )
            for index, fact in enumerate(facts, 1)
            if _role_for_category(fact.category) not in {
                SemanticRole.EXPERIMENT, SemanticRole.VALIDATION_METRIC,
                SemanticRole.LIMITATION,
            }
        ]
        feature_by_fact: dict[str, list[str]] = {}
        for feature in required_features:
            for fact_id in feature.fact_ids:
                feature_by_fact.setdefault(fact_id, []).append(feature.feature_id)
        required_fact_ids = set(feature_by_fact)

        source_texts = [fact.statement for fact in facts]
        source_terms = sorted(set().union(*(_latin_terms(text) for text in source_texts)))
        supported_parameters = sorted(set().union(*(_parameters(text) for text in source_texts)))
        supported_scenarios = sorted({
            _scenario_for(fact.category, fact.statement, invention_type) for fact in facts
        }, key=lambda item: item.value)

        nodes: list[InventionNode] = []
        validation_steps: list[EmbodimentStep] = []
        excluded: list[str] = []
        pending_support: list[SemanticFact] = []
        for fact in facts:
            role = _role_for_category(fact.category)
            # A source-declared training/validation fact becomes an invention
            # step only when a required feature is actually grounded on it.
            if role == SemanticRole.EXPERIMENT and fact.fact_id in required_fact_ids:
                role = SemanticRole.TECHNICAL_STEP
            scenario = _scenario_for(fact.category, fact.statement, invention_type)
            if role == SemanticRole.LIMITATION:
                excluded.append(fact.statement)
                continue
            if role in {SemanticRole.EXPERIMENT, SemanticRole.VALIDATION_METRIC}:
                index = len(validation_steps) + 1
                validation_steps.append(EmbodimentStep(
                    step_id=f"V{index}", title=f"验证步骤{index}", purpose="验证技术结果",
                    inputs=[nodes[-1].output_types[0] if nodes else "待验证对象"],
                    processing=fact.statement, outputs=[f"validation-{index}"],
                    fact_ids=[fact.fact_id], evidence_ids=fact.evidence_ids,
                    scenario=ScenarioRole.VALIDATION, semantic_role=SemanticRole.VALIDATION,
                    technical_terms=sorted(_latin_terms(fact.statement)),
                    parameters=sorted(_parameters(fact.statement)),
                ))
                continue
            if role in {SemanticRole.SCENARIO, SemanticRole.MACHINE_SPEC}:
                pending_support.append(fact)
                continue
            if role in {SemanticRole.FORMULA_ONLY, SemanticRole.PARAMETER_SET, SemanticRole.CONSTRAINT} and nodes:
                node = nodes[-1]
                node.fact_ids.append(fact.fact_id)
                node.evidence_ids = sorted(set(node.evidence_ids + fact.evidence_ids))
                node.statement += "\n" + fact.statement
                node.technical_terms = sorted(set(node.technical_terms) | _latin_terms(fact.statement))
                node.required_feature_ids = sorted(set(node.required_feature_ids + feature_by_fact.get(fact.fact_id, [])))
                continue

            grouped = pending_support + [fact]
            pending_support = []
            node_index = len(nodes) + 1
            previous_output = nodes[-1].output_types[0] if nodes else "technical-input"
            output = f"intermediate-{node_index}"
            node = InventionNode(
                node_id=f"N{node_index}", semantic_role=role,
                fact_ids=[item.fact_id for item in grouped],
                evidence_ids=sorted({ev for item in grouped for ev in item.evidence_ids}),
                input_types=[previous_output], output_types=[output], required=True,
                required_feature_ids=sorted({
                    feature for item in grouped for feature in feature_by_fact.get(item.fact_id, [])
                }),
                scenario=scenario,
                technical_terms=sorted(set().union(*(_latin_terms(item.statement) for item in grouped))),
                statement="\n".join(item.statement for item in grouped),
            )
            nodes.append(node)

        if pending_support and nodes:
            nodes[0].fact_ids = [item.fact_id for item in pending_support] + nodes[0].fact_ids
            nodes[0].evidence_ids = sorted(set(nodes[0].evidence_ids) | {
                ev for item in pending_support for ev in item.evidence_ids
            })
            nodes[0].statement = "\n".join(item.statement for item in pending_support) + "\n" + nodes[0].statement

        if not nodes and facts:
            fact = facts[0]
            nodes.append(InventionNode(
                node_id="N1", semantic_role=SemanticRole.TECHNICAL_STEP,
                fact_ids=[fact.fact_id], evidence_ids=fact.evidence_ids,
                input_types=["technical-input"], output_types=["technical-output"],
                required=True, required_feature_ids=feature_by_fact.get(fact.fact_id, []),
                scenario=_scenario_for(fact.category, fact.statement, invention_type),
                technical_terms=sorted(_latin_terms(fact.statement)), statement=fact.statement,
            ))

        if nodes:
            nodes[-1].output_types = list(output_objects or ["final-technical-result"])
        edges = [
            InventionEdge(
                source=nodes[index].node_id, target=nodes[index + 1].node_id,
                data_or_control_flow=nodes[index].output_types[0],
                evidence_ids=nodes[index + 1].evidence_ids,
            )
            for index in range(len(nodes) - 1)
        ]
        for index in range(1, len(nodes)):
            nodes[index].input_types = list(nodes[index - 1].output_types)

        steps = [
            EmbodimentStep(
                step_id=f"S{index}", title=f"执行{node.semantic_role.value.lower()}",
                purpose="沿发明核心图执行受证据支持的技术操作",
                inputs=node.input_types, processing=node.statement, outputs=node.output_types,
                fact_ids=node.fact_ids, evidence_ids=node.evidence_ids,
                next_step=f"S{index + 1}" if index < len(nodes) else None,
                scenario=node.scenario, semantic_role=node.semantic_role,
                required_feature_ids=node.required_feature_ids,
                technical_terms=node.technical_terms,
                parameters=sorted(set().union(*(
                    _parameters(text) for text in node.statement.splitlines()
                ))),
            )
            for index, node in enumerate(nodes, 1)
        ]
        scenario = steps[0].scenario if steps else ScenarioRole.DESIGN
        title_by_type = {
            "apparatus-system": "技术装置的完整组装与运行实施过程",
            "process-material": "材料制备方法的完整实施过程",
            "algorithm-software": "算法技术方案的完整实施过程",
        }
        primary = EmbodimentPlan(
            embodiment_id="EMB-001", title=title_by_type.get(invention_type, "技术方法的完整实施过程"),
            embodiment_type=invention_type, is_primary=True, scenario=scenario,
            input_objects=list(input_objects or (nodes[0].input_types if nodes else [])),
            output_objects=list(output_objects or (nodes[-1].output_types if nodes else [])),
            ordered_steps=steps,
            required_feature_ids=[item.feature_id for item in required_features],
            fact_ids=sorted({fact_id for node in nodes for fact_id in node.fact_ids}),
            evidence_ids=sorted({ev for node in nodes for ev in node.evidence_ids}),
            validation_steps=validation_steps, excluded_content=excluded,
            final_technical_result=(output_objects or nodes[-1].output_types)[0] if nodes else "",
        )
        graph = InventionCoreGraph(
            nodes=nodes, edges=edges,
            input_objects=primary.input_objects, output_objects=primary.output_objects,
            required_feature_ids=primary.required_feature_ids,
        )
        core_terms = sorted({term for node in nodes for term in node.technical_terms})
        validation_terms = sorted({term for step in validation_steps for term in step.technical_terms})
        registry = SemanticRegistry(
            supported_scenarios=supported_scenarios,
            technical_roles=[
                TechnicalRoleEntry(term=term, role=TechnicalRole.INVENTION_CORE)
                for term in core_terms
            ] + [
                TechnicalRoleEntry(term=term, role=TechnicalRole.COMPARISON_BASELINE)
                for term in validation_terms if term not in core_terms
            ],
            supported_alternatives=supported_alternatives or [],
            supported_parameters=supported_parameters,
            source_texts=source_texts, source_terms=core_terms,
        )
        return SemanticPlanningBundle(
            graph=graph, embodiments=[primary], required_features=required_features,
            registry=registry,
            section5_fact_clusters=[{fact.fact_id} for fact in facts],
            invention_type=invention_type,
        )

    def plan(self, understanding, strategy, invention_type: str | None = None) -> SemanticPlanningBundle:
        understanding_facts = [
            SemanticFact(
                fact_id=str(fact.fact_id), category=str(fact.category),
                statement=str(fact.statement), evidence_ids=list(fact.evidence_ids),
            )
            for fact in getattr(understanding, "facts", [])
            if str(getattr(fact, "review_status", "")) != "ReviewStatus.REJECTED"
            and str(getattr(fact, "review_status", "")) != "REJECTED"
        ]
        method_steps = list(getattr(understanding, "steps", []) or [])
        facts = [
            SemanticFact(
                fact_id=str(getattr(step, "step_id", f"METHOD-STEP-{index:03d}")),
                category="technical_step",
                statement=str(getattr(getattr(step, "text", step), "text", getattr(step, "text", step))),
                evidence_ids=list(getattr(getattr(step, "text", step), "evidence_ids", []) or []),
            )
            for index, step in enumerate(method_steps, 1)
        ] or understanding_facts
        if method_steps:
            facts = sorted(facts, key=lambda fact: _method_stage(fact.statement))
        required: list[RequiredFeature] = []
        for index, statement in enumerate(getattr(strategy, "independent_claim_core", []) or [], 1):
            evidence_ids = list(getattr(statement, "evidence_ids", []) or [])
            fact_ids = [
                fact.fact_id for fact in facts if set(fact.evidence_ids) & set(evidence_ids)
            ]
            # A reviewed strategy feature may be grounded directly in source
            # evidence that the A1 summarizer did not promote into its compact
            # fact list.  Preserve that supported feature as a graph fact
            # instead of declaring it unsupported or inventing missing prose.
            if not fact_ids and evidence_ids:
                derived_id = f"STRATEGY-FEATURE-{index:03d}"
                facts.append(SemanticFact(
                    fact_id=derived_id,
                    category="required_feature",
                    statement=str(getattr(statement, "text", "")),
                    evidence_ids=evidence_ids,
                ))
                fact_ids = [derived_id]
            required.append(RequiredFeature(
                feature_id=f"RF-{index:03d}", fact_ids=fact_ids,
                evidence_ids=evidence_ids, text=str(getattr(statement, "text", "")),
            ))
        alternatives = [
            str(getattr(item, "text", "")) for item in getattr(understanding, "alternatives", []) or []
            if getattr(item, "evidence_ids", None)
        ]
        resolved_type = invention_type or infer_invention_type(understanding_facts or facts)
        inputs = [str(getattr(item, "text", item)) for item in getattr(understanding, "inputs", []) or []]
        outputs = [str(getattr(item, "text", item)) for item in getattr(understanding, "outputs", []) or []]
        bundle = self.plan_from_facts(
            facts, required or None, resolved_type, alternatives,
            input_objects=inputs or None, output_objects=outputs or None,
        )
        bundle.section5_fact_clusters = [{fact.fact_id} for fact in understanding_facts]
        enrich_registry(bundle, _semantic_strings(understanding))
        return bundle


class PatentSemanticsValidator:
    """Aggregate hard semantic gates for embodiments and supporting roles."""

    def validate(
        self,
        embodiments: list[EmbodimentPlan],
        graph: InventionCoreGraph,
        required_features: list[RequiredFeature],
        registry: SemanticRegistry,
        section5_fact_clusters: list[set[str]] | None = None,
        invention_type: str = "method",
        generated_texts: list[str] | None = None,
    ) -> PatentSemanticsReport:
        findings: list[SemanticFinding] = []
        primary = [item for item in embodiments if item.is_primary]
        if len(primary) != 1:
            findings.append(SemanticFinding(
                code="PRIMARY_EMBODIMENT_COUNT_INVALID",
                message="Exactly one primary embodiment is required.",
            ))
        target = primary[0] if primary else None

        for plan in embodiments:
            roles = {step.semantic_role for step in plan.ordered_steps}
            if plan.ordered_steps and roles <= _PROHIBITED_STANDALONE:
                findings.append(SemanticFinding(
                    code="PROHIBITED_EMBODIMENT_ROLE",
                    message="A supporting semantic role cannot independently form an embodiment.",
                    embodiment_id=plan.embodiment_id,
                ))

        coverage: dict[str, str] = {}
        if target:
            for feature in required_features:
                step = next((step for step in target.ordered_steps if (
                    feature.feature_id in step.required_feature_ids
                    or set(feature.fact_ids) & set(step.fact_ids)
                    or set(feature.evidence_ids) & set(step.evidence_ids)
                )), None)
                if step:
                    coverage[feature.feature_id] = step.step_id
                else:
                    findings.append(SemanticFinding(
                        code="CLAIM_FEATURE_WITHOUT_EMBODIMENT_SUPPORT",
                        message=f"Required feature {feature.feature_id} has no primary-embodiment step.",
                        embodiment_id=target.embodiment_id,
                    ))
            graph_fact_ids = {fact for node in graph.nodes if node.required for fact in node.fact_ids}
            covered_fact_ids = {fact for step in target.ordered_steps for fact in step.fact_ids}
            if (set(item.feature_id for item in required_features) - set(coverage)
                    or graph_fact_ids - covered_fact_ids):
                findings.append(SemanticFinding(
                    code="PRIMARY_EMBODIMENT_INCOMPLETE",
                    message="The primary embodiment does not cover the required invention graph.",
                    embodiment_id=target.embodiment_id,
                ))

            if not target.input_objects or not target.ordered_steps:
                findings.append(SemanticFinding(
                    code="PRIMARY_INPUT_MISSING", message="Primary input is not defined.",
                    embodiment_id=target.embodiment_id,
                ))
            if not target.output_objects or not target.final_technical_result or not target.ordered_steps[-1].outputs:
                findings.append(SemanticFinding(
                    code="PRIMARY_OUTPUT_MISSING", message="Final technical output is not defined.",
                    embodiment_id=target.embodiment_id,
                ))

            for index, step in enumerate(target.ordered_steps):
                if not step.evidence_ids or not step.fact_ids:
                    findings.append(SemanticFinding(
                        code="EVIDENCE_SUPPORT_MISSING", message="Substantive step lacks fact/evidence support.",
                        embodiment_id=target.embodiment_id, step_id=step.step_id,
                    ))
                if index:
                    previous = target.ordered_steps[index - 1]
                    if not set(previous.outputs) & set(step.inputs):
                        findings.append(SemanticFinding(
                            code="BROKEN_STEP_CHAIN", message="Step input is not produced upstream.",
                            embodiment_id=target.embodiment_id, step_id=step.step_id,
                        ))
                if index < len(target.ordered_steps) - 1:
                    expected = target.ordered_steps[index + 1].step_id
                    if step.next_step != expected:
                        findings.append(SemanticFinding(
                            code="BROKEN_STEP_CHAIN", message="next_step does not match ordered flow.",
                            embodiment_id=target.embodiment_id, step_id=step.step_id,
                        ))

        supported_scenarios = set(registry.supported_scenarios)
        role_map = {_norm(item.term): item.role for item in registry.technical_roles}
        source_terms = {_norm(item) for item in registry.source_terms}
        supported_alternatives = {_norm(item) for item in registry.supported_alternatives}
        supported_parameters = {_norm(item) for item in registry.supported_parameters}
        expansion_patterns = [
            re.compile(r"图像[、,，]文本|文本[、,，]音频|其它类型的数据|其他类型的数据|任意(?:类型的)?数据"),
            re.compile(r"(?:电磁|力学|热)[、,，](?:电磁|力学|热).{0,8}多物理场|多物理场(?:性能)?(?:预测|约束|推断|评估)"),
            re.compile(r"(?:电磁|热|机械|力学)(?:或|、|，)(?:电磁|热|机械|力学)性能(?:预测|推断|评估)"),
            re.compile(r"(?:二值|连续)[、,，或/]*(?:梯度|连续|二值).{0,8}(?:图|输出|结构)"),
            re.compile(r"二值(?:像素|图像|表示)"),
            re.compile(r"以.{0,30}(?:目标|需求).{0,15}为条件.{0,20}(?:生成|解码)"),
        ]
        source_joined = "\n".join(registry.source_texts)
        source_parameter_text = re.sub(r"[\s,，]", "", source_joined.lower()).replace("×", "x")
        dimension_aliases = {
            "二维": ("二维", "2d", "2-d", "two-dimensional"),
            "三维": ("三维", "3d", "3-d", "three-dimensional"),
        }

        def unsupported_expansion(text: str) -> bool:
            return any(pattern.search(text) and not pattern.search(source_joined)
                       for pattern in expansion_patterns)
        online_pattern = re.compile(r"实时(?:采集|控制|获取)|每(?:个|次)控制周期|位置传感器|观测器")
        control_promotion_pattern = re.compile(r"最优控制策略|在线控制策略|控制器")
        alternative_pattern = re.compile(r"可采用|可以采用|可选用|典型取值|例如")

        for plan in embodiments:
            for step in plan.ordered_steps:
                if step.scenario not in supported_scenarios:
                    findings.append(SemanticFinding(
                        code="SCENARIO_DRIFT", message=f"Unsupported scenario: {step.scenario.value}",
                        embodiment_id=plan.embodiment_id, step_id=step.step_id,
                    ))
                if unsupported_expansion(step.processing):
                    findings.append(SemanticFinding(
                        code="UNSUPPORTED_GENERALIZATION", message="Cross-domain data expansion is unsupported.",
                        embodiment_id=plan.embodiment_id, step_id=step.step_id,
                    ))
                if online_pattern.search(step.processing) and ScenarioRole.ONLINE_CONTROL not in supported_scenarios:
                    findings.append(SemanticFinding(
                        code="SCENARIO_DRIFT", message="Online-control language is outside the case scenario.",
                        embodiment_id=plan.embodiment_id, step_id=step.step_id,
                    ))
                for term in step.technical_terms:
                    normalized = _norm(term)
                    role = role_map.get(normalized)
                    if role == TechnicalRole.COMPARISON_BASELINE:
                        findings.append(SemanticFinding(
                            code="BASELINE_PROMOTED_TO_INVENTION",
                            message=f"Comparison baseline {term} appears in a required step.",
                            embodiment_id=plan.embodiment_id, step_id=step.step_id,
                        ))
                    elif normalized not in role_map and normalized not in source_terms:
                        findings.append(SemanticFinding(
                            code="UNSUPPORTED_GENERALIZATION",
                            message=f"Unsupported technical component: {term}",
                            embodiment_id=plan.embodiment_id, step_id=step.step_id,
                        ))
                for alternative in step.alternatives:
                    if _norm(alternative) not in supported_alternatives:
                        findings.append(SemanticFinding(
                            code="UNSUPPORTED_ALTERNATIVE", message=f"Unsupported alternative: {alternative}",
                            embodiment_id=plan.embodiment_id, step_id=step.step_id,
                        ))
                for parameter in step.parameters:
                    if _norm(parameter) not in supported_parameters:
                        findings.append(SemanticFinding(
                            code="UNSUPPORTED_PARAMETER", message=f"Unsupported parameter: {parameter}",
                            embodiment_id=plan.embodiment_id, step_id=step.step_id,
                        ))
                if invention_type == "algorithm-software" and step.semantic_role == SemanticRole.TECHNICAL_MODULE:
                    if not step.inputs or not step.outputs or step.scenario not in supported_scenarios:
                        findings.append(SemanticFinding(
                            code="AI_INPUT_OUTPUT_SCENE_LINK_MISSING",
                            message="AI module lacks a supported input/output/scenario link.",
                            embodiment_id=plan.embodiment_id, step_id=step.step_id,
                        ))

        for index, left in enumerate(embodiments):
            for right in embodiments[index + 1:]:
                left_facts, right_facts = set(left.fact_ids), set(right.fact_ids)
                similarity = len(left_facts & right_facts) / max(1, len(left_facts | right_facts))
                if similarity >= 0.85 and not right.material_distinctions:
                    findings.append(SemanticFinding(
                        code="EMBODIMENT_NOT_DISTINCT", message="Embodiments lack a material technical distinction.",
                        embodiment_id=right.embodiment_id,
                    ))

        clusters = section5_fact_clusters or []
        if len(embodiments) > 1 and clusters:
            mirrored = 0
            for plan in embodiments:
                facts = set(plan.fact_ids)
                if any(facts and facts <= set(cluster) for cluster in clusters):
                    mirrored += 1
            if mirrored == len(embodiments):
                findings.append(SemanticFinding(
                    code="EMBODIMENT_SECTION_MIRRORING",
                    message="Section 7 maps Section 5 modules one-to-one into embodiments.",
                ))

        for text in generated_texts or []:
            section_match = re.match(r"\[SECTION:([^]]+)]\s*", text)
            section_id = section_match.group(1) if section_match else "07-UNSCOPED"
            scoped_text = text[section_match.end():] if section_match else text
            is_validation_text = bool(re.match(r"\s*(?:验证步骤|validation\s+step)", scoped_text, re.I))
            if (section_id.startswith("07-") and not is_validation_text
                    and re.search(r"(?:具体事实|输入|处理|输出).{0,12}待.{0,8}(?:补充|确认)", scoped_text)):
                findings.append(SemanticFinding(
                    code="PRIMARY_EMBODIMENT_INCOMPLETE",
                    message="Generated primary step leaves its substantive implementation pending."
                ))
            if section_id.startswith("07-") and target:
                step_match = re.match(r"\s*S(\d+)[：:]", scoped_text)
                if (step_match and int(step_match.group(1)) == len(target.ordered_steps)
                        and re.search(r"后续步骤|传递至下游|作为下游", scoped_text)):
                    findings.append(SemanticFinding(
                        code="PRIMARY_EMBODIMENT_INCOMPLETE",
                        message="Generated final step falsely declares a downstream implementation step."
                    ))
            if section_id.startswith(("05-", "07-")):
                for parameter in _parameters(scoped_text):
                    signature = re.sub(r"[\s,，]", "", parameter.lower()).replace("×", "x")
                    numbers = re.findall(r"\d+(?:\.\d+)?", signature)
                    unit = "".join(re.findall(r"[a-z%]+", signature))
                    supported = (signature in source_parameter_text or (
                        bool(numbers)
                        and all(number in source_parameter_text for number in numbers)
                        and (not unit or unit in source_parameter_text)
                    ))
                    if not supported:
                        findings.append(SemanticFinding(
                            code="UNSUPPORTED_PARAMETER",
                            message=(f"Generated exact parameter lacks source support in {section_id}: "
                                     f"{parameter} | {scoped_text[:100]}")
                        ))
                source_lower = source_joined.lower()
                for generated_term, aliases in dimension_aliases.items():
                    if generated_term in scoped_text and not any(alias in source_lower for alias in aliases):
                        findings.append(SemanticFinding(
                            code="UNSUPPORTED_PARAMETER",
                            message=(f"Generated dimensionality lacks source support in {section_id}: "
                                     f"{generated_term} | {scoped_text[:100]}")
                        ))
            if not section_id.startswith("09") and unsupported_expansion(scoped_text):
                findings.append(SemanticFinding(
                    code="UNSUPPORTED_GENERALIZATION",
                    message=f"Generated prose expands the source domain in {section_id}: {scoped_text[:120]}"
                ))
            if (section_id.startswith(("05-", "07-")) and online_pattern.search(scoped_text)
                    and ScenarioRole.ONLINE_CONTROL not in supported_scenarios):
                findings.append(SemanticFinding(
                    code="SCENARIO_DRIFT",
                    message=f"Generated prose introduces an unsupported online scenario in {section_id}: {scoped_text[:120]}"
                ))
            if (section_id.startswith(("05-", "07-")) and control_promotion_pattern.search(scoped_text)
                    and ScenarioRole.ONLINE_CONTROL not in supported_scenarios):
                findings.append(SemanticFinding(
                    code="SCENARIO_DRIFT",
                    message=f"Generated prose promotes offline output to control strategy in {section_id}: {scoped_text[:120]}"
                ))
            if (section_id.startswith(("05-", "07-")) and alternative_pattern.search(scoped_text)
                    and not registry.supported_alternatives):
                findings.append(SemanticFinding(
                    code="UNSUPPORTED_ALTERNATIVE", message="Generated prose introduces an unapproved alternative."
                ))
            for term, role in role_map.items():
                if (section_id.startswith(("05-", "07-")) and not is_validation_text
                        and role == TechnicalRole.COMPARISON_BASELINE
                        and term and term in _norm(scoped_text)):
                    findings.append(SemanticFinding(
                        code="BASELINE_PROMOTED_TO_INVENTION",
                        message="Generated embodiment prose promotes a comparison baseline."
                    ))

        # Deduplicate deterministic findings to keep audits concise.
        unique: list[SemanticFinding] = []
        seen: set[tuple[str, str, str, str]] = set()
        for finding in findings:
            key = (finding.code, finding.message, finding.embodiment_id, finding.step_id)
            if key not in seen:
                seen.add(key)
                unique.append(finding)
        component_codes = {
            "EmbodimentCompleteness": {"PRIMARY_EMBODIMENT_COUNT_INVALID", "PRIMARY_EMBODIMENT_INCOMPLETE", "PRIMARY_INPUT_MISSING", "PRIMARY_OUTPUT_MISSING", "PROHIBITED_EMBODIMENT_ROLE", "EVIDENCE_SUPPORT_MISSING"},
            "EmbodimentContinuity": {"BROKEN_STEP_CHAIN", "AI_INPUT_OUTPUT_SCENE_LINK_MISSING"},
            "EmbodimentDistinctness": {"EMBODIMENT_NOT_DISTINCT"},
            "ScenarioConsistency": {"SCENARIO_DRIFT"},
            "UnsupportedGeneralization": {"UNSUPPORTED_GENERALIZATION", "UNSUPPORTED_PARAMETER"},
            "ComparisonBaselineIsolation": {"BASELINE_PROMOTED_TO_INVENTION"},
            "AlternativeImplementation": {"UNSUPPORTED_ALTERNATIVE"},
            "ClaimEmbodimentSupport": {"CLAIM_FEATURE_WITHOUT_EMBODIMENT_SUPPORT"},
            "Section5Section7Redundancy": {"EMBODIMENT_SECTION_MIRRORING"},
        }
        codes = {item.code for item in unique}
        components = {
            name: "FAIL" if codes & relevant else "PASS"
            for name, relevant in component_codes.items()
        }
        return PatentSemanticsReport(
            status="FAIL" if unique else "PASS", findings=unique,
            component_status=components, required_feature_coverage=coverage,
            unresolved_hard_drift=len(unique),
        )


def required_features_from_claims(claims) -> list[RequiredFeature]:
    features: list[RequiredFeature] = []
    for claim in getattr(claims, "claims", []) or []:
        if getattr(claim, "claim_type", "") == "dependent":
            continue
        for feature in getattr(claim, "features", []) or []:
            if getattr(feature, "mandatory", False):
                features.append(RequiredFeature(
                    feature_id=str(feature.feature_id),
                    fact_ids=list(feature.source_fact_ids),
                    evidence_ids=list(feature.evidence_ids), text=str(feature.text),
                ))
    return features


def validate_bundle(bundle: SemanticPlanningBundle, claims=None, generated_texts=None) -> PatentSemanticsReport:
    required = required_features_from_claims(claims) if claims is not None else []
    return PatentSemanticsValidator().validate(
        embodiments=bundle.embodiments, graph=bundle.graph,
        required_features=required or bundle.required_features,
        registry=bundle.registry,
        section5_fact_clusters=bundle.section5_fact_clusters,
        invention_type=bundle.invention_type,
        generated_texts=generated_texts,
    )


__all__ = [
    "EmbodimentPlan", "EmbodimentStep", "EvidenceBoundEmbodimentPlanner",
    "InventionCoreGraph", "InventionEdge", "InventionNode",
    "PatentSemanticsReport", "PatentSemanticsValidator", "RequiredFeature",
    "ScenarioRole", "SemanticFact", "SemanticPlanningBundle", "SemanticRegistry",
    "SemanticRole", "TechnicalRole", "TechnicalRoleEntry",
    "enrich_registry", "required_features_from_claims", "validate_bundle",
]
