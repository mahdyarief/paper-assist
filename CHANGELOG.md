# Changelog

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
