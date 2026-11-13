---
name: review-paper
description: Peer-review a manuscript through PaperAssist, with claim-to-evidence auditing and a validated NeurIPS-style review. Use when the user asks for a critical review, a mock reviewer report, or a revision plan.
---

# Review Paper

PaperAssist scaffolds the review and validates every score; the harness writes
the judgement. Reviews are recorded and converted into revision tasks.

## Workflow

```bash
paperassist pack --kind review --workspace . --run-id rev-1 \
  --manuscript main.tex --venue "NeurIPS"
```

Tasks: `read-manuscript` → `evidence-audit` → `score-and-decide` →
`revision-plan`.

Fill `.paperassist/packs/review/rev-1/review.json`:

- `Summary` is neutral and would be accepted by the authors.
- `Strengths`, `Weaknesses`, `Questions`, `Limitations` are string lists.
- `Originality`, `Quality`, `Clarity`, `Significance`, `Soundness`,
  `Presentation`, `Contribution`: 1-4.
- `Overall`: 1-10. `Confidence`: 1-5. `Ethical Concerns`: boolean.
- `Decision`: exactly `Accept` or `Reject`.

Import:

```bash
paperassist pack --kind review --workspace . --run-id rev-1 --import \
  .paperassist/packs/review/rev-1/review.json
```

On success PaperAssist writes `.paperassist/review/rev-1/review.json` and
`.paperassist/revision/review-revision.json|.md` (weaknesses first, then
questions, each with a priority). Apply those tasks through the writing pack,
never by editing protected experiment blocks.
