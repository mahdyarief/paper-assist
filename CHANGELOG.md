# Changelog

## Unreleased

- Security: workspace containment now rejects `..` segments. Previously
  `ws/../other.tex` passed the lexical check, so `writing_patch` could write a
  `.tex` file outside the workspace. `pack_task`/`writing_task` validate
  `task_id`, `writing_patch` `replacement_path` and Research OS `ris_paths`
  use the same containment as every other workspace read.
- MCP: every tool publishes a real `inputSchema` (names, types, defaults,
  required); unknown arguments are rejected instead of silently dropped;
  execution failures return `isError: true`; `resources/read` works with
  per-run parameters in the URI query string; only declared tools are callable.
- The run-lock wait message goes to stderr so it cannot corrupt the JSON-RPC
  stream.
- `harness_status` reads MCP servers from `plugin.json` (`.mcp.json` is
  optional and merged when present).
- Fixed the ACM profile's `template_formats` (a string, listed as `t`,`e`,`x`).
- Added the `research-workflow` skill that drives the MCP tools end to end, a
  Claude Code marketplace manifest, and tests for the MCP layer, packs,
  patching, protected blocks, LaTeX/style guards, path safety and memory.
- ruff and mypy are clean; a duplicated test that shadowed another was removed.
- Added an advisory `formulaic_prose` quality dimension that flags generic
  Indonesian phrasing and unusually uniform sentence rhythm. It is a review
  signal, not an authorship detector, and does not penalise standard academic
  vocabulary.
- Added default Indonesian anti-slop guidance to the `write-section`,
  `refine-section`, and `de-aigc-rewrite` skills and to generated section
  instructions, without changing any claims, citations, or numbers.

## 4.0.1

- Added `journal_lookup` MCP tool and `paperassist://journal-profiles` resource:
  curated, citable format references for Indonesian (SINTA/JTIM) and
  international (Elsevier/IEEE/Springer Nature/ACM) journals, plus heuristic
  `\documentclass` detection. Includes explicit note that stock `article`
  abstracts use `\small` + `quotation` (inset), not full `\textwidth`.
- Added `paperassist/journal_profiles.py` and focused tests.

## 3.0.0

- Added the unified Research OS runtime, typed agents, profiles, approvals,
  recovery, and idempotent workflow events.
- Added SQLite Scientific Memory and sentence-level Claim/Evidence publication
  gates.
- Added verified experiment provenance and six compute backend contracts.
- Added generic, CVPR, IEEE, and Elsevier publication profiles with bounded
  layout repair and deterministic source bundles.
- Added a single provider configuration/request path and fail-closed Bailu
  authentication handling.
- Added authoritative release verification, secret scanning, safe artifact
  preview, third-party source locks, and MambaIR-GPPNN writing-only delivery.
- Removed legacy Alpha documentation, generated demo results, cached
  environments, and obsolete shell-key setup.
