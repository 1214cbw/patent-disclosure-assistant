from __future__ import annotations

import re
import zipfile
from pathlib import Path
from lxml import etree

from .equation_engine.omml_renderer import NSMAP


class PatentDocxValidator:
    def inspect_xml(self, path: Path) -> dict:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
            media = [name for name in archive.namelist() if name.startswith("word/media/")]
        root = etree.fromstring(xml)
        maths = root.xpath(".//m:oMath", namespaces=NSMAP)
        displays = root.xpath(".//m:oMathPara", namespaces=NSMAP)
        math_text = "".join(root.xpath(".//m:oMath//m:t/text()", namespaces=NSMAP))
        full_text = "".join(root.xpath(".//w:t/text()", namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}))
        empty_nary = sum(not node.xpath("./m:e/*", namespaces=NSMAP) for node in root.xpath(".//m:nary", namespaces=NSMAP))
        result = {
            "docx": str(path), "omml_count": len(maths), "display_omml_count": len(displays), "inline_omml_count": len(maths)-len(displays),
            "image_count": len(media), "empty_nary_operands": empty_nary,
            "residual_latex_in_omml": len(re.findall(r"\\(?:frac|sqrt|sum|int|begin)", math_text)),
            "unresolved_variables": re.findall(r"\{\{[^}]+\}\}|\[\[[^]]+\]\]", full_text),
            "has_figure_1_reference": "图1" in full_text,
            "has_equation_1_reference": "式（1）" in full_text,
        }
        # V7: inline math is a nice-to-have (emitted when equations declare
        # symbols); the hard floor is display equations (>=2) + total OMML
        # (>=3). A disclosure whose equations carry no symbol table is still
        # valid.
        result["xml_pass"] = result["omml_count"] >= 3 and result["display_omml_count"] >= 2 and result["image_count"] >= 1 and result["empty_nary_operands"] == 0 and result["residual_latex_in_omml"] == 0 and not result["unresolved_variables"] and result["has_figure_1_reference"] and result["has_equation_1_reference"]
        return result

    def inspect_word(self, path: Path, export_pdf: bool = True) -> dict:
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            return {"available": False, "error": "pywin32 unavailable"}
        word = document = None
        com_initialized = False
        try:
            pythoncom.CoInitialize()
            com_initialized = True
            word = win32com.client.DispatchEx("Word.Application"); word.Visible = False; word.DisplayAlerts = 0
            document = word.Documents.Open(str(path.resolve()), ReadOnly=False, AddToRecentFiles=False)
            result = {"available": True, "omaths_count": int(document.OMaths.Count), "tables_count": int(document.Tables.Count), "inline_shapes_count": int(document.InlineShapes.Count), "pages": int(document.ComputeStatistics(2))}
            document.Save()
            pdf = path.with_suffix(".pdf")
            if export_pdf: document.ExportAsFixedFormat(str(pdf.resolve()), 17)
            result["pdf"] = str(pdf) if pdf.exists() else None
            return result
        except Exception as exc:
            return {"available": True, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if document is not None: document.Close(SaveChanges=False)
            if word is not None: word.Quit()
            if com_initialized: pythoncom.CoUninitialize()

    def validate(self, path: Path, export_pdf: bool = True) -> dict:
        word = self.inspect_word(path, export_pdf=export_pdf)
        xml = self.inspect_xml(path)
        return {"xml": xml, "word": word, "pass": xml["xml_pass"] and word.get("omaths_count") == xml["omml_count"]}
