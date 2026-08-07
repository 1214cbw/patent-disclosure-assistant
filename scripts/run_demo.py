from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patent_agent.core.config import Settings
from patent_agent.workflow import PatentPipeline


if __name__ == "__main__":
    pipeline = PatentPipeline(Settings.load(ROOT))
    result = pipeline.run(
        "PAT-2026-DEMO-001",
        [ROOT / "demo" / "motor_control" / "materials"],
        ROOT / "demo" / "motor_control" / "prior_art_demo.json",
        ROOT / "output" / "demo",
        auto_approve_demo=True,
        use_word_com=True,
    )
    print({"case_id": result["case_id"], "candidates": len(result["candidates"]), "claims": len(result["claims"].claims), "figures": len(result["figures"]), "validation": result["validation"]["pass"]})

