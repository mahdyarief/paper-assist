---
name: paperassist
description: Operate PaperAssist end to end. Use when planning research, running controlled experiments, writing LaTeX manuscripts, reviewing a paper, or preparing a release. PaperAssist ships no language model; this session is the executor.
---

# PaperAssist

PaperAssist is a deterministic research runtime plus a task-pack protocol. It
owns no model, no provider client and no credentials. You (the harness) do all
generation; PaperAssist scaffolds the work and validates the result.

## Core loop

1. **Scaffold a pack** for the phase you are in.
2. **Read the plan and tasks** (`plan.json`, `agent-brief.md`, `tasks/*.json`).
3. **Do the work** in the workspace, editing the pack target file.
4. **Import the result.** Never declare success yourself: import returns the
   deterministic verdict and the artifact record.

## Commands

```bash
# ideation
paperassist pack --kind ideation --workspace . --topic "..." --venue "..."
paperassist pack --kind ideation --workspace . --run-id <id> --import ideas.json

# experiment
paperassist pack --kind experiment --workspace . --hypothesis "..." \
  --metric accuracy --metric f1 --dataset "..."
paperassist pack --kind experiment --workspace . --run-id <id> --import experiment.json

# review
paperassist pack --kind review --workspace . --manuscript main.tex
paperassist pack --kind review --workspace . --run-id <id> --import review.json

# writing
paperassist write --workspace . --title "..." --topic "..."
paperassist write --workspace . --run-id <id> --import draft.tex

# readiness (no provider, no keys)
paperassist preflight --workspace .
```

The same tools are exposed over MCP as `pack_scaffold`, `pack_plan`,
`pack_task`, `pack_import`, `harness_status`, plus the `writing_*` tools.

## Non-negotiable rules

- Never invent numbers, datasets, baselines, hardware, citations, or reviewers.
- Every quantitative claim must trace to a run log, artifact, or bibliography
  entry in the workspace.
- Preserve every `PAPERASSIST-PROTECTED-EXPERIMENT` block byte-for-byte.
- Do not add API keys, provider configs, or model names to the workspace.
- If a gate rejects the import, fix the artifact; do not bypass the gate.

## Packs

Packs live under `.paperassist/packs/<kind>/<run-id>/`. Validated results are
recorded under `.paperassist/ideation/`, `.paperassist/experiments/`,
`.paperassist/review/` and `.paperassist/revision/`.
