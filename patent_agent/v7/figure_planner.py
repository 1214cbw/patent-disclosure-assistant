"""Evidence-driven, case-local figure planning.

Graphs are projections of the current understanding's method steps and
declared relationships. No case name or technical-domain vocabulary controls
their structure. Extracted images require a case-local ``figure_registry.json``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec
from patent_agent.document.math_registry import normalize_symbol_aliases
from patent_agent.v7_1.quality import TechnicalTerminologyNormalizer

MAX_FIGURES = 8
MAX_NODES = 10


def _text(obj: Any) -> str:
    value = getattr(obj, "text", obj)
    value = getattr(value, "text", value)
    return str(value or "").strip()


class FigurePlannerV7:
    def __init__(self, case_id: str, understanding, evidence_store=None,
                 source_figures=None, provider=None, cache_dir: Path | None = None):
        self.case_id = case_id
        self.understanding = understanding
        self.evidence_store = evidence_store
        self.source_figures = source_figures or []
        self.provider = provider
        self.cache_dir = cache_dir
        sources = [str(getattr(fact, "statement", ""))
                   for fact in (getattr(understanding, "facts", []) or [])]
        if evidence_store is not None:
            sources.extend(str(chunk.raw_text or chunk.normalized_text)
                           for chunk in evidence_store.all())
        self.normalizer = TechnicalTerminologyNormalizer.from_source_texts(sources)
        self.equation_sources = [
            str(getattr(equation, "normalized_latex", "")
                or getattr(equation, "original_expression", ""))
            for equation in (getattr(understanding, "equations", []) or [])
        ]

    def _normalize_label(self, value: str) -> str:
        return normalize_symbol_aliases(
            self.normalizer.normalize(str(value)), self.equation_sources
        )

    def _facts_for_evidence(self, evidence_ids: list[str]) -> list[str]:
        evidence = set(evidence_ids)
        return [str(getattr(fact, "fact_id", ""))
                for fact in (getattr(self.understanding, "facts", []) or [])
                if evidence & set(getattr(fact, "evidence_ids", []) or [])][:8]

    def _contract(self, figure: FigureSpec) -> FigureSpec:
        node_ids = [node.id for node in figure.nodes]
        edge_ids = [f"{edge.source}->{edge.target}" for edge in figure.edges]
        fact_ids = sorted({item for node in figure.nodes for item in node.fact_ids})
        evidence_ids = sorted({item for node in figure.nodes for item in node.evidence_ids})
        return figure.model_copy(update={
            "case_id": self.case_id,
            "source_feature_ids": fact_ids + evidence_ids,
            "source_fact_ids": fact_ids,
            "semantic_keywords": list(self.normalizer.registry.tokens[:12]) or [figure.source_type],
            "required_node_ids": node_ids,
            "required_edge_ids": edge_ids,
            "caption": figure.caption or figure.title,
            "purpose": figure.purpose or figure.title,
        })

    def _step_figure(self) -> FigureSpec | None:
        steps = list(getattr(self.understanding, "steps", []) or [])[:MAX_NODES]
        if not steps:
            return None
        nodes = []
        for index, step in enumerate(steps, 1):
            statement = getattr(step, "text", step)
            evidence_ids = list(getattr(statement, "evidence_ids", []) or [])
            nodes.append(FigureNode(
                id=f"S{index}", label=self._normalize_label(_text(statement)),
                claim_step=f"S{index}", evidence_ids=evidence_ids,
                fact_ids=self._facts_for_evidence(evidence_ids),
            ))
        edges = [FigureEdge(source=nodes[i].id, target=nodes[i + 1].id)
                 for i in range(len(nodes) - 1)]
        first_step = _text(getattr(steps[0], "text", steps[0]))
        title = (f"技术方案总体流程图（{first_step}）"
                 if 2 <= len(first_step) <= 28 else "技术方案总体流程图")
        return self._contract(FigureSpec(
            id="FIG-001", number=1, type="flowchart", title=title,
            nodes=nodes, edges=edges,
            source_ids=[str(getattr(step, "step_id", "")) for step in steps],
            purpose="展示当前案例证据声明的方法步骤及其顺序",
            source_type="method_steps", layout="vertical",
        ))

    def _inventory_figure(self, items: list[Any], number: int, title: str,
                          source_type: str) -> FigureSpec | None:
        if not items:
            return None
        nodes = []
        for index, item in enumerate(items[:MAX_NODES], 1):
            statement = getattr(item, "description", None) or item
            evidence_ids = list(getattr(statement, "evidence_ids", []) or [])
            label = str(getattr(item, "name", "") or _text(statement))
            nodes.append(FigureNode(
                id=f"N{index}", label=self._normalize_label(label),
                evidence_ids=evidence_ids, fact_ids=self._facts_for_evidence(evidence_ids),
            ))
        return self._contract(FigureSpec(
            id=f"FIG-{number:03d}", number=number, type="system", title=title,
            nodes=nodes, edges=[], source_ids=[source_type], source_type=source_type,
            purpose=f"汇总当前案例证据声明的{title[:-1] if title.endswith('图') else title}",
        ))

    def _relationship_figure(self, relationships: list[Any], number: int,
                             title: str, source_type: str) -> FigureSpec | None:
        relationships = relationships[:MAX_NODES - 1]
        if not relationships:
            return None
        nodes_by_label: dict[str, FigureNode] = {}
        edges = []
        for relation in relationships:
            data = getattr(relation, "relation", relation)
            evidence_ids = list(getattr(data, "evidence_ids", []) or [])
            fact_ids = self._facts_for_evidence(evidence_ids)
            labels = [self._normalize_label(str(getattr(relation, key, "")).strip())
                      for key in ("source", "target")]
            node_ids = []
            for label in labels:
                if label not in nodes_by_label:
                    node_id = f"N{len(nodes_by_label) + 1}"
                    nodes_by_label[label] = FigureNode(
                        id=node_id, label=label, fact_ids=fact_ids,
                        evidence_ids=evidence_ids,
                    )
                node_ids.append(nodes_by_label[label].id)
            edges.append(FigureEdge(
                source=node_ids[0], target=node_ids[1], fact_ids=fact_ids,
                evidence_ids=evidence_ids,
            ))
        return self._contract(FigureSpec(
            id=f"FIG-{number:03d}", number=number, type="system", title=title,
            nodes=list(nodes_by_label.values()), edges=edges,
            source_ids=[source_type], source_type=source_type,
            purpose="展示当前案例证据声明的节点关系",
        ))

    def _registry_path(self) -> Path | None:
        if self.evidence_store is not None:
            return Path(self.evidence_store.root).parent / "figure_registry.json"
        candidate = Path("workspace") / "private_cases" / self.case_id / "figure_registry.json"
        return candidate.resolve()

    def _case_local_plan(self) -> list[FigureSpec]:
        registry_path = self._registry_path()
        if registry_path is None or not registry_path.is_file():
            return []
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        planned = payload.get("figure_plan", []) if isinstance(payload, dict) else []
        figures = []
        for item in planned:
            value = dict(item)
            png_path = str(value.get("png_path", ""))
            if png_path and not Path(png_path).is_absolute():
                value["png_path"] = str((registry_path.parent / png_path).resolve())
            figures.append(self._contract(FigureSpec.model_validate(value)))
        return figures

    def _source_figure(self, number: int) -> FigureSpec | None:
        entries = list(self.source_figures)
        registry_path = self._registry_path()
        if registry_path is not None and registry_path.is_file():
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            entries.extend(payload.get("figures", []) if isinstance(payload, dict) else payload)
        for entry in entries:
            path = Path(str(entry.get("path", "")))
            if not path.is_absolute() and registry_path is not None:
                path = (registry_path.parent / path).resolve()
            if not path.is_file() or path.stat().st_size <= 10_000:
                continue
            title = str(entry.get("title") or "来源材料结构示意图")
            return self._contract(FigureSpec(
                id=f"FIG-{number:03d}", number=number, type="system", title=title,
                nodes=[FigureNode(id="R1", label="来源材料结构示意图",
                                  evidence_ids=list(entry.get("evidence_ids", [])))],
                edges=[],
                source_ids=list(entry.get("evidence_ids", [])), png_path=str(path),
                provenance="extracted", source_type="case_local_registry",
                source_figure_ref=str(entry.get("source_figure_ref", path.name)),
                purpose=str(entry.get("purpose") or "展示来源材料中的结构关系"),
            ))
        return None

    def _translate_to_chinese(self, figures: list[FigureSpec]) -> list[FigureSpec]:
        if self.provider is None:
            return figures
        from patent_agent.v7.disclosure_planner import CHINESE_STYLE_RULES, _text_retry

        items = [{
            "id": figure.id, "title": figure.title,
            "nodes": [{"id": node.id, "label": node.label} for node in figure.nodes],
        } for figure in figures if figure.provenance != "extracted"]
        if not items:
            return figures
        prompt = (
            "V7.1_FIGURE_LABEL_SCHEMA\n将下列由当前案例证据直接生成的图题和节点标签翻译为简洁中文。"
            "保持ID、公式、符号、数字和技术含义，不增加任何节点、边或技术事实。\n"
            f"输入：{json.dumps(items, ensure_ascii=False)}\n"
            "仅输出同结构JSON对象：{\"figures\":[...]}"
        )
        response = _text_retry(self.provider, system_prompt=CHINESE_STYLE_RULES,
                               user_prompt=prompt, cache_dir=self.cache_dir)
        match = re.search(r"\{.*\}", response, re.S)
        try:
            translated = json.loads(match.group(0) if match else response).get("figures", [])
        except (json.JSONDecodeError, AttributeError):
            return figures
        mapped = {item.get("id"): item for item in translated}
        output = []
        for figure in figures:
            item = mapped.get(figure.id)
            if not item:
                output.append(figure)
                continue
            labels = {node.get("id"): str(node.get("label", "")) for node in item.get("nodes", [])}
            nodes = [node.model_copy(update={
                "label": self._normalize_label(labels.get(node.id, node.label))
            }) for node in figure.nodes]
            title = str(item.get("title") or figure.title)
            output.append(figure.model_copy(update={"title": title, "caption": title, "nodes": nodes}))
        return output

    def plan(self) -> list[FigureSpec]:
        case_local = self._case_local_plan()
        if case_local:
            return case_local[:MAX_FIGURES]
        figures = []
        step_figure = self._step_figure()
        if step_figure is not None:
            figures.append(step_figure)
        source_figure = self._source_figure(len(figures) + 1)
        if source_figure is not None:
            figures.append(source_figure)
        control = list(getattr(self.understanding, "control_flows", []) or [])
        data = list(getattr(self.understanding, "data_flows", []) or [])
        if control or data:
            for relationships, title, source_type in (
                (control, "控制关系图", "control_flows"),
                (data[:4], "前段数据关系图", "data_flows"),
                (data[4:8], "后段数据关系图", "data_flows"),
            ):
                number = len(figures) + 1
                figure = self._relationship_figure(relationships, number, title, source_type)
                if figure is not None:
                    figures.append(figure)
        else:
            for items, title, source_type in (
                (list(getattr(self.understanding, "components", []) or []), "技术组件图", "components"),
                (list(getattr(self.understanding, "inputs", []) or []), "输入要素图", "inputs"),
                (list(getattr(self.understanding, "outputs", []) or []), "输出要素图", "outputs"),
            ):
                number = len(figures) + 1
                figure = self._inventory_figure(items, number, title, source_type)
                if figure is not None:
                    figures.append(figure)
        figures = figures[:MAX_FIGURES]
        figures = [figure.model_copy(update={"number": index, "id": f"FIG-{index:03d}"})
                   for index, figure in enumerate(figures, 1)]
        return self._translate_to_chinese(figures)
