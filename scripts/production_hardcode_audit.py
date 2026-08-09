"""Audit production Python for case/domain terms used as control logic.

Fixed vocabulary is reported but never treated as proof of generalization.
The hard failure is a target term inside a branch condition or in production
output content outside an explicitly identified vocabulary-data module.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TERMS = {
    "case identifier": r"\bREAL-PAPER-\d+\b",
    "FlowVAE": r"\bFlowV\s*AE\b",
    "FiLM": r"\bFiLM\b",
    "rotor": r"\brotor\b|转子",
    "motor": r"\bmotor\b|电机",
    "torque": r"\btorque\b|转矩",
    "flux linkage": r"flux[ -]?linkage|磁链",
    "voltage constraint": r"voltage constraint|电压约束",
    "LDM": r"\bLDM\b|latent diffusion|潜在扩散",
    "PMa-SynRM": r"\bPMa-SynRM\b",
    "GAN": r"\bGAN\b",
    "VAE": r"\bVAE\b",
    "NSGA": r"\bNSGA(?:-II)?\b",
}

VOCABULARY_MODULES = {
    "patent_agent/v7/concepts.py",
    "patent_agent/document/math_registry.py",
    "patent_agent/document/chinese_validator.py",
    "patent_agent/v7/translation_roles.py",
}


def _inside(candidate: ast.AST, root: ast.AST) -> bool:
    return any(node is candidate for node in ast.walk(root))


def audit(root: Path) -> dict:
    records = []
    for base in (root / "patent_agent", root / "app"):
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8", errors="ignore")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            parents: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parents[child] = parent
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                matched = [term for term, pattern in TERMS.items()
                           if re.search(pattern, node.value, re.I)]
                if not matched:
                    continue
                ancestor = parents.get(node)
                branch_condition = False
                while ancestor is not None:
                    if isinstance(ancestor, (ast.If, ast.IfExp, ast.While)) and _inside(node, ancestor.test):
                        branch_condition = True
                        break
                    if isinstance(ancestor, ast.Match):
                        branch_condition = True
                        break
                    ancestor = parents.get(ancestor)
                if branch_condition:
                    category, status = "production_branching_logic", "forbidden"
                    resolution = "Refactor condition to case-local facts/evidence before delivery."
                elif relative.endswith("/llm/demo_mock.py"):
                    category, status = "test_fixture", "allowed"
                    resolution = "Deterministic demo fixture only; not used by the real-case production provider."
                elif relative in VOCABULARY_MODULES:
                    category, status = "auxiliary_vocabulary_data", "allowed"
                    resolution = "Auxiliary signal only; evidence-derived fingerprint is the primary gate."
                elif isinstance(parents.get(node), (ast.Expr, ast.Module)):
                    category, status = "documentation", "allowed"
                    resolution = "Non-executable documentation; does not control planning or validation."
                else:
                    category, status = "production_domain_content", "forbidden"
                    resolution = "Move case content to evidence or a case-local registry."
                for term in matched:
                    records.append({
                        "term": term,
                        "file": relative,
                        "line/module": f"{relative}:{getattr(node, 'lineno', 0)}",
                        "category": category,
                        "status": status,
                        "allowed / forbidden": status,
                        "resolution": resolution,
                    })
    forbidden = [record for record in records if record["status"] == "forbidden"]
    return {
        "scope": ["patent_agent/**/*.py", "app/**/*.py"],
        "policy": "Fixed vocabularies are auxiliary only; production branching must be fact/evidence driven.",
        "records": records,
        "summary": {
            "occurrences": len(records),
            "allowed": len(records) - len(forbidden),
            "forbidden": len(forbidden),
            "pass": not forbidden,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("production_hardcode_audit.json"))
    args = parser.parse_args()
    report = audit(args.root.resolve())
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
