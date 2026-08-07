"""Structural DOCX and optional real-Word validation for the PoC."""
from __future__ import annotations
import re, zipfile
from pathlib import Path
from lxml import etree
from .equation_engine import EquationEngine
from .omml_renderer import M, NSMAP


def validate_docx(docx_path: str | Path, expected_equations: int, expected_display: int, expected_inline: int) -> dict:
    path = Path(docx_path)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = etree.fromstring(xml)
    maths = root.xpath(".//m:oMath", namespaces=NSMAP)
    displays = root.xpath(".//m:oMathPara", namespaces=NSMAP)
    empty_nary_bodies = sum(not nary.xpath("./m:e/*", namespaces=NSMAP) for nary in root.xpath(".//m:nary", namespaces=NSMAP))
    math_text = "".join("".join(item.xpath(".//m:t/text()", namespaces=NSMAP)) for item in maths)
    report = {"expected_equations": expected_equations, "omml_equations_found": len(maths), "display_equations": len(displays), "inline_equations": len(maths) - len(displays), "residual_dollar_markers": xml.count(b"$$"), "residual_latex_in_omml": len(re.findall(r"\\(?:frac|sqrt|begin|sum|int|lim)", math_text)), "broken_placeholders": len(re.findall(r"\[?(?:TODO|PLACEHOLDER|FAIL)\]?", xml.decode("utf-8", "ignore"), flags=re.I)), "empty_nary_bodies": empty_nary_bodies}
    report["docx_structure_pass"] = report["omml_equations_found"] == expected_equations and report["display_equations"] == expected_display and report["inline_equations"] == expected_inline
    report["omml_validation_pass"] = report["docx_structure_pass"] and not report["residual_dollar_markers"] and not report["residual_latex_in_omml"] and not report["broken_placeholders"] and not report["empty_nary_bodies"]
    return report


def write_validation_report(report: dict, path: str | Path) -> None:
    lines = ["Patent Equation Engine Validation Report", "", f"Expected equations: {report['expected_equations']}", f"OMML equations found: {report['omml_equations_found']}", "", f"Display equations: {report['display_equations']}", f"Inline equations: {report['inline_equations']}", "", f"Residual $$ markers: {report['residual_dollar_markers']}", f"Residual LaTeX commands in OMML: {report['residual_latex_in_omml']}", f"Broken placeholders: {report['broken_placeholders']}", f"Empty sum/integral operands: {report['empty_nary_bodies']}", "", f"DOCX structure: {'PASS' if report['docx_structure_pass'] else 'FAIL'}", f"OMML validation: {'PASS' if report['omml_validation_pass'] else 'FAIL'}"]
    if "word" in report:
        word = report["word"]; lines += ["", "Microsoft Word COM:", f"Available: {word.get('available')}", f"Word OMaths.Count: {word.get('omaths_count', 'N/A')}", f"PDF: {word.get('pdf', 'N/A')}", f"COM error: {word.get('error', 'None')}"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

