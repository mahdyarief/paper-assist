"""Method rigour and limitations, per paper type (PRISMA review or empirical study)."""

from __future__ import annotations

import re
from typing import Any

from ..reporting_checks import (
    FlowCheck,
)
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

# Indonesian meN-/peN- prefixes mutate a root's initial consonant: saring ->
# penyaringan, seleksi -> penyeleksian, telusur -> penelusuran. Matching the bare
# root therefore misses the forms academic prose actually uses. The \b-anchored
# English alternatives stay word-initial so "research" is not read as "search".
_REVIEW_METHOD_SIGNALS: tuple[tuple[str, str], ...] = (
    ("search strategy", r"\b(?:search|query|string)\w*|\b\w*(?:cari|telusur|nelusur)\w*"),
    ("database enumeration", r"\b\w*(?:scopus|pubmed|web of science|ieee|scholar|garuda|database|basis data|pangkalan data)\w*"),
    ("search dates", r"last searched|search(?:es)? (?:was|were )?(?:conducted|performed|run) (?:on|in|between)|search date|tanggal pencarian|dilakukan pada|hingga (?:\d|januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)|up to (?:\d|january|february|march|april|may|june|july|august|september|october|november|december)|as of"),
    ("inclusion criteria", r"\b\w*(?:inclusion|inklusi|eligib|kriteria)\w*"),
    ("exclusion criteria", r"\b\w*(?:exclusion|eksklusi)\w*"),
    ("screening process", r"\b\w*(?:screen|skrin|saring|yaring|seleksi|yeleksi|tapis)\w*"),
    ("independent reviewers", r"two (?:independent )?reviewers|independent(?:ly)?|dua (?:orang )?(?:reviewer|peninjau|penilai)|secara independen|kappa|inter-rater|antar-?penilai"),
    ("extraction procedure", r"\b\w*(?:extraction|ekstraksi|charting|penilaian)\w*"),
    ("risk-of-bias appraisal", r"risk of bias|risiko bias|\brob\s*-?2\b|robins|\bcasp\b|\bjbi\b|\bmmat\b|quadas|newcastle|amstar|critical appraisal|quality (?:appraisal|assessment)|penilaian kualitas"),
    ("certainty of evidence", r"certainty of (?:the )?evidence|\bgrade\b (?:approach|framework|assessment)|cerqual|kepastian bukti|confidence in (?:the )?evidence"),
    ("synthesis method", r"\b\w*(?:synthesis|sintesis|meta-analy)\w*"),
)


_REVIEW_REPRO_SIGNALS: tuple[tuple[str, str], ...] = (
    ("data availability", r"data availability|ketersediaan data|dataset tersedia|extraction (?:form|data) (?:is|are) available"),
    ("protocol or registration", r"protocol|protokol|registr|\bosf\b|prospero"),
    ("full search strings", r"search strings?|query strings?|string pencarian|full search strateg|appendix|lampiran|supplementary"),
    ("prisma reporting", r"prisma"),
)


_EMPIRICAL_METHOD_SIGNALS: tuple[tuple[str, str], ...] = (
    ("research design", r"\b(?:design|desain|rancangan|approach|pendekatan)\w*"),
    ("data or participants", r"\b\w*(?:dataset|data set|sampel|sample|participant|partisipan|responden|respondent|subjek|subject|populasi|population|corpus|korpus)\w*"),
    ("procedure or instrument", r"\b\w*(?:procedure|prosedur|instrumen|instrument|kuesioner|questionnaire|setup|implementasi|implementation|pipeline)\w*"),
    ("variables or metrics", r"\b\w*(?:metric|metrik|variabel|variable|measure|ukuran|indikator|indicator|evaluat|evaluasi)\w*"),
    ("analysis method", r"\b\w*(?:analysis|analisis|statistic|statistik|regression|regresi|anova|t-test|uji)\w*"),
    ("baseline or comparison", r"\b\w*(?:baseline|pembanding|comparison|perbandingan|control group|kelompok kontrol|benchmark)\w*"),
    ("validation", r"\b\w*(?:validation|validasi|cross-validation|reliabilit|validity|validitas|held-out|test set|data uji)\w*"),
)


_EMPIRICAL_REPRO_SIGNALS: tuple[tuple[str, str], ...] = (
    ("data availability", r"data availability|ketersediaan data|data (?:are|is) available|dataset tersedia|publicly available"),
    ("code availability", r"code availability|source code|kode sumber|github\.com|gitlab\.com|zenodo|repositori"),
    ("parameter settings", r"hyperparameter|hiperparameter|random seed|\bseed\b|learning rate|parameter settings?|konfigurasi|configuration"),
    ("computing environment", r"\bgpu\b|\bcpu\b|hardware|perangkat keras|software version|versi|python \d|pytorch|tensorflow|\br \d|spss|stata"),
)


# Uncertainty and effect reporting in the results (APA/CONSORT-style practice).
_STATISTICS_SIGNALS: tuple[tuple[str, str], ...] = (
    ("uncertainty", r"confidence interval|interval kepercayaan|\bci\b|standard deviation|simpangan baku|standard error|\bstd\b|\bsd\b|\\pm|±"),
    ("significance or effect", r"p-?value|nilai p|\bp\s*[<=>]|effect size|ukuran efek|cohen|odds ratio|\bor\b\s*=|hazard ratio"),
    ("sample size", r"\bn\s*=\s*\d|sample size|ukuran sampel|jumlah sampel|\d+ (?:participants|responden|samples|sampel)"),
)


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
    text: str, *, paper_type: str = "review", flow: FlowCheck | None = None
) -> Dimension:
    bodies = _section_bodies(text)
    method = bodies.get("method", "")
    lowered = _strip_latex(method).lower()
    findings: list[Finding] = []
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
            measurements={"paper_type": paper_type, "signals": [], "repro": []},
            findings=tuple(findings),
        )
    if paper_type == "review":
        method_signals, repro_signals = _REVIEW_METHOD_SIGNALS, _REVIEW_REPRO_SIGNALS
    else:
        method_signals, repro_signals = _EMPIRICAL_METHOD_SIGNALS, _EMPIRICAL_REPRO_SIGNALS
    covered = [name for name, pattern in method_signals if re.search(pattern, lowered)]
    missing = [name for name, _ in method_signals if name not in covered]
    for name in missing:
        findings.append(
            Finding(
                dimension="method_rigour",
                severity="warning",
                message=f"method does not describe: {name}",
                remedy=f"add the {name} so the procedure is reproducible",
            )
        )
    whole = _strip_latex(text).lower()
    repro = [name for name, pattern in repro_signals if re.search(pattern, whole)]
    measurements: dict[str, Any] = {
        "paper_type": paper_type,
        "signals": covered,
        "missing": missing,
        "repro": repro,
    }
    if paper_type == "review":
        third, flow_notes = _flow_findings(flow)
        findings.extend(flow_notes)
        measurements["prisma_flow"] = flow.to_dict() if flow else None
    else:
        results = _strip_latex(bodies.get("results", "")).lower()
        stats = [name for name, pattern in _STATISTICS_SIGNALS if re.search(pattern, results)]
        measurements["statistics"] = stats
        if results and len(stats) < len(_STATISTICS_SIGNALS):
            absent = [name for name, _ in _STATISTICS_SIGNALS if name not in stats]
            findings.append(
                Finding(
                    dimension="method_rigour",
                    severity="warning",
                    message="results do not report: " + ", ".join(absent),
                    remedy=(
                        "report variability (SD/CI), effect size or test result, and "
                        "sample size beside each headline number"
                    ),
                )
            )
        third = len(stats) / len(_STATISTICS_SIGNALS) if results else 0.0
    score = (
        0.6 * (len(covered) / len(method_signals))
        + 0.2 * (len(repro) / len(repro_signals))
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
