---
name: ideate
description: Generate and stress-test research ideas with PaperAssist. Use when the user wants candidate directions, novelty checks, or a ranked shortlist before committing compute.
---

# Ideate

PaperAssist turns idea generation into an auditable pack. You produce the
ideas; the import gate checks the structure and citation keys.

## Workflow

```bash
paperassist pack --kind ideation --workspace . \
  --topic "retrieval-augmented verification" \
  --venue "NeurIPS" --num-ideas 5 --run-id idea-1
```

Then, in order:

1. `literature-scan` — search the `literature` MCP server; write the closest
   prior work to `literature.md`. Cite real keys only.
2. `idea-cards` — fill `.paperassist/packs/ideation/idea-1/ideas.json`.
3. `novelty-check` — score `novelty` and `feasibility` (1-5) and record the
   strongest objection per idea.
4. `rank-and-select` — mark **exactly one** idea `"selected": true`.

Import:

```bash
paperassist pack --kind ideation --workspace . --run-id idea-1 --import \
  .paperassist/packs/ideation/idea-1/ideas.json
```

## Idea card contract

Each idea needs: `title`, `problem`, `hypothesis`, `approach`,
`evaluation_plan`, `novelty` (1-5), `feasibility` (1-5), `risks` (list),
`references` (bibliography keys), `selected` (bool).

Rejections to expect: missing hypothesis, empty evaluation plan, a reference
key that is not in `references.bib`, zero or multiple selected ideas, or
secret-like content.
