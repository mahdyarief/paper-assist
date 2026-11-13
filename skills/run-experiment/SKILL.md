---
name: run-experiment
description: Implement and run a controlled experiment through PaperAssist packs, with artifact hashes and metric validation. Use when a selected idea needs code, a smoke run, and a full run.
---

# Run Experiment

PaperAssist never executes the model or writes the method for you. It defines
the experiment contract and verifies that the recorded numbers came from a real
command with hashed artifacts.

## Workflow

```bash
paperassist pack --kind experiment --workspace . --run-id exp-1 \
  --hypothesis "Sparse attention preserves recall at 4x speed" \
  --dataset "LongBench" --metric accuracy --metric latency_ms \
  --success-criteria "accuracy within 1 point, latency halved"
```

Tasks, in order: `implement` → `static-check` → `mini-run` → `full-run`.

- Put code inside the workspace and record its relative paths in `code_paths`.
- Run the mini experiment first; confirm every declared metric is produced.
- For the full run, fill `.paperassist/packs/experiment/exp-1/experiment.json`:

```json
{
  "status": "COMPLETED",
  "command": "python experiments/run.py --config configs/full.yaml",
  "code_paths": ["experiments/run.py", "configs/full.yaml"],
  "metrics": {"accuracy": 0.812, "latency_ms": 143.2},
  "artifacts": [{"path": "runs/full/metrics.json", "sha256": "<real hash>"}],
  "notes": "seed=0, single A100"
}
```

Import:

```bash
paperassist pack --kind experiment --workspace . --run-id exp-1 --import \
  .paperassist/packs/experiment/exp-1/experiment.json
```

The import fails on: non-numeric metrics, missing declared metrics, a missing
code path, an artifact hash mismatch, a missing command, or status outside
`COMPLETED|FAILED|BLOCKED`.
