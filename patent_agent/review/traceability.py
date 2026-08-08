from __future__ import annotations

from patent_agent.core.models import GroundedClaimSet, GroundedDisclosure, TechnicalUnderstandingResult, TraceabilityLink, TraceabilityReport


def build_traceability(disclosure: GroundedDisclosure, claims: GroundedClaimSet, understanding: TechnicalUnderstandingResult, figures: list | None = None) -> TraceabilityReport:
    fact_ids = {fact.fact_id for fact in understanding.facts}
    # Evidence union covers every source in the understanding, not just
    # facts: equations, steps, components, flows and parameters carry their
    # own evidence ids that disclosure paragraphs / figures legitimately
    # cite back to.
    evidence_ids: set[str] = set()
    for fact in understanding.facts:
        evidence_ids.update(fact.evidence_ids)
    for equation in understanding.equations:
        evidence_ids.update(equation.evidence_ids)
    for component in understanding.components:
        evidence_ids.update(component.description.evidence_ids)
    for step in understanding.steps:
        evidence_ids.update(step.text.evidence_ids)
    for flow in [*understanding.data_flows, *understanding.control_flows]:
        evidence_ids.update(flow.relation.evidence_ids)
    for parameter in understanding.parameters:
        evidence_ids.update(parameter.evidence_ids)
    for statement_list in (understanding.technical_field, understanding.technical_problems,
                           understanding.system_overview, understanding.inputs,
                           understanding.outputs, understanding.technical_effects,
                           understanding.experiments, understanding.alternatives):
        for statement in statement_list:
            evidence_ids.update(statement.evidence_ids)
    links: list[TraceabilityLink] = []
    broken: list[str] = []
    for section in disclosure.sections:
        for paragraph in section.paragraphs:
            valid = bool(paragraph.evidence_ids or paragraph.fact_ids) and set(paragraph.fact_ids) <= fact_ids and set(paragraph.evidence_ids) <= evidence_ids
            link = TraceabilityLink(link_id=f"TR-{paragraph.paragraph_id}", object_type="disclosure", object_id=paragraph.paragraph_id, fact_ids=paragraph.fact_ids, evidence_ids=paragraph.evidence_ids, status="LINKED" if valid else "BROKEN")
            links.append(link)
            if not valid: broken.append(link.link_id)
    paragraph_ids = {paragraph.paragraph_id for section in disclosure.sections for paragraph in section.paragraphs}
    for claim in claims.claims:
        for feature in claim.features:
            matched = [paragraph.paragraph_id for section in disclosure.sections for paragraph in section.paragraphs if set(paragraph.fact_ids) & set(feature.source_fact_ids) or set(paragraph.evidence_ids) & set(feature.evidence_ids)]
            valid = bool(matched and feature.source_fact_ids and feature.evidence_ids) and set(feature.source_fact_ids) <= fact_ids and set(matched) <= paragraph_ids
            link = TraceabilityLink(link_id=f"TR-CL{claim.claim_number}-{feature.feature_id}", object_type="claim_feature", object_id=f"CL{claim.claim_number}:{feature.feature_id}", disclosure_paragraph_ids=matched, fact_ids=feature.source_fact_ids, evidence_ids=feature.evidence_ids, status="LINKED" if valid else "BROKEN")
            links.append(link)
            if not valid: broken.append(link.link_id)
    for equation in understanding.equations:
        valid = bool(equation.evidence_ids) and set(equation.evidence_ids) <= evidence_ids
        link = TraceabilityLink(link_id=f"TR-{equation.equation_id}", object_type="equation", object_id=equation.equation_id, evidence_ids=equation.evidence_ids, status="LINKED" if valid else "BROKEN")
        links.append(link)
        if not valid: broken.append(link.link_id)
    for figure in figures or []:
        figure_evidence = sorted({identifier for node in figure.nodes for identifier in getattr(node, "evidence_ids", [])})
        valid = bool(figure_evidence) and set(figure_evidence) <= evidence_ids
        link = TraceabilityLink(link_id=f"TR-{figure.id}", object_type="figure", object_id=figure.id, evidence_ids=figure_evidence, status="LINKED" if valid else "BROKEN")
        links.append(link)
        if not valid: broken.append(link.link_id)
    return TraceabilityReport(links=links, broken_links=broken)


def render_traceability_markdown(report: TraceabilityReport) -> str:
    lines = ["# Traceability Report", "", f"Broken links: **{len(report.broken_links)}**", ""]
    for link in report.links:
        lines += [f"## {link.object_type}: {link.object_id}", "", f"- Status: **{link.status}**", f"- Disclosure: {', '.join(link.disclosure_paragraph_ids) or 'none'}", f"- Facts: {', '.join(link.fact_ids) or 'none'}", f"- Evidence: {', '.join(link.evidence_ids) or 'none'}", ""]
    return "\n".join(lines)
