"""Structure, abstract and depth dimensions: is the paper complete and substantive?"""

from __future__ import annotations

import re
from typing import Any

from ._base import (
    _ABSTRACT_RE,
    DEFAULT_WEIGHTS,
    Dimension,
    Finding,
    _clamp,
    _count_words,
    _section_bodies,
    _strip_latex,
)

# Analytic prose a review needs per included study before it can report what
# each one contributed. Twenty five words is roughly two substantive sentences:
# enough for a design, a method and a reported result, which is the minimum a
# synthesis entry carries. Used only when the corpus size is known.
_STUDY_WORDS = 25


def _dimension_structure(text: str, *, depth_target: int) -> Dimension:
    bodies = _section_bodies(text)
    required = ("introduction", "method", "results", "discussion", "conclusion")
    present = [name for name in required if name in bodies]
    findings: list[Finding] = []
    for name in required:
        if name not in bodies:
            findings.append(
                Finding(
                    dimension="structure",
                    severity="critical",
                    message=f"missing required section: {name}",
                    remedy=f"add a {name} section with its own content, not a pointer",
                )
            )
    word_counts = {
        name: _count_words(_strip_latex(body)) for name, body in bodies.items()
    }
    thin = [
        name
        for name, count in word_counts.items()
        if name in required and count < depth_target // 3
    ]
    for name in thin:
        findings.append(
            Finding(
                dimension="structure",
                severity="warning",
                message=f"section '{name}' is thin ({word_counts[name]} words)",
                remedy=(
                    f"expand '{name}' to at least {depth_target // 3} words "
                    "with concrete content"
                ),
            )
        )
    score = len(present) / len(required)
    if thin:
        score *= 0.85
    return Dimension(
        name="structure",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["structure"],
        measurements={
            "required_sections": list(required),
            "present_sections": present,
            "section_words": word_counts,
        },
        findings=tuple(findings),
    )


def _dimension_abstract(text: str) -> Dimension:
    match = _ABSTRACT_RE.search(text)
    findings: list[Finding] = []
    if not match:
        findings.append(
            Finding(
                dimension="abstract",
                severity="critical",
                message="no abstract environment found",
                remedy="wrap the summary in \\begin{abstract}...\\end{abstract}",
            )
        )
        return Dimension(
            name="abstract",
            score=0.0,
            weight=DEFAULT_WEIGHTS["abstract"],
            measurements={"words": 0, "sections_covered": []},
            findings=tuple(findings),
        )

    body = match.group(1)
    words = _count_words(_strip_latex(body))
    lowered = body.lower()
    checks = {
        "objective": r"tujuan|kajian ini|this (?:study|review|paper)|we (?:review|examine|map)",
        "scope": r"studi|records|articles|basis data|database|rentang|20\d\d",
        "method": r"prisma|scoping|sistemati|systematic|pencarian|search",
        "result": r"hasil|menunjukkan|menemukan|found|show|reveal|score|skor",
        "conclusion": r"kesimpulan|rekomendasi|recommend|menyimpulkan|conclude",
    }
    covered = [name for name, pattern in checks.items() if re.search(pattern, lowered)]
    score = len(covered) / len(checks)
    if words < 120:
        score *= 0.7
        findings.append(
            Finding(
                dimension="abstract",
                severity="warning",
                message=f"abstract is short ({words} words)",
                remedy=(
                    "state objective, scope, method, results and conclusion in "
                    "about 150-250 words"
                ),
            )
        )
    if words > 400:
        findings.append(
            Finding(
                dimension="abstract",
                severity="warning",
                message=f"abstract is long ({words} words)",
                remedy="move detail into the body; editors often trim abstracts over 300 words",
            )
        )
    for name in checks:
        if name not in covered:
            findings.append(
                Finding(
                    dimension="abstract",
                    severity="warning" if name == "result" else "info",
                    message=f"abstract does not state {name}",
                    remedy=f"add one sentence covering {name}",
                )
            )
    return Dimension(
        name="abstract",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["abstract"],
        measurements={"words": words, "sections_covered": covered},
        findings=tuple(findings),
    )


def _dimension_depth(
    text: str, *, depth_target: int, corpus_size: int = 0
) -> Dimension:
    bodies = _section_bodies(text)
    words = {name: _count_words(_strip_latex(body)) for name, body in bodies.items()}
    findings: list[Finding] = []
    thin = sorted(
        (name for name, count in words.items() if count < depth_target),
        key=lambda name: words[name],
    )
    for name in thin[:6]:
        findings.append(
            Finding(
                dimension="depth",
                severity="warning",
                message=f"section '{name}' has {words[name]} words, target is {depth_target}",
                remedy="add analysis rather than restating; each paragraph should carry a claim",
            )
        )
    graded = [
        name
        for name in words
        if name in {"introduction", "method", "results", "discussion", "conclusion"}
    ]
    if not graded:
        return Dimension(
            name="depth",
            score=0.0,
            weight=DEFAULT_WEIGHTS["depth"],
            measurements={"section_words": words},
            findings=tuple(findings),
        )
    ratio = sum(min(1.0, words[name] / depth_target) for name in graded) / len(graded)

    # A review earns its length by synthesising its corpus. Below a floor of
    # analysis per included study the prose cannot carry a per-study finding, and
    # a hundred-study review that fits in a handful of pages has not reported
    # what it read. The floor is a judgement about reporting, not about writing
    # style, so it is stated here as a constant rather than tuned per project.
    measurements: dict[str, Any] = {
        "section_words": words,
        "depth_target": depth_target,
        "total_words": sum(words.values()),
    }
    if corpus_size > 0:
        synthesised = sum(words[name] for name in graded)
        required = max(depth_target * len(graded), _STUDY_WORDS * corpus_size)
        ratio = min(ratio, min(1.0, synthesised / required))
        measurements.update(
            {
                "corpus_records": corpus_size,
                "synthesis_words": synthesised,
                "synthesis_target": required,
            }
        )
        if synthesised < required:
            findings.append(
                Finding(
                    dimension="depth",
                    severity="critical" if synthesised < required * 0.5 else "warning",
                    message=(
                        f"analytic sections carry {synthesised} words for {corpus_size} "
                        f"included studies; the floor is about {required}"
                    ),
                    remedy=(
                        "report what each study contributed: characteristics, method, "
                        "reported performance and limitations; aggregate counts alone "
                        "do not account for the corpus"
                    ),
                )
            )
    return Dimension(
        name="depth",
        score=_clamp(ratio),
        weight=DEFAULT_WEIGHTS["depth"],
        measurements=measurements,
        findings=tuple(findings),
    )
