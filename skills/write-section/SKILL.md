---
name: write-section
description: Section-level paper writing. Draft a single section without taking over the scientist / mvp / writeup pipeline.
---

# Write Section

## Purpose

Write one section at a time. This skill does not own the pipeline, the stage
order or the round budget.

## Input

- `section_name`
- `notes`
- `idea_metadata`
- `style_policy`
- `existing_tex_context`

## Output

- draft text for a single section
- optional in-section structural suggestions

## Boundaries

This skill does:
- write one section

This skill does not:
- decide whether cite / refine / latex_fix runs next
- decide the next phase
- modify global checkpoints
- write the final PDF

## Typical sections

- Introduction
- Background
- Method
- Experimental Setup
- Results
- Conclusion
