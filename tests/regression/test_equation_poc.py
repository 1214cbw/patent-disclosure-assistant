from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "patent_equation_poc" / "src"))
from generate_test_docx import TESTS

from patent_agent.document.equation_engine.omml_renderer import M, latex_to_omml


def test_original_equation_suite_in_migrated_engine():
    ns = {"m": M}
    for latex in TESTS:
        node = latex_to_omml(latex)
        assert node.tag == f"{{{M}}}oMath"
        assert not node.xpath(".//m:nary[not(m:e/*)]", namespaces=ns)

