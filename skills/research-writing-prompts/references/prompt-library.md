# Research Writing Prompt Library

> Writing prompts for academic papers, maintained as part of PaperAssist.
> Original idea and Chinese prompt collection: the public "Make AI Writing
> Better for Everyone" project. This English edition keeps the same task
> families and is adapted for harness-driven writing.

Use these prompts with the harness you run (OpenClaude, Claude Code, Freebuff).
PaperAssist itself never calls a model: it can store the result, validate it and
attach it to a workspace.

## Contents

### Part I — Writing prompts

- [Draft to English paper text](#draft-to-english-paper-text)
- [English paper to Indonesian/Chinese explanation](#english-paper-to-explanation)
- [Draft to polished academic text](#draft-to-polished-academic-text)
- [Shorten](#shorten)
- [Expand](#expand)
- [Polish English paper wording](#polish-english-paper-wording)
- [Polish non-English paper wording](#polish-non-english-paper-wording)
- [Logic check](#logic-check)
- [Reduce AI tone in English LaTeX](#reduce-ai-tone-in-english-latex)
- [Reduce AI tone in Word text](#reduce-ai-tone-in-word-text)

### Part II — Figures, tables and experiments

- [Architecture diagram prompt](#architecture-diagram-prompt)
- [Plotting recommendations](#plotting-recommendations)
- [Figure titles](#figure-titles)
- [Table titles](#table-titles)
- [Experiment analysis](#experiment-analysis)

### Part III — Review and decisions

- [Review the paper as a reviewer](#review-the-paper-as-a-reviewer)
- [Model / route selection](#model--route-selection)

### Part IV — Meta

- [Skill configuration](#skill-configuration)
- [Skill catalogue](#skill-catalogue)
- [Usage scenarios and example prompts](#usage-scenarios-and-example-prompts)

---

## Draft to English paper text

**Role.** You are an academic editor who writes publication-quality English for
top-tier venues.

**Task.** Turn the supplied draft into English paper prose that keeps every
technical claim, number, symbol and citation exactly as given.

**Constraints.**
- Do not add claims, results, datasets or citations that are not in the source.
- Keep LaTeX macros, labels, `\cite{}` keys and protected experiment blocks
  unchanged.
- Prefer plain, precise academic English over marketing language.
- Preserve the original paragraph order unless the logic is broken; then say
  what you moved and why.
- Output LaTeX when the input is LaTeX, otherwise plain text.

**Execution protocol.**
1. Restate the section's purpose in one line.
2. Translate paragraph by paragraph.
3. Check terminology consistency (define once, reuse).
4. List any source sentence you could not render faithfully.

**Input.** `<paste draft>`

---

## English paper to explanation

**Role.** You are a research mentor explaining a paper to a graduate student.

**Task.** Explain the supplied English paper text in Indonesian (or Chinese if
requested), preserving technical meaning.

**Constraints.**
- Keep technical terms in English on first use, with a short gloss.
- Do not simplify away caveats or limitations.
- Mark anything ambiguous instead of guessing.
- Output structured notes: claim, method, evidence, limitation.

**Input.** `<paste English text>`

---

## Draft to polished academic text

**Role.** You are a native-level academic editor in the target language.

**Task.** Polish the draft into publishable academic prose in the same language.

**Constraints.**
- Keep meaning, numbers and citations identical.
- Remove filler, redundancy and informal phrasing.
- Keep sentence length readable; split run-on sentences.
- Do not "upgrade" hedged claims into strong claims.

**Execution protocol.**
1. Identify the paragraph's single main point.
2. Rewrite with topic sentence first.
3. Verify each number and citation survived.

**Input.** `<paste draft>`

---

## Shorten

**Role.** You are a copy editor working under a strict length budget.

**Task.** Shorten the text to roughly the requested ratio without losing claims.

**Constraints.**
- Target 60–70% of the original length unless told otherwise.
- Keep all numbers, citations, definitions and protected blocks.
- Delete redundancy first, then compress phrasing, then merge sentences.
- Report the final word count and the ratio.

**Input.** `<paste text>` `<target ratio>`

---

## Expand

**Role.** You are an academic writer adding necessary detail.

**Task.** Expand the text with explanation, motivation and transition sentences
that the source already implies.

**Constraints.**
- Add no new empirical claims.
- Every added sentence must be supported by the supplied text or by a citation
  the user provides.
- Mark inferred content as `[needs citation]` instead of inventing a reference.

**Input.** `<paste text>` `<target ratio>`

---

## Polish English paper wording

**Role.** You are a reviewer-friendly English academic editor.

**Task.** Improve clarity, precision and flow of the supplied English paper
section.

**Constraints.**
- Keep the author's voice; do not flatten it into generic AI prose.
- Prefer active voice where it does not obscure the actor.
- Fix article, tense and agreement errors.
- Return a diff-style summary of the changes plus the full revised text.

**Input.** `<paste LaTeX or plain text>`

---

## Polish non-English paper wording

**Role.** You are an editor for academic Indonesian or Chinese.

**Task.** Polish the wording while preserving technical accuracy.

**Constraints.**
- Keep established English technical terms where translation would confuse.
- Keep citation markers untouched.
- Do not change the argument structure.

**Input.** `<paste text>`

---

## Logic check

**Role.** You are a strict methodologist reading a draft.

**Task.** Audit the argument for gaps, unsupported jumps and contradictions.

**Constraints.**
- Quote the exact sentence you criticise.
- Classify each issue: `gap`, `contradiction`, `undefined term`, `weak link`,
  `missing evidence`.
- Propose the smallest fix for each issue.
- Do not rewrite the whole text; only repair what you flagged.

**Output format.** A table of `location | issue type | problem | suggested fix`.

**Input.** `<paste section>`

---

## Reduce AI tone in English LaTeX

**Role.** You are an editor who removes mechanical, templated phrasing.

**Task.** Rewrite the text so it reads like a careful human researcher wrote it.

**Constraints.**
- Remove formulaic openings ("In this paper, we propose…" repeated everywhere).
- Replace stacked nominalisations with verbs.
- Vary sentence length; cut empty intensifiers.
- Keep all claims, numbers and citations; never invent support.
- Return the rewritten LaTeX only, plus a short note on what you changed.

**Input.** `<paste LaTeX>`

---

## Reduce AI tone in Word text

**Role.** You are an editor for non-LaTeX academic documents.

**Task.** Same as above, for plain-text or Word-oriented prose.

**Constraints.**
- Keep heading structure and list numbering.
- Do not touch tables or figure captions unless asked.

**Input.** `<paste text>`

---

## Architecture diagram prompt

**Role.** You are a systems communicator who designs publication figures.

**Task.** Propose an architecture figure for the described method.

**Constraints.**
- Use the actual module names from the paper.
- Show data flow direction and tensor/signal shapes where known.
- Keep it readable in a single column; propose a two-panel split if crowded.
- Return a Mermaid or TikZ sketch plus a caption draft.

**Input.** `<method description>`

---

## Plotting recommendations

**Role.** You are a data-visualisation reviewer.

**Task.** Recommend the figure types that best support each claim in the results.

**Constraints.**
- One recommendation per claim, with the chart type and axes.
- Prefer showing variance (error bars, seeds) over single numbers.
- Flag any claim the current data cannot support.

**Input.** `<results table or description>`

---

## Figure titles

**Role.** You are a journal copy editor.

**Task.** Write figure titles that state what the figure shows.

**Constraints.**
- One sentence, no "Figure X shows…" preamble.
- Include the setting (dataset, metric) when it is not in the caption body.
- No claims beyond the plotted data.

**Input.** `<figure description>`

---

## Table titles

**Role.** You are a journal copy editor.

**Task.** Write table titles for the supplied tables.

**Constraints.**
- State the comparison, dataset and metric.
- Keep abbreviations defined at first use in the caption.
- Avoid "Results of…" phrasing.

**Input.** `<table description>`

---

## Experiment analysis

**Role.** You are an experimental scientist writing the results section.

**Task.** Analyse the supplied results and draft the results narrative.

**Constraints.**
- Report only numbers present in the data.
- Separate observation, interpretation and speculation explicitly.
- State variance and sample size when available; otherwise say they are missing.
- Name the strongest alternative explanation for each effect.

**Input.** `<results files or tables>`

---

## Review the paper as a reviewer

**Role.** You are a senior reviewer for a top-tier venue.

**Task.** Produce a structured review of the manuscript.

**Constraints.**
- Sections: summary, strengths, weaknesses, questions, limitations, decision.
- Rate originality, quality, clarity, significance, soundness, presentation and
  contribution from 1 to 4; overall 1–10; confidence 1–5.
- Every weakness must cite the location in the manuscript.
- Do not invent experiments; ask for them in the questions section.

> Tip: `paperassist pack --kind review --manuscript main.tex` produces the same
> schema and validates it on import.

**Input.** `<manuscript>`

---

## Model / route selection

**Role.** You are a research engineer choosing an execution strategy.

**Task.** Compare candidate approaches for the stated goal and recommend one.

**Constraints.**
- Compare on data, compute, risk and expected reviewer reaction.
- Name the cheapest experiment that would falsify the recommendation.
- No preference for a specific vendor or model.

**Input.** `<goal, constraints, resources>`

---

## Skill configuration

This repository exposes its capabilities as an OpenClaude / Claude Code plugin:

- `.claude-plugin/plugin.json` — manifest, skills path, MCP server
- `skills/<name>/SKILL.md` — one skill per task family
- `mcp_servers/stdio.py` — MCP tools for packs and writing

To add a skill: create `skills/<name>/SKILL.md` with `name` and `description`
front matter, then describe inputs, outputs and boundaries. Keep the skill
narrow: one task per skill.

---

## Skill catalogue

| Skill | Scope |
|---|---|
| `paperassist` | Router and hard rules |
| `ideate` | Idea generation and selection |
| `run-experiment` | Experiment implementation and validation |
| `review-paper` | Manuscript review and revision plan |
| `write-section` | Draft one section |
| `refine-section` | Refine one section |
| `latex-fix` | One round of LaTeX repair |
| `citation-gap` / `citation-select` | Citation rounds |
| `de-aigc-rewrite` | Remove mechanical style |
| `research-writing-prompts` | This prompt library |

---

## Usage scenarios and example prompts

**Scenario: first draft of an introduction.**
> Use `write-section` for the Introduction. Notes: gap is X, method is Y,
> contribution is Z. Output LaTeX, max 700 words, cite only `smith2024`.

**Scenario: reviewer simulation before submission.**
> Use `review-paper` on `main.tex`. Focus on whether the ablation supports the
> central claim. Return the validated review JSON only.

**Scenario: experiment plan from a selected idea.**
> Use `run-experiment` with run id `exp-1`. Hypothesis: sparse attention keeps
> recall within 1 point at half the latency. Metrics: accuracy, latency_ms.
