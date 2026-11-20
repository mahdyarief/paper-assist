"""Method rigour and limitations, judged against the research design's reporting standard."""

from __future__ import annotations

import re
from typing import Any

from ..reporting_checks import (
    FlowCheck,
)
from ..research_designs import DESIGNS, STATISTICS_SIGNALS, ResearchDesign
from ._base import (
    DEFAULT_WEIGHTS,
    Dimension,
    Finding,
    _clamp,
    _count_words,
    _heading_body,
    _section_bodies,
    _strip_latex,
)

# Signal tables live in the research-design registry; these names keep the
# general review and empirical tables addressable for callers and tests.
_REVIEW_METHOD_SIGNALS = DESIGNS["systematic_review"].method_signals
_REVIEW_REPRO_SIGNALS = DESIGNS["systematic_review"].repro_signals
_EMPIRICAL_METHOD_SIGNALS = DESIGNS["empirical"].method_signals
_EMPIRICAL_REPRO_SIGNALS = DESIGNS["empirical"].repro_signals
_STATISTICS_SIGNALS = STATISTICS_SIGNALS


def _flow_findings(flow: FlowCheck | None) -> tuple[float, list[Finding]]:
    """PRISMA 2020 flow-diagram arithmetic as a score part and findings."""

    if flow is None or not flow.available:
        return 0.5, [
            Finding(
                dimension="method_rigour",
                severity="info",
                message="no PRISMA flow counts supplied; flow arithmetic not checked",
                remedy=(
                    "pass the flow document (e.g. prisma_flow.json with identified, "
                    "duplicates_removed, screened, excluded_screening, sought, "
                    "not_retrieved, assessed, excluded_fulltext, included)"
                ),
            )
        ]
    findings = [
        Finding(
            dimension="method_rigour",
            severity="critical",
            message=(
                f"PRISMA flow does not add up at {identity.name}: "
                f"{identity.formula} = {identity.expected}, reported {identity.reported}"
            ),
            remedy="correct the flow counts so every stage follows from the one before",
        )
        for identity in flow.identities
        if not identity.passed
    ]
    if flow.unchecked:
        findings.append(
            Finding(
                dimension="method_rigour",
                severity="info",
                message="PRISMA flow stages not checkable: " + ", ".join(flow.unchecked),
                remedy="report every count of the PRISMA 2020 flow diagram",
            )
        )
    if not flow.identities:
        return 0.5, findings
    passed = sum(1 for identity in flow.identities if identity.passed)
    return passed / len(flow.identities), findings


def _dimension_method(
    text: str,
    *,
    paper_type: str = "review",
    flow: FlowCheck | None = None,
    design: ResearchDesign | None = None,
) -> Dimension:
    """Method rigour: 0.6 method items + 0.2 reproducibility + 0.2 results/flow.

    ``design`` selects the reporting standard (see
    :mod:`paperassist.research_designs`); without one, ``paper_type`` selects
    the general systematic-review or empirical standard.
    """

    if design is None:
        design = DESIGNS["systematic_review" if paper_type == "review" else "empirical"]
    bodies = _section_bodies(text)
    method = bodies.get("method", "")
    lowered = _strip_latex(method).lower()
    findings: list[Finding] = []
    base: dict[str, Any] = {
        "paper_type": design.family,
        "research_design": design.key,
        "guideline": design.guideline,
    }
    if not method:
        findings.append(
            Finding(
                dimension="method_rigour",
                severity="critical",
                message="no method section",
                remedy="describe the procedure so another team could repeat it",
            )
        )
        return Dimension(
            name="method_rigour",
            score=0.0,
            weight=DEFAULT_WEIGHTS["method_rigour"],
            measurements={**base, "signals": [], "repro": []},
            findings=tuple(findings),
        )
    method_signals, repro_signals = design.method_signals, design.repro_signals
    covered = [name for name, pattern in method_signals if re.search(pattern, lowered)]
    missing = [name for name, _ in method_signals if name not in covered]
    for name in missing:
        findings.append(
            Finding(
                dimension="method_rigour",
                severity="warning",
                message=f"method does not describe: {name}",
                remedy=f"add the {name}, as {design.guideline} asks",
            )
        )
    whole = _strip_latex(text).lower()
    repro = [name for name, pattern in repro_signals if re.search(pattern, whole)]
    measurements: dict[str, Any] = {
        **base,
        "signals": covered,
        "missing": missing,
        "repro": repro,
    }
    if design.flow == "prisma":
        third, flow_notes = _flow_findings(flow)
        findings.extend(flow_notes)
        measurements["prisma_flow"] = flow.to_dict() if flow else None
    else:
        results_signals = design.results_signals or STATISTICS_SIGNALS
        # The raw body keeps \pm and quotation marks that some signals need.
        raw_results = bodies.get("results", "")
        results = (_strip_latex(raw_results) + "\n" + raw_results).lower()
        reported = [name for name, pattern in results_signals if re.search(pattern, results)]
        measurements["results_items"] = reported
        if results_signals == STATISTICS_SIGNALS:
            measurements["statistics"] = reported
        if raw_results.strip() and len(reported) < len(results_signals):
            absent = [name for name, _ in results_signals if name not in reported]
            remedy = (
                "report variability (SD/CI), effect size or test result, and "
                "sample size beside each headline number"
                if set(absent) <= {name for name, _ in STATISTICS_SIGNALS}
                else f"report these in the results, as {design.guideline} expects"
            )
            findings.append(
                Finding(
                    dimension="method_rigour",
                    severity="warning",
                    message="results do not report: " + ", ".join(absent),
                    remedy=remedy,
                )
            )
        third = len(reported) / len(results_signals) if raw_results.strip() else 0.0
    if design.notes:
        measurements["notes"] = design.notes
    score = (
        0.6 * (len(covered) / len(method_signals))
        + 0.2 * (len(repro) / len(repro_signals) if repro_signals else 1.0)
        + 0.2 * third
    )
    return Dimension(
        name="method_rigour",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["method_rigour"],
        measurements=measurements,
        findings=tuple(findings),
    )


def _dimension_limitations(text: str) -> Dimension:
    bodies = _section_bodies(text)
    lowered = text.lower()
    findings: list[Finding] = []
    present = "limitations" in bodies
    if not present:
        # A Limitations subsection inside the Discussion is a dedicated,
        # findable statement too, and is common in journal templates.
        nested = _heading_body(text, "limitations")
        if nested.strip():
            bodies = {**bodies, "limitations": nested}
            present = True
    if not present:
        findings.append(
            Finding(
                dimension="limitations",
                severity="warning",
                message="no limitations section and no explicit limitation statement",
                remedy=(
                    "add a limitations section covering corpus, method and "
                    "generalisability"
                ),
            )
        )
    has_threats = bool(
        re.search(r"threats? to validity|validitas|keterbatasan|limitation", lowered)
    )
    score = 0.0
    if present:
        body = _strip_latex(bodies["limitations"])
        score = 0.6 + 0.4 * min(1.0, _count_words(body) / 150)
    elif has_threats:
        score = 0.45
    return Dimension(
        name="limitations",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["limitations"],
        measurements={"section_present": present, "explicit_statement": has_threats},
        findings=tuple(findings),
    )
