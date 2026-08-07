from pathlib import Path

from patent_agent.progress import ProgressManager


def test_progress_resume_after_failure_and_completed_is_idempotent(tmp_path: Path):
    manager = ProgressManager(tmp_path)
    record = manager.start(task="test", phase="P1", subphase="stage-a", next_step="run")
    failed = manager.fail(record, error_code="SIMULATED", reason="test failure")
    assert failed.status == "FAILED"
    resumed = manager.resume()
    assert resumed.status == "READY_TO_RESUME"
    completed = manager.complete(resumed, completed_step="stage-a", next_step="stage-b", tests="PASS")
    assert manager.resume().status == "COMPLETED"
    assert completed.stage_states["stage-a"] == "COMPLETED"


def test_human_gate_is_not_crossed(tmp_path: Path):
    manager = ProgressManager(tmp_path)
    record = manager.start(task="real", phase="A1", subphase="review", next_step="human review", case_id="REAL-1")
    waiting = manager.wait_for_human(record, reason="A1 review required", next_step="human approves A1")
    resumed = manager.resume("REAL-1")
    assert resumed.status == "WAITING_FOR_HUMAN_REVIEW"
    assert resumed.blocking_reason == "A1 review required"
