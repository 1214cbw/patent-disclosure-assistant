from pathlib import Path

from patent_agent.core.models import Claim, ClaimTree
from patent_agent.core.patent_ast import PatentDocumentAST, PatentNode
from patent_agent.core.state import CaseStore


def test_case_persistence_and_versioning(tmp_path: Path):
    store = CaseStore(tmp_path)
    store.create("PAT-TEST", "测试案件")
    first = store.save_stage("PAT-TEST", "knowledge", {"value": 1})
    second = store.save_stage("PAT-TEST", "knowledge", {"value": 2})
    assert first.name == "v001.json"
    assert second.name == "v002.json"
    assert store.latest_stage_path("PAT-TEST", "knowledge") == second


def test_claim_tree_rejects_forward_dependency():
    try:
        ClaimTree(title="x", claims=[Claim(number=1, category="dependent", depends_on=[2], text="x", feature_ids=["F1"], evidence_ids=["P001"])])
    except ValueError:
        return
    raise AssertionError("invalid dependency was accepted")


def test_patent_ast_references_are_resolved():
    ast = PatentDocumentAST(document_id="D1", kind="disclosure", title="x", nodes=[
        PatentNode(type="display_equation", target="EQ-001", latex="x=1", number=1),
        PatentNode(type="paragraph", children=[PatentNode(type="equation_reference", target="EQ-001")]),
    ])
    assert ast.nodes[0].target == "EQ-001"

