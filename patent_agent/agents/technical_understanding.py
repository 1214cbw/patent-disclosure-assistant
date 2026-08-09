from __future__ import annotations

import re
from patent_agent.core.models import EvidenceRef, EvidenceStatus, EquationSpec, PatentKnowledge, SourceChunk


def _find(chunks: list[SourceChunk], *terms: str, default: str = "[待发明人确认]") -> str:
    for chunk in chunks:
        if any(term in chunk.heading for term in terms):
            return chunk.text.strip()
    return default


def _bullets(text: str) -> list[str]:
    values = []
    for line in text.splitlines():
        value = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).strip()
        if value and not value.startswith(("FORMULA", "PARAM", "SYMBOL")):
            values.append(value)
    return values


class TechnicalUnderstandingAgent:
    """Builds structured technical knowledge; it never drafts patent prose."""
    def run(self, chunks: list[SourceChunk]) -> PatentKnowledge:
        joined = "\n".join(chunk.text for chunk in chunks)
        equations: list[EquationSpec] = []
        for match in re.finditer(r"(?m)^FORMULA\s+(EQ-\d+)\s*\|\s*([^|]+)\|\s*(.+)$", joined):
            equations.append(EquationSpec(id=match.group(1), role=match.group(2).strip(), latex=match.group(3).strip(), source_ids=[self._source_for(chunks, match.group(0))]))
        parameters = {m.group(1).strip(): m.group(2).strip() for m in re.finditer(r"(?m)^PARAM\s+([^=]+)=(.+)$", joined)}
        symbol_map = {m.group(1).strip(): m.group(2).strip() for m in re.finditer(r"(?m)^SYMBOL\s+([^=]+)=(.+)$", joined)}
        for equation in equations:
            equation.symbols = symbol_map.copy()
        evidence = [EvidenceRef(id=chunk.id, claim=chunk.text[:160], source_file=chunk.source_file, source_location=chunk.source_location, confidence=0.98, status=EvidenceStatus.SOURCE_FACT) for chunk in chunks]
        synthetic_results = [
            line.strip()
            for line in joined.splitlines()
            if line.strip().startswith("SYNTHETIC DEMO DATA:")
        ]
        problem = _find(chunks, "技术问题", "问题")
        scheme = _find(chunks, "技术方案", "核心方案", "系统组成")
        steps = _bullets(_find(chunks, "算法流程", "方法流程", default=""))
        components = _bullets(_find(chunks, "系统组成", "组件", default=""))
        effects = _bullets(_find(chunks, "技术效果", "有益效果", default=""))
        alternatives = _bullets(_find(chunks, "替代", default=""))
        uncertainty = _bullets(_find(chunks, "待确认", "不确定", default="")) or ["关键实施参数、公开日期、发明人和权属信息均待确认。"]
        relationships = [f"{components[index]}→{components[index + 1]}"
                         for index in range(max(0, len(components) - 1))]
        return PatentKnowledge(
            technical_field=_find(chunks, "技术领域", default="[待发明人确认]"),
            technical_problem=problem,
            existing_technology=_bullets(_find(chunks, "技术背景", "现有技术", default="")),
            existing_limitations=_bullets(_find(chunks, "现有问题", "局限", default=problem)),
            core_idea=scheme,
            components=components,
            steps=steps,
            relationships=relationships,
            data_flow=steps,
            control_flow=steps,
            inputs=_bullets(_find(chunks, "输入", default="")),
            outputs=_bullets(_find(chunks, "输出", default="")),
            technical_effects=effects,
            key_parameters=parameters,
            equations=equations,
            experimental_evidence=synthetic_results,
            alternative_embodiments=alternatives,
            optional_features=alternatives,
            mandatory_features=steps[:4] if steps else components[:4],
            inventor_assertions=[chunk.text for chunk in chunks if "发明人陈述" in chunk.heading],
            uncertain_information=uncertainty,
            evidence=evidence,
        )

    @staticmethod
    def _source_for(chunks: list[SourceChunk], fragment: str) -> str:
        return next((chunk.id for chunk in chunks if fragment in chunk.text), chunks[0].id if chunks else "P000")
