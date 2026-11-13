---
name: refine-section
description: Section-level refinement. Tighten logic, wording and structure in a single section.
---

# Refine Section

## Purpose

Refine one section locally while the global state machine stays untouched.

## Input

- `section_name`
- `section_text`
- `tips`
- `error_list`
- `style_policy`

## Output

- refined section text
- optional summary of the changes

## Boundaries

This skill does:
- refine a single section

This skill does not:
- decide whether another round runs
- change global writeup state
- update checkpoints
- compile the PDF

## Typical use

- refining a section right after the init draft
- section-by-section polish in the second refinement pass
