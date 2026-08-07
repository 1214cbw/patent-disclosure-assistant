from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


class SyntheticDemoResponder:
    """Deterministic schema-valid responder for synthetic/offline E2E only."""

    def __call__(self, response_model: type[BaseModel], context: dict | None) -> dict[str, Any]:
        context = context or {}
        handlers = {
            "TechnicalUnderstandingResult": self._technical,
            "GroundedCandidateList": self._candidates,
            "GroundedProtectionStrategy": self._strategy,
            "GroundedDisclosure": self._disclosure,
            "GroundedClaimSet": self._claims,
            "SemanticReviewResult": lambda context: {"findings": []},
        }
        if response_model.__name__ not in handlers:
            raise KeyError(f"Synthetic demo has no response for {response_model.__name__}")
        return handlers[response_model.__name__](context)

    @staticmethod
    def _evidence(context: dict) -> list[dict]:
        return context.get("evidence", [])

    def _find(self, context: dict, keyword: str) -> dict:
        evidence = self._evidence(context)
        return next((item for item in evidence if keyword in (item.get("section") or "") or keyword in item.get("text", "")), evidence[0])

    @staticmethod
    def _gs(text: str, evidence_ids: list[str], status: str = "SOURCE_FACT", confidence: float = .97) -> dict:
        return {"text": text.strip(), "evidence_ids": evidence_ids, "status": status, "confidence": confidence}

    @staticmethod
    def _bullets(text: str) -> list[str]:
        return [re.sub(r"^\s*[-*]\s*", "", line).strip() for line in text.splitlines() if re.match(r"^\s*[-*]\s+", line)]

    def _technical(self, context: dict) -> dict:
        field = self._find(context, "技术领域"); background = self._find(context, "技术背景"); limitations = self._find(context, "现有技术存在的问题")
        problem = self._find(context, "技术问题"); system = self._find(context, "系统组成"); algorithm = self._find(context, "算法流程")
        params = self._find(context, "关键参数"); effects = self._find(context, "技术效果"); experiments = self._find(context, "合成演示实验")
        alternatives = self._find(context, "可替代实施方式"); uncertain = self._find(context, "待确认信息")
        eid = lambda item: [item["evidence_id"]]
        component_lines = self._bullets(system["text"])
        step_lines = self._bullets(algorithm["text"])
        effect_lines = self._bullets(effects["text"])
        alternative_lines = self._bullets(alternatives["text"])
        problem_text = problem["text"].strip()
        facts = [
            {"fact_id": "FACT-001", "statement": problem_text, "category": "technical_problem", "evidence_ids": eid(problem), "status": "SOURCE_FACT", "confidence": .99},
            {"fact_id": "FACT-002", "statement": background["text"].strip(), "category": "background", "evidence_ids": eid(background), "status": "SOURCE_FACT", "confidence": .98},
            {"fact_id": "FACT-003", "statement": limitations["text"].strip(), "category": "limitation", "evidence_ids": eid(limitations), "status": "SOURCE_FACT", "confidence": .98},
        ]
        components = []
        for index, line in enumerate(component_lines, 1):
            name, _, description = line.partition("：")
            fact_id = f"FACT-C{index:03d}"
            components.append({"component_id": f"COMP-{index:03d}", "name": name, "description": self._gs(line, eid(system))})
            facts.append({"fact_id": fact_id, "statement": line, "category": "component", "evidence_ids": eid(system), "status": "SOURCE_FACT", "confidence": .99})
        steps = []
        for index, line in enumerate(step_lines, 1):
            steps.append({"step_id": f"S{index}", "text": self._gs(line, eid(algorithm))})
            facts.append({"fact_id": f"FACT-S{index:03d}", "statement": line, "category": "method_step", "evidence_ids": eid(algorithm), "status": "SOURCE_FACT", "confidence": .99})
        technical_effects = []
        for index, line in enumerate(effect_lines, 1):
            technical_effects.append(self._gs(line, eid(effects)))
            facts.append({"fact_id": f"FACT-E{index:03d}", "statement": line, "category": "technical_effect", "evidence_ids": eid(effects), "status": "SOURCE_FACT", "confidence": .98})
        for index, line in enumerate(alternative_lines, 1):
            facts.append({"fact_id": f"FACT-A{index:03d}", "statement": line, "category": "alternative", "evidence_ids": eid(alternatives), "status": "SOURCE_FACT", "confidence": .98})
        parameters = []
        for index, match in enumerate(re.finditer(r"(?m)^PARAM\s+([^=]+)=([0-9.]+)\s*([^（\s]+)", params["text"]), 1):
            parameters.append({"parameter_id": f"PARAM-{index:03d}", "symbol": None, "name": match.group(1).strip(), "value": match.group(2), "unit": match.group(3), "evidence_ids": eid(params), "status": "SOURCE_FACT"})
        symbols = {match.group(1).strip(): match.group(2).strip() for match in re.finditer(r"(?m)^SYMBOL\s+([^=]+)=(.+)$", algorithm["text"])}
        equations = []
        for match in re.finditer(r"(?m)^FORMULA\s+(EQ-\d+)\s*\|\s*([^|]+)\|\s*(.+)$", algorithm["text"]):
            equations.append({"equation_id": match.group(1), "original_expression": match.group(3).strip(), "normalized_latex": match.group(3).strip(), "evidence_ids": eid(algorithm), "status": "SOURCE_FACT", "symbols": symbols})
        experiment_text = experiments["text"].strip()
        facts.append({"fact_id": "FACT-EXP-001", "statement": experiment_text, "category": "synthetic_experiment", "evidence_ids": eid(experiments), "status": "SOURCE_FACT", "confidence": 1, "notes": "SYNTHETIC DEMO DATA only"})
        questions = [{"question_id": f"Q-{index:03d}", "text": line, "priority": "P0" if "权重约束" in line else "P1", "related_fact_ids": [], "related_evidence_ids": eid(uncertain)} for index, line in enumerate(self._bullets(uncertain["text"]), 1)]
        facts.append({"fact_id": "FACT-U001", "statement": uncertain["text"].strip(), "category": "uncertainty", "evidence_ids": eid(uncertain), "status": "SOURCE_FACT", "confidence": 1})
        facts.append({"fact_id": "FACT-INF-001", "statement": "预期输出电机状态估计结果和自适应控制指令。", "category": "inferred_output", "evidence_ids": eid(system) + eid(algorithm), "status": "INFERRED", "confidence": .82})
        return {
            "technical_field": [self._gs(field["text"], eid(field))],
            "technical_problems": [self._gs(problem_text, eid(problem))],
            "system_overview": [self._gs("系统由状态采集、时间同步、状态估计、控制处理和电机驱动单元组成。", eid(system))],
            "components": components,
            "steps": steps,
            "data_flows": [{"source": "状态采集单元", "target": "状态估计单元", "relation": self._gs("多源传感信号经时间同步后进入状态估计单元。", eid(system) + eid(algorithm))}],
            "control_flows": [{"source": "状态估计单元", "target": "控制处理单元", "relation": self._gs("融合状态量用于生成控制参数修正量。", eid(system) + eid(algorithm))}],
            "inputs": [self._gs("振动、定子电流、转速和温度信号", eid(system))],
            "outputs": [self._gs("电机状态估计结果和自适应控制指令", eid(system) + eid(algorithm), "INFERRED", .85)],
            "parameters": parameters,
            "equations": equations,
            "technical_effects": technical_effects,
            "experiments": [self._gs(experiment_text, eid(experiments))],
            "alternatives": [self._gs(line, eid(alternatives)) for line in alternative_lines],
            "uncertainties": questions,
            "facts": facts,
        }

    def _candidates(self, context: dict) -> dict:
        understanding = context["technical_understanding"]
        facts = understanding["facts"]
        all_evidence = sorted({identifier for fact in facts for identifier in fact["evidence_ids"]})
        problem = understanding["technical_problems"][0]
        steps = [item["text"] for item in understanding["steps"]]
        effects = understanding["technical_effects"]
        score_sets = [(.90, .87, .24), (.78, .82, .32), (.72, .76, .38)]
        titles = ["多源置信度融合驱动的电机闭环控制方法", "异步多源传感信号统一时间窗融合方法", "状态监测与控制参数修正一体化系统"]
        feature_groups = [steps[:5], steps[:3], steps[2:5]]
        candidates = []
        for index, (title, features, scores) in enumerate(zip(titles, feature_groups, score_sets), 1):
            evidence = sorted({identifier for feature in features for identifier in feature["evidence_ids"]} | set(all_evidence))
            candidates.append({"candidate_id": f"INV-{index:03d}", "title": title, "technical_problem": problem, "core_idea": self._gs("将多源状态融合结果直接用于生成电机控制参数修正量。", evidence, "INFERRED", .90), "mandatory_features": features[:4], "optional_features": understanding["alternatives"][:3], "technical_effects": effects, "evidence_ids": evidence, "novelty_hypothesis": "查新前假设：多源置信度融合与闭环参数修正的组合关系可能形成区别特征。", "inventiveness_hypothesis": "需结合人工导入 prior art 的 feature-level matrix 进一步判断。", "protection_value_score": scores[0], "evidence_strength_score": scores[1], "risk_score": scores[2], "score_breakdown": {"evidence_strength": scores[1], "novelty_potential": .72 - index * .04, "technical_importance": .86 - index * .03, "claimability": .88 - index * .04, "alternative_coverage": .76, "implementation_support": .84 - index * .03, "risk": scores[2]}, "inventor_questions": [item["text"] for item in understanding["uncertainties"]], "possible_duplicate_of": [], "merge_recommendation": ""})
        return {"candidates": candidates}

    def _strategy(self, context: dict) -> dict:
        candidate = context["approved_candidate"]
        core = candidate["mandatory_features"]
        optional = candidate["optional_features"]
        evidence = candidate["evidence_ids"]
        return {"inventive_concept": candidate["core_idea"]["text"], "independent_claim_core": core, "dependent_claim_features": optional, "optional_features": optional, "broad_terms": [{"concept_id": "TERM-001", "selected_term": "状态采集单元", "alternatives": ["多源传感模块"], "evidence_ids": evidence}, {"concept_id": "TERM-002", "selected_term": "控制处理单元", "alternatives": ["控制器"], "evidence_ids": evidence}], "narrow_terms": [{"concept_id": "TERM-001", "selected_term": "振动、电流、转速和温度传感器组合", "alternatives": [], "evidence_ids": evidence}], "parameters_to_avoid_locking": ["时间窗长度", "权重更新周期", "采样率"], "alternative_embodiments_needed": [item["text"] for item in optional], "support_gaps": [], "risks": ["查新仅基于人工导入资料，不构成穷尽性检索。", "合成 Demo 参数不得作为真实申请事实。"], "inventor_questions": candidate["inventor_questions"]}

    def _disclosure(self, context: dict) -> dict:
        title = context["title"]; understanding = context["technical_understanding"]; candidate = context["approved_candidate"]
        facts = understanding["facts"]
        fact_by_category = {}
        for fact in facts: fact_by_category.setdefault(fact["category"], []).append(fact)
        all_evidence = candidate["evidence_ids"]
        def para(section: str, index: int, text: str, category: str | None = None, status: str = "SOURCE_FACT"):
            selected = fact_by_category.get(category, []) if category else facts[:1]
            evidence = sorted({identifier for fact in selected for identifier in fact["evidence_ids"]}) or all_evidence[:1]
            fact_ids = [fact["fact_id"] for fact in selected] or [facts[0]["fact_id"]]
            return {"paragraph_id": f"DISC-{section}-P{index:03d}", "section_id": section, "text": text, "evidence_ids": evidence, "fact_ids": fact_ids, "derived_from": fact_ids, "status": status}
        section_data = [
            ("01", "1. 发明名称", [para("01", 1, "预期发明名称为：" + title, "technical_problem", "AI_SUGGESTION")]),
            ("02", "2. 技术领域", [para("02", 1, understanding["technical_field"][0]["text"], "technical_problem")]),
            ("03", "3. 背景技术", [para("03", 1, fact_by_category["background"][0]["statement"], "background")]),
            ("04", "4. 现有技术存在的问题", [para("04", 1, fact_by_category["limitation"][0]["statement"], "limitation")]),
            ("05", "5. 本发明要解决的技术问题", [para("05", 1, understanding["technical_problems"][0]["text"], "technical_problem")]),
            ("06", "6. 技术方案", [para("06", index, item["text"]["text"], "method_step") for index, item in enumerate(understanding["steps"], 1)]),
            ("07", "7. 有益效果", [para("07", index, item["text"], "technical_effect") for index, item in enumerate(understanding["technical_effects"], 1)]),
            ("08", "8. 附图说明", [para("08", 1, "预期附图包括：图1为电机状态监测与自适应控制方法流程图；图2为系统结构示意图。", "component", "INFERRED")]),
            ("09", "9. 具体实施方式", [para("09", 1, "预期在合成演示实施例中，依次获取多源信号、完成时间同步与状态融合，并根据状态偏差生成控制参数修正量。", "method_step", "INFERRED"), para("09", 2, understanding["experiments"][0]["text"], "synthetic_experiment")]),
            ("10", "10. 可替代实施方式", [para("10", index, item["text"], "alternative", "SOURCE_FACT") for index, item in enumerate(understanding["alternatives"], 1)]),
            ("11", "11. 关键创新点与拟保护点", [para("11", 1, "预期保护的核心组合为：" + candidate["core_idea"]["text"], "method_step", "INFERRED")]),
            ("12", "12. 需要发明人进一步确认的问题", [para("12", index, item["text"], "uncertainty") for index, item in enumerate(understanding["uncertainties"], 1)]),
        ]
        return {"title": title, "sections": [{"section_id": sid, "title": heading, "paragraphs": paragraphs} for sid, heading, paragraphs in section_data]}

    def _claims(self, context: dict) -> dict:
        pool = context["supported_feature_pool"]
        core = [item for item in pool if item["mandatory"]]
        dependent = [item for item in pool if not item["mandatory"]]
        def claim(number, kind, parents, features, strategy):
            if kind == "dependent":
                subject = "系统" if parents == [5] else "方法"
                lead = f"根据权利要求{parents[0]}所述的{subject}"
            elif kind == "system":
                lead = "一种电机状态监测与自适应控制系统"
            else:
                lead = "一种电机状态监测与自适应控制方法"
            rendered = lead + "，其特征在于，包括：" + "；".join(item["text"].rstrip("。；") for item in features) + "。"
            return {"claim_number": number, "claim_type": kind, "parent_claims": parents, "features": features, "rendered_text": rendered, "draft_strategy": strategy}
        claims = [claim(1, "method", [], core, "broad")]
        for number, feature in enumerate(dependent[:3], 2):
            claims.append(claim(number, "dependent", [1], [feature], "conservative"))
        while len(claims) < 4:
            claims.append(claim(len(claims) + 1, "dependent", [1], [core[min(len(claims) - 1, len(core) - 1)]], "conservative"))
        claims.append(claim(5, "system", [], core, "conservative"))
        claims.append(claim(6, "dependent", [5], [dependent[0] if dependent else core[-1]], "conservative"))
        return {"title": context["title"], "claims": claims}
