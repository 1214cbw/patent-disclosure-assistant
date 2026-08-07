from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from patent_agent.core.atomic import atomic_write_text
from patent_agent.core.models import TechnicalUnderstandingResult


def build_a1_comparison(
    case_dir: Path,
    old_path: Path,
    new_path: Path,
    old_evidence_path: Path,
    new_evidence_path: Path,
) -> Path:
    old = TechnicalUnderstandingResult.model_validate_json(Path(old_path).read_text(encoding="utf-8"))
    new = TechnicalUnderstandingResult.model_validate_json(Path(new_path).read_text(encoding="utf-8"))
    old_evidence, new_evidence = _jsonl(old_evidence_path), _jsonl(new_evidence_path)
    added, removed, changed = _match_facts(old.facts, new.facts)
    usage_path = Path(case_dir) / "logs" / "llm_calls.jsonl"
    usage = []
    if usage_path.exists():
        for line in usage_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("stage") == "grounded_technical_understanding":
                usage.append(record)

    lines = [
        "# A1 v1 与 v2 对比",
        "",
        "| 指标 | v1 | v2 |",
        "|---|---:|---:|",
        f"| Evidence chunks | {len(old_evidence)} | {len(new_evidence)} |",
        f"| Average evidence length | {_average_length(old_evidence):.1f} | {_average_length(new_evidence):.1f} |",
        f"| Facts | {len(old.facts)} | {len(new.facts)} |",
        f"| Questions | {len(old.uncertainties)} | {len(new.uncertainties)} |",
        f"| Equations | {len(old.equations)} | {len(new.equations)} |",
        f"| Evidence precision proxy | {_precision_proxy(old, old_evidence):.3f} | {_precision_proxy(new, new_evidence):.3f} |",
        "",
        "## 新增事实",
        "",
    ]
    lines += [f"- {item.fact_id}: {item.statement}" for item in added] or ["- 无"]
    lines += ["", "## 删除事实", ""]
    lines += [f"- {item.fact_id}: {item.statement}" for item in removed] or ["- 无"]
    lines += ["", "## 变化事实", ""]
    lines += [f"- {left.fact_id} -> {right.fact_id}: {left.statement} -> {right.statement}" for left, right in changed] or ["- 无"]
    lines += [
        "",
        "## Evidence references",
        "",
        f"- v1 unique fact references: {len({e for item in old.facts for e in item.evidence_ids})}",
        f"- v2 unique fact references: {len({e for item in new.facts for e in item.evidence_ids})}",
        "",
        "## Token usage",
        "",
    ]
    for index, item in enumerate(usage[-2:], 1):
        token = item.get("token_usage", {})
        lines.append(
            f"- A1 v{index}: input={token.get('input_tokens', token.get('prompt_tokens', 0))}, "
            f"output={token.get('output_tokens', token.get('completion_tokens', 0))}, "
            f"cache_hit={token.get('cache_hit_tokens', 0)}, reasoning={token.get('reasoning_tokens', 0)}"
        )
    lines += [
        "",
        "## Question changes",
        "",
        f"- v1 roles: {json.dumps(_question_roles(old), ensure_ascii=False, sort_keys=True)}",
        f"- v2 roles: {json.dumps(_question_roles(new), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Formula changes",
        "",
        f"- v1 equations: {', '.join(item.equation_id for item in old.equations) or 'none'}",
        f"- v2 equations: {', '.join(item.equation_id for item in new.equations) or 'none'}",
        "",
        "## Review note",
        "",
        "All v2 facts remain UNREVIEWED. This comparison does not approve technical correctness.",
        "",
    ]
    path = Path(case_dir) / "review" / "a1_version_comparison.md"
    atomic_write_text(path, "\n".join(lines))
    return path


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _average_length(items: list[dict]) -> float:
    return sum(len(item.get("raw_text", "")) for item in items) / max(1, len(items))


def _precision_proxy(result: TechnicalUnderstandingResult, evidence: list[dict]) -> float:
    lengths = {item["evidence_id"]: len(item.get("raw_text", "")) for item in evidence}
    scores = []
    for fact in result.facts:
        cited = [lengths.get(identifier, 4000) for identifier in fact.evidence_ids]
        scores.append(min(1.0, 600 / max(1, sum(cited) / max(1, len(cited)))))
    return sum(scores) / max(1, len(scores))


def _match_facts(old_facts, new_facts):
    remaining = set(range(len(new_facts)))
    changed, removed = [], []
    for old in old_facts:
        candidates = [
            (SequenceMatcher(None, old.statement.lower(), new_facts[index].statement.lower()).ratio(), index)
            for index in remaining
            if new_facts[index].category == old.category
        ]
        if not candidates:
            candidates = [
                (SequenceMatcher(None, old.statement.lower(), new_facts[index].statement.lower()).ratio(), index)
                for index in remaining
            ]
        score, index = max(candidates, default=(0.0, -1))
        if score >= 0.48:
            remaining.remove(index)
            if old.statement.strip() != new_facts[index].statement.strip():
                changed.append((old, new_facts[index]))
        else:
            removed.append(old)
    return [new_facts[index] for index in sorted(remaining)], removed, changed


def _question_roles(result: TechnicalUnderstandingResult) -> dict[str, int]:
    roles: dict[str, int] = {}
    for item in result.uncertainties:
        roles[item.question_role] = roles.get(item.question_role, 0) + 1
    return roles
