"""V7.1 DOCX/PDF delivery audits and report persistence."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from patent_agent.document.equation_engine import latex_to_omml
from patent_agent.document.equation_engine.omml_renderer import NSMAP
from patent_agent.v7_1.quality import (
    BilingualTermValidator,
    DeliveryQualityGate,
    EquationIntegrityValidator,
    FigureGraphValidator,
    FigureNarrativeConsistencyValidator,
    HeadingCompletenessValidator,
    QualityResult,
    SectionCompletenessValidator,
    TechnicalTerminologyNormalizer,
    TokenIntegrityValidator,
)


def _json_result(result: QualityResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "findings": [finding.__dict__ for finding in result.findings],
    }


def _omml_signature(node) -> dict[str, Any]:
    sequence = []
    for item in node.iter():
        tag = etree.QName(item).localname
        if tag.endswith("Pr"):
            continue
        value = ""
        for key, raw in item.attrib.items():
            if etree.QName(key).localname == "val":
                value = raw
        sequence.append([tag, (item.text or "").strip(), value])
    payload = json.dumps(sequence, ensure_ascii=False, separators=(",", ":"))
    return {"sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "sequence": sequence}


def audit_docx_equations(docx_path: Path, equations: list[Any]) -> dict[str, Any]:
    with zipfile.ZipFile(docx_path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    actual_nodes = root.xpath(".//m:oMathPara", namespaces=NSMAP)
    expected_items = []
    actual_items = []
    for index, equation in enumerate(equations, 1):
        if isinstance(equation, dict):
            equation_id = str(equation.get("id") or equation.get("equation_id") or f"eq{index}")
            latex = str(equation.get("latex") or equation.get("normalized_latex") or
                        equation.get("original_expression") or "")
        else:
            equation_id = str(getattr(equation, "id", getattr(equation, "equation_id", f"eq{index}")))
            latex = str(getattr(equation, "latex", "") or
                        getattr(equation, "normalized_latex", "") or
                        getattr(equation, "original_expression", ""))
        signature = _omml_signature(latex_to_omml(latex, display=True))
        expected_items.append({"id": equation_id, "latex": latex, "signature": signature})
    for index, node in enumerate(actual_nodes, 1):
        equation_id = expected_items[index - 1]["id"] if index <= len(expected_items) else f"unexpected-{index}"
        actual_items.append({"id": equation_id, "signature": _omml_signature(node)})
    structural = EquationIntegrityValidator().validate(
        [{"id": item["id"], "latex": item["latex"]} for item in expected_items],
        [{"id": item["id"], "latex": expected_items[index]["latex"]
          if index < len(expected_items) else ""} for index, item in enumerate(actual_items)],
    )
    mismatches = []
    for expected, actual in zip(expected_items, actual_items):
        if expected["signature"]["sha256"] != actual["signature"]["sha256"]:
            mismatches.append(expected["id"])
    status = "PASS" if structural.status == "PASS" and not mismatches and len(expected_items) == len(actual_items) else "FAIL"
    return {
        "status": status,
        "expected_count": len(expected_items),
        "actual_count": len(actual_items),
        "id_order": [item["id"] for item in actual_items],
        "signature_mismatches": mismatches,
        "structural": _json_result(structural),
        "equations": [
            {
                "id": expected["id"],
                "latex": expected["latex"],
                "expected_signature": expected["signature"]["sha256"],
                "actual_signature": actual_items[index]["signature"]["sha256"]
                if index < len(actual_items) else None,
            }
            for index, expected in enumerate(expected_items)
        ],
    }


def audit_pdf_render(pdf_path: Path, equation_count: int, figure_count: int) -> dict[str, Any]:
    import fitz

    errors: list[dict[str, Any]] = []
    pages = []
    equation_locations: dict[str, dict[str, Any]] = {}
    image_locations: list[dict[str, Any]] = []
    image_count = 0
    document = fitz.open(pdf_path)
    for page_index, page in enumerate(document, 1):
        width, height = float(page.rect.width), float(page.rect.height)
        blocks = page.get_text("dict").get("blocks", [])
        text_chars = 0
        page_images = 0
        for block in blocks:
            bbox = [float(value) for value in block.get("bbox", (0, 0, 0, 0))]
            if bbox[0] < -0.5 or bbox[1] < -0.5 or bbox[2] > width + 0.5 or bbox[3] > height + 0.5:
                errors.append({"code": "PDF_BLOCK_CLIPPED", "page": page_index, "bbox": bbox})
            if block.get("type") == 1:
                page_images += 1
                image_locations.append({"page": page_index, "bbox": bbox})
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                text_chars += len(line_text.strip())
                for number in range(1, equation_count + 1):
                    if f"({number})" in line_text or f"（{number}）" in line_text:
                        equation_locations[str(number)] = {
                            "page": page_index,
                            "bbox": [float(value) for value in line.get("bbox", block.get("bbox", ()))],
                        }
        image_count += page_images
        if text_chars == 0 and page_images == 0:
            errors.append({"code": "PDF_BLANK_PAGE", "page": page_index})
        pages.append({
            "page": page_index, "width": width, "height": height,
            "text_chars": text_chars, "image_blocks": page_images,
        })
    document.close()
    missing_equation_locations = [number for number in range(1, equation_count + 1)
                                  if str(number) not in equation_locations]
    if missing_equation_locations:
        errors.append({"code": "EQUATION_RENDER_LOCATION_MISSING", "numbers": missing_equation_locations})
    if image_count < figure_count:
        errors.append({"code": "FIGURE_RENDER_COUNT_MISMATCH", "expected": figure_count, "actual": image_count})
    return {
        "status": "PASS" if not errors else "FAIL",
        "backend": "Microsoft Word COM compatible PDF + PyMuPDF geometry audit",
        "page_count": len(pages),
        "pages": pages,
        "equation_locations": equation_locations,
        "image_locations": image_locations,
        "image_blocks": image_count,
        "errors": errors,
    }


def rendered_graphs(figures: list[Any], figure_dir: Path) -> dict[str, Any]:
    graphs: dict[str, Any] = {}
    for figure in figures:
        path = figure_dir / f"figure_{int(figure.number):02d}_layout.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        node_ids = {item.get("node_id", "") for item in payload.get("elements", [])
                    if item.get("kind") in {"node", "source_image"}}
        edge_ids = {item.get("node_id", "") for item in payload.get("elements", [])
                    if item.get("kind") == "arrow"}
        graphs[figure.id] = {
            "node_ids": sorted(node_ids), "edge_ids": sorted(edge_ids),
            "collisions": payload.get("collisions", []),
            "canvas": payload.get("canvas", {}),
        }
    return graphs


def run_delivery_audit(output: Path, docx_path: Path, pdf_path: Path,
                       disclosure, understanding, figures: list[Any], equations: list[Any]) -> dict[str, Any]:
    headings = [section.title for section in disclosure.sections]
    heading_result = HeadingCompletenessValidator().validate(headings)
    section_result = SectionCompletenessValidator().validate(disclosure.sections)
    source_texts = [str(getattr(fact, "statement", "")) for fact in understanding.facts]
    normalizer = TechnicalTerminologyNormalizer.from_source_texts(source_texts)
    disclosure_texts = [paragraph.text for section in disclosure.sections for paragraph in section.paragraphs]
    figure_texts = [figure.title for figure in figures] + [node.label for figure in figures for node in figure.nodes]
    token_result = TokenIntegrityValidator(normalizer.registry).validate(disclosure_texts + figure_texts)
    bilingual_result = BilingualTermValidator().validate(disclosure_texts + figure_texts)
    graphs = rendered_graphs(figures, output / "figures")
    graph_result = FigureGraphValidator().validate(figures, graphs)
    narrative_result = FigureNarrativeConsistencyValidator().validate(disclosure_texts, figures)
    equation_audit = audit_docx_equations(docx_path, equations)
    render_audit = audit_pdf_render(pdf_path, len(equations), len(figures))

    heading_items = []
    for section in disclosure.sections:
        section_id = str(getattr(section, "section_id", ""))
        if not section_id.startswith("05-"):
            continue
        title = str(section.title)
        paragraphs = list(getattr(section, "paragraphs", []) or [])
        body_first = str(getattr(paragraphs[0], "text", "")) if paragraphs else ""
        semantic_title = re.sub(r"^\s*5\.\d+\s*", "", title).strip()
        single = HeadingCompletenessValidator().validate([title])
        terminology = TokenIntegrityValidator(normalizer.registry).validate([title])
        balanced = all(title.count(left) == title.count(right) for left, right in (
            ("（", "）"), ("(", ")"), ("[", "]"), ("“", "”"), ('"', '"'),
        ))
        # Straight quote pairs are balanced when their count is even.
        balanced = balanced and title.count('"') % 2 == 0
        heading_items.append({
            "section_id": section_id,
            "title": title,
            "length": len(title),
            "complete": single.status == "PASS",
            "prefix_of_body": bool(semantic_title and body_first.startswith(semantic_title)),
            "terminology_valid": terminology.status == "PASS",
            "parentheses_balanced": balanced,
            "validator_result": single.status,
        })

    section_items = []
    for section in disclosure.sections:
        paragraphs = list(getattr(section, "paragraphs", []) or [])
        texts = [str(getattr(paragraph, "text", "")) for paragraph in paragraphs]
        fact_ids = sorted({
            str(fact_id) for paragraph in paragraphs
            for fact_id in (getattr(paragraph, "fact_ids", []) or []) if fact_id
        })
        single = SectionCompletenessValidator().validate([section])
        section_id = str(getattr(section, "section_id", ""))
        section_items.append({
            "section_id": section_id,
            "heading": str(getattr(section, "title", "")),
            "body_paragraph_count": len([text for text in texts if text.strip()]),
            "body_char_count": len("".join(texts)),
            "fact_ids": fact_ids,
            "figures": [str(figure.id) for figure in figures] if section_id == "06" else [],
            "equations": [str(getattr(equation, "id", "")) for equation in equations]
            if section_id == "05" else [],
            "status": single.status,
        })

    figure_items = []
    image_locations = render_audit.get("image_locations", [])
    for index, figure in enumerate(figures):
        graph = graphs.get(str(figure.id), {})
        planned_nodes = [str(node.id) for node in figure.nodes]
        planned_edges = [f"{edge.source}->{edge.target}" for edge in figure.edges]
        node_set = set(planned_nodes)
        dangling = [edge for edge in planned_edges
                    if any(endpoint not in node_set for endpoint in edge.split("->", 1))]
        location = image_locations[index] if index < len(image_locations) else None
        figure_items.append({
            "figure_id": str(figure.id),
            "caption": str(getattr(figure, "caption", "") or figure.title),
            "source_type": str(getattr(figure, "source_type", "")),
            "planned_nodes": planned_nodes,
            "rendered_nodes": graph.get("node_ids", []),
            "planned_edges": planned_edges,
            "rendered_edges": graph.get("edge_ids", []),
            "dangling_edges": dangling,
            "source_fact_ids": list(getattr(figure, "source_fact_ids", []) or []),
            "render_page": location.get("page") if location else None,
            "bbox_valid": bool(location),
            "consistency_result": narrative_result.status,
            "collisions": graph.get("collisions", []),
        })

    for index, equation in enumerate(equation_audit.get("equations", []), 1):
        location = render_audit.get("equation_locations", {}).get(str(index))
        equation.update({
            "equation_id": equation["id"],
            "registry_signature": equation["expected_signature"],
            "document_signature": equation["actual_signature"],
            "match": equation["expected_signature"] == equation["actual_signature"],
            "render_page": location.get("page") if location else None,
            "bbox_valid": bool(location),
            "validator_result": "PASS" if location and equation["expected_signature"] == equation["actual_signature"] else "FAIL",
        })

    audits = {
        "heading_audit.json": {
            **_json_result(heading_result),
            "total_technical_headings": len(heading_items),
            "headings": heading_items,
        },
        "section_audit.json": {
            **_json_result(section_result),
            "sections": section_items,
        },
        "figure_audit.json": {
            "status": "PASS" if graph_result.status == "PASS" and narrative_result.status == "PASS" else "FAIL",
            "graph": _json_result(graph_result), "narrative": _json_result(narrative_result),
            "rendered_graphs": graphs,
            "figures": figure_items,
        },
        "equation_audit.json": equation_audit,
        "render_audit.json": render_audit,
        "terminology_audit.json": {
            "status": "PASS" if token_result.status == "PASS" and bilingual_result.status == "PASS" else "FAIL",
            "registered_tokens": list(normalizer.registry.tokens),
            "token_integrity": _json_result(token_result),
            "bilingual_terms": _json_result(bilingual_result),
        },
    }
    for name, payload in audits.items():
        (output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    synthetic_results = [heading_result, section_result, token_result, bilingual_result,
                         graph_result, narrative_result]
    if equation_audit["status"] != "PASS":
        failed = QualityResult(); failed.add("EQUATION_AUDIT_FAILED", "DOCX OMML differs from canonical signatures.")
        synthetic_results.append(failed)
    delivery = DeliveryQualityGate().validate(
        synthetic_results, docx_path, pdf_path, render_audit,
    )
    report = {
        "status": delivery.status,
        "component_status": {name: payload["status"] for name, payload in audits.items()},
        "findings": [finding.__dict__ for finding in delivery.findings],
        "page_count": render_audit["page_count"],
        "equation_count": equation_audit["actual_count"],
        "figure_count": len(figures),
    }
    (output / "delivery_quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
