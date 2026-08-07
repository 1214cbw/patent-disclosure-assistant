"""Remove machine-populated values from fields reserved for human review.

This explicit migration is idempotent. It does not change source expressions,
normalized formulas, evidence IDs, review statuses, or human-modified equations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patent_agent.core.atomic import atomic_write_json


def migrate(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for equation in payload.get("equations", []):
        if equation.get("human_formula") is not None and not equation.get("human_modified", False):
            equation["human_formula"] = None
            changed += 1
    if changed:
        atomic_write_json(path, payload)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    total = 0
    for path in args.paths:
        count = migrate(path)
        total += count
        print(f"{path}: sanitized={count}")
    print(f"total_sanitized={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
