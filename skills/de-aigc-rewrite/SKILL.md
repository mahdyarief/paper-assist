---
name: de-aigc-rewrite
description: De-mechanicalise prose. Compress templated phrasing and obvious AI tone without changing the argument.
---

# De-AIGC Rewrite

## Purpose

Rewrite a paragraph or section once to remove mechanical style, keeping facts
and structure intact.

## Input

- `text`
- `style_goal`

## Output

- `rewritten_text`
- `style_notes`

## Boundaries

This skill does:
- compress expression
- cut templated openings and filler

This skill does not:
- change experimental conclusions
- invent citations
- take over the writeup pipeline
