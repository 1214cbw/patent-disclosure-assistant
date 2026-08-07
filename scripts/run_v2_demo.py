from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patent_agent.core.config import Settings
from patent_agent.llm import MockLLMProvider
from patent_agent.llm.demo_mock import SyntheticDemoResponder
from patent_agent.workflow import PatentPipelineV2


if __name__ == "__main__":
    result = PatentPipelineV2(Settings.load(ROOT), MockLLMProvider(responder=SyntheticDemoResponder())).run(
        case_id="PAT-V2-DEMO-001",
        materials=[ROOT / "demo" / "motor_control" / "materials"],
        prior_art=ROOT / "demo" / "motor_control" / "prior_art_demo.json",
        output_dir=ROOT / "output" / "v2_demo",
        auto_approve_demo=True,
        use_word_com=True,
    )
    print({"case_id": result["case_id"], "candidates": len(result["candidates"]), "claims": len(result["claims"].claims), "features": sum(len(claim.features) for claim in result["claims"].claims), "support": result["support_matrix"].validation_status, "broken_traceability": len(result["traceability"].broken_links), "omml": result["validation"]["xml"]["omml_count"], "validation": result["validation"]["pass"]})
