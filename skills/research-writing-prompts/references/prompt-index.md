# Prompt index

Start here. Each task maps to a section in `prompt-library.md`.

## Core writing tasks

| Task | Section |
|---|---|
| Draft to English paper text | [Draft to English paper text](prompt-library.md#draft-to-english-paper-text) |
| English paper to Indonesian/Chinese explanation | [English paper to explanation](prompt-library.md#english-paper-to-explanation) |
| Draft to polished academic text | [Draft to polished academic text](prompt-library.md#draft-to-polished-academic-text) |
| Shorten | [Shorten](prompt-library.md#shorten) |
| Expand | [Expand](prompt-library.md#expand) |
| Polish English paper wording | [Polish English paper wording](prompt-library.md#polish-english-paper-wording) |
| Polish non-English paper wording | [Polish non-English paper wording](prompt-library.md#polish-non-english-paper-wording) |
| Check paragraph / section logic | [Logic check](prompt-library.md#logic-check) |
| Reduce AI tone in English LaTeX | [Reduce AI tone in English LaTeX](prompt-library.md#reduce-ai-tone-in-english-latex) |
| Reduce AI tone in Word text | [Reduce AI tone in Word text](prompt-library.md#reduce-ai-tone-in-word-text) |

## Figures, tables and experiments

| Task | Section |
|---|---|
| Draft an architecture-diagram prompt | [Architecture diagram prompt](prompt-library.md#architecture-diagram-prompt) |
| Ask for plotting recommendations | [Plotting recommendations](prompt-library.md#plotting-recommendations) |
| Generate figure titles | [Figure titles](prompt-library.md#figure-titles) |
| Generate table titles | [Table titles](prompt-library.md#table-titles) |
| Analyse experiment results | [Experiment analysis](prompt-library.md#experiment-analysis) |

## Review and decision support

| Task | Section |
|---|---|
| Review the whole paper | [Review the paper as a reviewer](prompt-library.md#review-the-paper-as-a-reviewer) |
| Choose a model / route | [Model / route selection](prompt-library.md#model--route-selection) |

## Repo / skill meta

| Task | Section |
|---|---|
| Learn how this repo configures skills | [Skill configuration](prompt-library.md#skill-configuration) |
| Understand the skill catalogue | [Skill catalogue](prompt-library.md#skill-catalogue) |
| See example prompts | [Usage scenarios and example prompts](prompt-library.md#usage-scenarios-and-example-prompts) |

## Selection guidance

- If the user already supplied paper text, execute the chosen prompt logic
  directly instead of returning a long prompt block.
- If the user wants a reusable prompt, return the template plus a version
  adapted to their paper.
- If the intent is unclear, pick the narrowest matching section.
