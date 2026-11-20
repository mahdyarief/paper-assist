"""Declarations and references dimensions: what an editor checks before review."""

from __future__ import annotations

from ..reporting_checks import (
    DeclarationCheck,
    ReferenceAudit,
)
from ._base import (
    DEFAULT_WEIGHTS,
    Dimension,
    Finding,
    _clamp,
)

_DECLARATION_REMEDIES: dict[str, str] = {
    "competing_interests": 'state competing interests, or "none" (ICMJE; publisher declarations)',
    "funding": "name each funder and grant number, or state that no funding was received",
    "data_availability": "say where the data can be obtained, or why it cannot be shared",
    "ai_use": (
        "disclose which AI tools were used, for what, and that the authors take "
        "responsibility (ICMJE, COPE); state none if no tool was used"
    ),
    "author_contributions": "list each author's CRediT roles (ANSI/NISO Z39.104-2022)",
    "code_availability": "link the code or state why it is not released",
    "ethics": "report ethics approval and informed consent for human participants",
}


def _dimension_declarations(check: DeclarationCheck) -> Dimension:
    findings = [
        Finding(
            dimension="declarations",
            severity="warning",
            message=f"missing declaration: {name.replace('_', ' ')}",
            remedy=_DECLARATION_REMEDIES[name],
        )
        for name in check.missing
    ]
    findings.extend(
        Finding(
            dimension="declarations",
            severity="info",
            message=f"recommended declaration absent: {name.replace('_', ' ')}",
            remedy=_DECLARATION_REMEDIES[name],
        )
        for name in check.recommended_missing
    )
    required = len(check.required)
    score = (required - len(check.missing)) / required if required else 1.0
    return Dimension(
        name="declarations",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["declarations"],
        measurements=check.to_dict(),
        findings=tuple(findings),
    )


def _dimension_references(audit: ReferenceAudit | None) -> Dimension:
    if audit is None or not audit.entries:
        return Dimension(
            name="references",
            score=0.5,
            weight=DEFAULT_WEIGHTS["references"],
            measurements={"entries": 0},
            findings=(
                Finding(
                    dimension="references",
                    severity="info",
                    message="no parsed bibliography; reference recency and type not measured",
                    remedy="pass bibliography_path so references can be audited",
                ),
            ),
        )
    policy = audit.policy
    findings: list[Finding] = []
    for key, doi, nature in audit.retracted:
        severity = "critical" if "retract" in nature.lower() else "warning"
        findings.append(
            Finding(
                dimension="references",
                severity=severity,
                message=f"cited work {key} ({doi}) is flagged: {nature}",
                remedy=(
                    "remove or replace the citation, or cite it explicitly as "
                    "retracted with the retraction notice"
                ),
            )
        )
    if audit.with_year and audit.recent_share < policy.min_recent_share:
        findings.append(
            Finding(
                dimension="references",
                severity="warning",
                message=(
                    f"{audit.recent_share:.0%} of references are from the last "
                    f"{policy.recent_years} years (target {policy.min_recent_share:.0%})"
                ),
                remedy="support the state of the art with recent primary literature",
            )
        )
    if audit.primary_share < policy.min_primary_share:
        findings.append(
            Finding(
                dimension="references",
                severity="warning",
                message=(
                    f"{audit.primary_share:.0%} of references are journal or conference "
                    f"papers (target {policy.min_primary_share:.0%})"
                ),
                remedy="prefer primary peer-reviewed sources over books, web pages and preprints",
            )
        )
    missing_year = audit.entries - audit.with_year
    if missing_year:
        findings.append(
            Finding(
                dimension="references",
                severity="info",
                message=f"{missing_year} reference(s) have no year",
                remedy="complete the year field so recency can be audited",
            )
        )
    recent_part = (
        min(1.0, audit.recent_share / policy.min_recent_share)
        if policy.min_recent_share
        else 1.0
    )
    primary_part = (
        min(1.0, audit.primary_share / policy.min_primary_share)
        if policy.min_primary_share
        else 1.0
    )
    score = 0.5 * recent_part + 0.5 * primary_part
    retracted = sum(1 for _, _, nature in audit.retracted if "retract" in nature.lower())
    if retracted:
        score *= 0.5
    return Dimension(
        name="references",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["references"],
        measurements=audit.to_dict(),
        findings=tuple(findings),
    )
