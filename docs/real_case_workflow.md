# Real Case Workflow

## 1. Create an authorized case

Use a `REAL-` prefix. This command creates a private, Git-ignored case and does not ingest material:

```powershell
python -m app.cli real-case-create REAL-2026-001 --title "待确认的发明名称" --authorized
```

For a local model, both global and case policy must say `local`:

```powershell
$env:PATENT_LLM_MODE="local"
python -m app.cli real-case-create REAL-2026-001 --authorized --llm-mode local
```

For an external provider, also pass `--external-llm-approved`. Do this only after confidentiality approval. The system will not infer approval from an available API key.

## 2. Explicitly ingest material

```powershell
python -m app.cli real-case-ingest REAL-2026-001 D:\approved-materials\paper.docx
```

An explicitly named directory is accepted. The system does not look elsewhere for related files.

## 3. Generate Checkpoint A1 only

```powershell
python -m app.cli real-case-a1 REAL-2026-001
```

The first run stops at `review/checkpoint_A1/`. It does not mine inventions, draft Claims or generate Word. Inspect:

- `technical_understanding_review.md`
- `evidence_coverage.md`
- `terminology_review.md`
- `inventor_questions.md`
- `review_objects.json`
- `review_input.json`

## 4. Review A1

Copy `review_input.json` and add strict-schema `HumanCorrection` objects. Supported fact actions are `ACCEPT`, `EDIT`, `REJECT`, `ADD`, `DELETE` and explicit `UNLOCK`.

```powershell
python -m app.cli checkpoint-import REAL-2026-001 D:\safe-review\a1_review.json
python -m app.cli checkpoint-approve REAL-2026-001 A1
```

An incomplete review is rejected. Human edits are versioned, locked and propagated as downstream `STALE` state.

## 5. Continue to A2

```powershell
python -m app.cli checkpoint-continue REAL-2026-001
```

A2 supports candidate approve/reject/edit/merge/split/rerank. Import and approve its JSON exactly as for A1.

## 6. Enter Checkpoint B

Prior art must be explicitly supplied:

```powershell
python -m app.cli checkpoint-continue REAL-2026-001 --prior-art D:\approved-search\prior_art.json
```

Review the inventive concept, mandatory/dependent features, terminology, parameters, alternatives, support gaps and risk points. Set `scope_strategy` to `Broad`, `Balanced` or `Conservative`; all modes use the same supported feature pool.

Blocking P0 questions must be answered before approval:

```powershell
python -m app.cli real-case-answer REAL-2026-001 Q-002 "发明人确认内容"
python -m app.cli checkpoint-import REAL-2026-001 D:\safe-review\b_review.json
python -m app.cli checkpoint-approve REAL-2026-001 B
```

## 7. Enter Checkpoint C

```powershell
python -m app.cli checkpoint-continue REAL-2026-001
```

Checkpoint C shows Claim text, structured features, parent, support, Evidence, disclosure mapping, novelty and scope risks. Feature operations include add/remove/edit/move/promote. The Claim sentence is rerendered from the feature graph.

```powershell
python -m app.cli checkpoint-import REAL-2026-001 D:\safe-review\c_review.json
python -m app.cli claim-scope REAL-2026-001
python -m app.cli checkpoint-approve REAL-2026-001 C --ack-risk
```

`--ack-risk` is required only when the scope gate reports an acknowledgement warning. Unsupported mandatory independent features remain a hard block.

## 8. Final render

After C approval:

```powershell
python -m app.cli checkpoint-continue REAL-2026-001
```

Final DOCX files are written under the Git-ignored `output/real_case/<CASE_ID>/`. The Document Engine performs OMML/XML and Word COM validation.

## 9. Evaluation

```powershell
python -m app.cli evaluation-report REAL-2026-001 --run-id RUN-001
```

Evaluation snapshots compare models only on fixed Evidence, prompt/schema versions and starting state. External providers require separate authorization for every real-case run.

## Safety reminders

- Never place API keys in review JSON.
- Do not move private case folders into tests or public demo directories.
- Do not use real material for the first paid API smoke test.
- Generated documents require inventor and patent professional review.
