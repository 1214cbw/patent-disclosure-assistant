from patent_agent.core.exceptions import CheckpointRequired
from patent_agent.core.state import CaseStore


CHECKPOINTS = {"A": "发明点确认", "B": "保护方案确认", "C": "权利要求确认"}


def require_checkpoint(store: CaseStore, case_id: str, name: str, auto_approve: bool = False):
    if auto_approve:
        store.approve_checkpoint(case_id, name, "approve", "auto-approved for synthetic demo")
        return
    if not store.checkpoint_approved(case_id, name):
        raise CheckpointRequired(f"Checkpoint {name} ({CHECKPOINTS[name]}) requires approve/edit/regenerate/back")

