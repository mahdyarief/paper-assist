---
name: research-writing-prompts
description: Use when the user wants paper-writing prompt templates or wants Codex to automatically choose and apply the best prompt logic for tasks such as translating, polishing, rewriting, shortening, expanding, logic checking, reviewer critique, reducing AI tone, experiment analysis, figure and table captions, model selection, or converting a strong external prompt collection into a reusable paper-writing workflow.
---

# Research Writing Prompts

## Overview

This skill provides a curated prompt library for academic paper writing workflows. Use it when the user wants either:

1. The raw prompt template itself, ready to copy or adapt.
2. A customized prompt rewritten for the user's current paper/project.
3. Direct execution of the prompt logic, where Codex performs the writing task instead of only returning the prompt.

## Quick Start

1. Identify the task type first:
   - translation
   - rewriting / polishing
   - shortening / expansion
   - logic checking
   - reviewer-style critique
   - experiment analysis
   - figure / table naming
   - model selection
2. Read [references/prompt-index.md](references/prompt-index.md) to find the right section.
3. Load only the needed section from [references/prompt-library.md](references/prompt-library.md).
4. Choose one of three output modes:
   - `prompt-only`: return the best prompt template.
   - `prompt-plus-adaptation`: return the source prompt plus a version customized for the user's task or paper.
   - `direct-execution`: apply the prompt logic internally and return the finished writing/result.

## Intent Router

Use this routing table before loading any detailed prompt section.

- If the user says `translate`, `terjemahkan`, `ubah ke bahasa Inggris`, or equivalent:
  route to translation prompts.
- If the user says `polish`, `rewrite`, `perbaiki gaya`, `akademik`, or equivalent:
  route to polish / rewrite prompts.
- If the user says `shorten`, `compress`, `expand`, `ringkas`, `perluas`:
  route to shortening / expansion prompts.
- If the user says `logic is off`, `check the logic`, `cek alurnya`, `flow`:
  route to logic-check prompts.
- If the user says `review like a reviewer`, `tinjau`, `kritik`, `review my paper`:
  route to reviewer-style critique prompts.
- If the user says `remove AI tone`, `more natural`, `kurangi kesan mesin`:
  route to de-AI-tone prompts, but keep claims faithful to the evidence.
- If the user says `analyze the results`, `analisis hasil`, `write the results section`:
  route to experiment-analysis prompts.
- If the user says `figure caption`, `table caption`, `plot advice`, `architecture diagram`:
  route to figure / table / diagram prompts.
- If the user says `model choice`, `pilih model`, `pilih pendekatan`:
  route to model-selection prompts.

If multiple intents appear together, use this priority:
1. reviewer / logic diagnosis
2. translation
3. rewrite / polish
4. shorten / expand
5. experiment / figure / table support
6. model selection

When the user already provides manuscript text, prefer `direct-execution` after routing instead of returning a long prompt block.

## Task Map

- Translation:
  Use `draft-to-english`, `english-to-explanation`, or `draft-to-polished`.
- Rewrite / polish:
  Use `shorten`, `expand`, `polish-english`, `polish-non-english`, or either `reduce-ai-tone` section.
- Review / diagnosis:
  Use `logic-check` or `review-as-reviewer`.
- Experiment writing:
  Use `experiment-analysis`, `architecture-diagram`, `plotting-recommendations`, `figure-titles`, or `table-titles`.
- Research decision support:
  Use `model-selection`.
- Skill onboarding / examples:
  Use `skill-configuration`, `skill-catalogue`, and `usage-scenarios` only when the user asks how to use the repo itself.

## Usage Rules

1. Prefer direct execution when the user has already supplied text, figures, tables, or a LaTeX section to edit.
2. Prefer `prompt-plus-adaptation` when the user says a prompt is useful and wants a reusable task-specific version.
3. Prefer `prompt-only` when the user explicitly asks for the template itself.
4. Preserve the user's target format:
   - LaTeX for paper source editing.
   - plain text for Word-oriented Chinese writing.
   - bilingual output only when the chosen prompt requires it.
5. If the user already has a fixed paper template or storyline, adapt the prompt to that context instead of returning a generic version unchanged.

## For Ongoing Paper Projects

When the user is working on an active paper rather than experimenting with prompts:

1. Extract the useful prompt logic from the library.
2. Translate that logic into direct editing choices on the current manuscript.
3. Keep claims aligned with the user's actual evidence, tables, and figures.
4. Avoid returning large prompt blocks unless the user explicitly wants them.

For benchmark-style papers, prefer prompt logic that emphasizes:
- protocol control,
- claim-evidence alignment,
- clear writing boundaries,
- reviewer-facing justification,
- and distinction between recognition ranking and deployment ranking.

## References

- Use [references/prompt-index.md](references/prompt-index.md) as the navigation layer.
- Use [references/prompt-library.md](references/prompt-library.md) as the source prompt library.
- Do not load the entire prompt library unless the user is explicitly asking for a broad survey of all prompts.
