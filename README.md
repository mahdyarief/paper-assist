# PaperAssist

<p align="center">
  <a href="https://github.com/QJHWC/PaperAssist/actions/workflows/ci.yml">
    <img src="https://github.com/QJHWC/PaperAssist/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" />
  </a>
  <img src="https://img.shields.io/badge/version-v4.0.0-2563eb" alt="Version v4.0.0" />
  <img src="https://img.shields.io/badge/Python-3.10--3.12-3776ab?logo=python&logoColor=white" alt="Python 3.10-3.12" />
</p>

**English** · [Bahasa Indonesia](README.id.md)

PaperAssist is a model-free research runtime and an OpenClaude / Claude Code
plugin. It plans research, defines controlled experiments, prepares LaTeX
writing tasks, reviews manuscripts and verifies releases — while **the only
language model is the AI harness you already run**. PaperAssist ships no
provider client, no API key handling and no model selection.

> ⚠️ Disclaimer: this project is for learning and research. Do not use it
> commercially. You are responsible for anything you produce with it.

## Contents

- [What changed in v4](#what-changed-in-v4)
- [How it works](#how-it-works)
- [Install](#install)
- [Using the plugin](#using-the-plugin)
- [Packs and verification](#packs-and-verification)
- [CLI reference](#cli-reference)
- [Workspace layout](#workspace-layout)
- [Scientific integrity](#scientific-integrity)
- [Testing](#testing)
- [License](#license)

## What changed in v4

| Area | v3 | v4 |
|---|---|---|
| Language model | Bundled OpenAI-compatible client, provider registry, credentials | None. The AI harness is the executor (`executor: "ai-harness"`, `provider_calls: 0`) |
| Generation | In-process agent runtime called the model | Deterministic task packs the harness executes |
| Integration | Custom CLI only | OpenClaude / Claude Code plugin with skills and an MCP server |
| Runtime | `ResearchOSRuntime` orchestrated agents | Removed. Pack → harness → import gate *is* the runtime |
| Review / ideation / experiment | Direct model calls | `pack --kind review\|ideation\|experiment` with validated imports |
| Package | `paperforge` | `paperassist` |

## How it works

```mermaid
flowchart LR
    U["Researcher or agent"] --> S["Skill / MCP tool / CLI"]
    S --> P["Task pack<br/>plan.json + tasks + brief"]
    P --> H["AI harness<br/>(OpenClaude, Claude Code, Freebuff)"]
    H --> R["Result file<br/>ideas.json / review.json / experiment.json / draft.tex"]
    R --> G["Import gate<br/>deterministic validation"]
    G --> A["Artifacts + SQLite memory"]
```

PaperAssist never generates text. It owns:

- **Planning**: packs, task lists, briefs, acceptance rules.
- **Binding**: proposals, compute bindings, protected experiment blocks.
- **Verification**: citation keys, score ranges, artifact hashes, release gates.

## Install (OpenClaude user-level plugin)

Tambahkan ke direktori plugin user OpenClaude:

```bash
cp -r . /c/Users/<you>/.openclaude/plugins/paper-assist
```

Atau clone langsung:

```bash
git clone https://github.com/QJHWC/PaperAssist.git ~/.openclaude/plugins/paper-assist
```

Lalu aktifkan plugin:

```bash
cd ~/.openclaude/plugins/paper-assist
python -m pip install -r requirements-core.txt
```

Cek status:

```bash
python mcp_servers/stdio.py
```

## Menggunakan plugin

Plugin ini dideklarasikan oleh `.claude-plugin/plugin.json`; skill dan
MCP server `paperassist` berada di `mcp_servers/stdio.py`.

MCP tools: `harness_status`, `pack_scaffold`, `pack_plan`, `pack_task`,
`pack_import`, `writing_pack`, `writing_plan`, `writing_task`,
`writing_import`, `writing_patch`.

## Packs and verification

```bash
# ideation
paperassist pack --kind ideation --workspace . --topic "..." --venue NeurIPS
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
```

Every import runs deterministic gates before anything is recorded:

- **Ideation**: exactly one selected idea, hypothesis and evaluation plan
  present, every reference key resolvable, no secret-like content.
- **Experiment**: declared metrics present and numeric, code paths exist,
  artifact SHA-256 matches, `status` in `COMPLETED|FAILED|BLOCKED`.
- **Review**: NeurIPS rating ranges, `Decision` in `Accept|Reject`, no empty
  summary; produces `.paperassist/revision/review-revision.{json,md}`.
- **Writing**: protected `PAPERASSIST-PROTECTED-EXPERIMENT` blocks byte-equal,
  citations resolve to the allowed bibliography, no secrets.

## CLI reference

| Command | Purpose |
|---|---|
| `paperassist preflight` | Harness, MCP and LaTeX readiness (no credentials) |
| `paperassist pack --kind …` | Scaffold, inspect or import ideation/review/experiment packs |
| `paperassist write` | Scaffold, patch or import a writing pack |
| `paperassist run --profile writing-only\|research\|full` | Create a workflow run and scaffold its pack |
| `paperassist resume` | Re-scaffold or reuse the persisted pack |
| `paperassist approve` | Approve a full-experiment proposal |
| `paperassist publish` | Build the PDF with a publication template |
| `paperassist release` | Recompute the release gate and write the manifest |
| `paperassist status` / `unified_status` | Read workflow truth |

## Workspace layout

```text
<workspace>/
├── .paperassist/
│   ├── paperassist.db          # workflows, claims, evidence, artifacts
│   ├── packs/<kind>/<run-id>/  # plan.json, agent-brief.md, tasks/, target
│   ├── ideation/<run-id>/      # validated ideas.json
│   ├── experiments/<run-id>/   # validated result.json
│   ├── review/<run-id>/        # validated review.json
│   ├── revision/               # revision tasks derived from a review
│   ├── publication/
│   └── release_manifest.json
├── artifacts/
├── main.tex
└── references.bib
```

## Scientific integrity

- No invented metrics, datasets, baselines, hardware or citations.
- Every quantitative claim must trace to a run, artifact or bibliography entry.
- Protected experiment blocks are author-owned and byte-preserved.
- Full experiments require an approved proposal with an immutable compute
  binding; a changed script fails verification.
- Secrets are rejected at input, never written into a workspace.

## Testing

```bash
python -m pytest tests -q
```

The suite covers packs, gates, writing protection, compute bindings,
publication and release verification. Integration gates for real
Docker/SSH/Slurm/Kubernetes backends stay opt-in via environment variables.

## License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
