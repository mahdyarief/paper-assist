"""Deterministic manuscript quality scoring.

Reviewers reject manuscripts for a small set of recurring, measurable reasons:
the abstract does not state results, the method section does not describe the
search or sampling, no limitations are discussed, claims are not traceable, and
the reference list is thinner than the evidence corpus. This module converts
those reasons into dimensions computed directly from the LaTeX source, the
claim ledger and the corpus binding.

Scoring is intentionally conservative: each dimension returns a value in
``[0, 1]`` with the raw measurements that produced it, so a reader can contest
the weighting rather than the facts. Nothing here calls a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .anti_ai_style import detect_formulaic_phrases, is_uniform_rhythm, sentence_length_cv
from .claim_ledger import ClaimLedger
from .corpus_binder import CorpusBinding
from .provenance_audit import DEFAULT_MIN_ANCHORED
from .reporting_checks import (
    LOCATOR_NOT_FOUND,
    DeclarationCheck,
    FlowCheck,
    ReferenceAudit,
    resolve_paper_type,
)

QUALITY_SCHEMA = "paperassist.manuscript-quality/v1"
GRADE_SCHEMA = "paperassist.quality-grade/v1"

# Weights sum to 1.0. Provenance and evidence carry the largest share because
# they are the dimensions a reviewer cannot verify without the underlying data.
# Declarations and references are what an editor checks before sending a paper
# to review (ICMJE/COPE disclosure, publisher declarations, reference quality).
DEFAULT_WEIGHTS: dict[str, float] = {
    "structure": 0.07,
    "abstract": 0.09,
    "depth": 0.08,
    "citations": 0.09,
    "provenance": 0.18,
    "evidence": 0.13,
    "method_rigour": 0.12,
    "limitations": 0.05,
    "declarations": 0.04,
    "references": 0.04,
    "prose_style": 0.03,
    "tables_figures": 0.03,
    "readability": 0.03,
    "formulaic_prose": 0.02,
}

# Analytic prose a review needs per included study before it can report what
# each one contributed. Twenty five words is roughly two substantive sentences:
# enough for a design, a method and a reported result, which is the minimum a
# synthesis entry carries. Used only when the corpus size is known.
_STUDY_WORDS = 25

GRADE_BANDS: tuple[tuple[str, float], ...] = (
    ("A", 0.85),
    ("B", 0.72),
    ("C", 0.58),
    ("D", 0.40),
    ("E", 0.0),
)

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "abstrak"),
    "introduction": ("introduction", "pendahuluan"),
    "related": ("related work", "literature", "tinjauan", "state of the art"),
    "method": (
        "method",
        "metode",
        "materials and methods",
        "methodology",
        "experimental setup",
        "experimental design",
        "experiment setup",
        "research design",
        "desain penelitian",
        "rancangan penelitian",
    ),
    "results": ("result", "hasil", "findings", "temuan"),
    "discussion": ("discussion", "pembahasan", "diskusi"),
    "conclusion": ("conclusion", "kesimpulan", "closing"),
    "limitations": ("limitation", "keterbatasan", "threats to validity"),
    "background": ("background", "latar belakang"),
}

_SECTION_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]*)\}"
)
_ABSTRACT_RE = re.compile(
    r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL | re.IGNORECASE
)
# A tabular is the body of a table float, not a float of its own. Counting it
# alongside ``table`` would double every table in the manuscript and then
# report a caption shortage that does not exist.
_TABLE_RE = re.compile(r"\\begin\{(table\*?|longtable)\}", re.IGNORECASE)
_FIGURE_RE = re.compile(r"\\begin\{figure\*?\}", re.IGNORECASE)
_CAPTION_RE = re.compile(r"\\caption\s*\{")
_LABEL_RE = re.compile(r"\\label\s*\{([^{}]*)\}")
_REF_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref)\s*\{([^{}]*)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_BIBLIOGRAPHY_RE = re.compile(
    r"\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}"
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
_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F0-9'’\-]+")
# House style rules apply to running prose only. A table cell that marks a
# missing value as ``---`` is not a dash in a sentence, and counting it as one
# would penalise every manuscript that uses the conventional placeholder.
_NON_PROSE_RE = re.compile(
    r"\\begin\{(?:tabular\*?|table\*?|longtable|verbatim|lstlisting|equation\*?|"
    r"align\*?|displaymath)\}.*?\\end\{(?:tabular\*?|table\*?|longtable|verbatim|"
    r"lstlisting|equation\*?|align\*?|displaymath)\}",
    re.DOTALL | re.IGNORECASE,
)
# House style forbids the em dash in running prose. A LaTeX em dash is ``---``
# or ``\textemdash{}``; the literal character is also caught.
_EM_DASH_RE = re.compile(r"(?<!-)---(?!-)|\\textemdash\b|\u2014")
_EN_DASH_RE = re.compile(r"(?<!-)--(?!-)|\u2013|\\textendash\b")
# An en dash between digits is a numeric range, which is allowed.
_NUMERIC_RANGE_RE = re.compile(r"(?<=\d)\s*(?:--|\\textendash\b|\u2013)\s*(?=\d)")
_REFERENCE_ITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^{}]*)\}")


class QualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    """A single actionable defect with a location and a remedy."""

    dimension: str
    severity: str
    message: str
    remedy: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "severity": self.severity,
            "message": self.message,
            "remedy": self.remedy,
            "line": self.line,
        }


@dataclass(frozen=True)
class Dimension:
    name: str
    score: float
    weight: float
    measurements: Mapping[str, Any] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "weight": self.weight,
            "measurements": dict(self.measurements),
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class QualityReport:
    dimensions: tuple[Dimension, ...] = ()
    paper_type: str = "review"
    score: float = 0.0
    grade: str = "E"
    recommendation: str = "reject"
    worst_dimensions: tuple[str, ...] = ()
    digest: str = ""
    source_sha256: str = ""

    def dimension(self, name: str) -> Dimension | None:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        return None

    def findings(self, *, min_severity: str = "info") -> tuple[Finding, ...]:
        order = {"info": 0, "warning": 1, "critical": 2}
        floor = order.get(min_severity, 0)
        selected = [
            finding
            for dimension in self.dimensions
            for finding in dimension.findings
            if order.get(finding.severity, 0) >= floor
        ]
        return tuple(
            sorted(
                selected,
                key=lambda f: (-order.get(f.severity, 0), f.dimension, f.line or 0),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUALITY_SCHEMA,
            "grade_schema": GRADE_SCHEMA,
            "digest": self.digest,
            "source_sha256": self.source_sha256,
            "paper_type": self.paper_type,
            "score": round(self.score, 4),
            "grade": self.grade,
            "recommendation": self.recommendation,
            "worst_dimensions": list(self.worst_dimensions),
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _strip_latex(text: str) -> str:
    text = re.sub(r"(?<!\\)%.*$", " ", text, flags=re.M)
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}$&_^~]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _section_kinds(title: str) -> tuple[str, ...]:
    """Every kind a heading names.

    A combined heading is common: "Hasil dan Pembahasan" is the standard
    Indonesian journal section and "Results and Discussion" its English twin.
    Returning only the first match would report a discussion as missing from
    every such paper.
    """

    lowered = title.lower()
    return tuple(
        candidate
        for candidate, aliases in _SECTION_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    )


def _section_kind(title: str) -> str | None:
    kinds = _section_kinds(title)
    return kinds[0] if kinds else None


def _heading_body(text: str, kind: str) -> str:
    """Body under any heading level that names ``kind``, up to the next heading.

    Used where a subsection is a legitimate home, such as a Limitations
    subsection inside the Discussion.
    """

    headings = list(_SECTION_RE.finditer(text))
    parts: list[str] = []
    for index, match in enumerate(headings):
        if kind not in _section_kinds(match.group(2).strip()):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        parts.append(text[match.end():end])
    return _without_floats("\n".join(parts))


def _section_bodies(text: str) -> dict[str, str]:
    """Map a section kind to its body text, concatenating duplicates.

    A subsection belongs to the section it sits in. Ending a section's body at
    the next heading would drop every paragraph written under a subsection,
    so analysis would count for nothing precisely where it is most detailed.
    Only a heading that opens a different recognised kind ends the current body.

    A table float is not running prose. A catalogue of studies sits inside
    whatever section precedes it, and counting its rows as analysis would let a
    reference list inflate the depth score of a review that argues nothing. The
    same applies to an appendix, which is not one of the paper's argument
    sections even when its title contains a recognised word.
    """

    entries = list(_SECTION_RE.finditer(text))
    bodies: dict[str, list[str]] = {}
    current: tuple[str, ...] = ()
    start = 0

    def close(end: int) -> None:
        for kind in current:
            bodies.setdefault(kind, []).append(text[start:end])

    for match in entries:
        # A subsection heading never closes the section around it, even when its
        # title happens to contain a word such as "limitations": that paragraph
        # still argues the discussion it sits in.
        if match.group(1).lower() in ("subsection", "subsubsection"):
            continue
        kinds = _section_kinds(match.group(2).strip())
        # An unrecognised top-level heading opens a new part of the document,
        # so it closes the section before it. Otherwise an appendix would be
        # counted as the conclusion's own prose.
        close(match.start())
        current = kinds
        start = match.end()
    close(len(text))
    return {
        kind: _without_floats("\n".join(parts)) for kind, parts in bodies.items()
    }


def _without_floats(text: str) -> str:
    """Remove table and figure environments, keeping paragraph text.

    The body of a section is what its author argues. Tabular rows and figure
    captions are evidence placed inside it, and counting their cells as prose
    would reward a paper for the size of its appendix rather than its analysis.
    """

    return re.sub(
        r"\\begin\{(table\*?|longtable|figure\*?|tabular\*?)\}.*?"
        r"\\end\{\1\}",
        " ",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )


def _grade(score: float) -> tuple[str, str]:
    grade = "E"
    for label, threshold in GRADE_BANDS:
        if score >= threshold:
            grade = label
            break
    if score >= GRADE_BANDS[0][1]:
        recommendation = "accept"
    elif score >= GRADE_BANDS[1][1]:
        recommendation = "minor revision"
    elif score >= GRADE_BANDS[2][1]:
        recommendation = "major revision"
    else:
        recommendation = "reject"
    return grade, recommendation


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


def _dimension_citations(
    ledger: ClaimLedger,
    binding: CorpusBinding | None,
    *,
    reference_keys: Sequence[str],
) -> Dimension:
    findings: list[Finding] = []
    cited: list[str] = []
    for claim in ledger.claims:
        for key in claim.citation_keys:
            if key not in cited:
                cited.append(key)
    known = set(reference_keys)
    unresolved = [key for key in cited if known and key not in known]
    for key in unresolved[:10]:
        findings.append(
            Finding(
                dimension="citations",
                severity="critical",
                message=f"citation key not in reference list: {key}",
                remedy="add the entry to the bibliography or remove the citation",
            )
        )
    evidence_claims = [c for c in ledger.claims if c.channel == "evidence"]
    # A derived claim is arithmetic over ingested data records, so it is already
    # traceable without a citation. Requiring one for it conflates "no source"
    # with "source is the dataset" and penalises synthesis-heavy reviews, whose
    # result sentences are mostly aggregates. Only attributed and grounded
    # claims assert something external and therefore demand a bibliography key.
    citable_claims = [c for c in evidence_claims if c.status != "derived"]
    cited_claims = sum(1 for claim in citable_claims if claim.citation_keys)
    cited_share = cited_claims / len(citable_claims) if citable_claims else 1.0
    reference_count = len(reference_keys) or len(cited)
    corpus_size = len(binding.records) if binding else 0
    coverage = binding.coverage()["bibliography_coverage"] if binding and corpus_size else 0.0
    if corpus_size and coverage < 0.25:
        findings.append(
            Finding(
                dimension="citations",
                severity="critical",
                message=(
                    f"only {coverage:.1%} of {corpus_size} extracted records have a "
                    "bibliography entry"
                ),
                remedy=(
                    "generate bibliography entries for the full evidence corpus; a "
                    "review citing a small fraction of its records is not auditable"
                ),
            )
        )
    if corpus_size:
        score = (
            0.35 * cited_share
            + 0.25 * min(1.0, reference_count / 40)
            + 0.40 * min(1.0, coverage / 0.8)
        )
    else:
        score = 0.5 * cited_share + 0.5 * min(1.0, reference_count / 40)
    if unresolved:
        score *= 0.8
    return Dimension(
        name="citations",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["citations"],
        measurements={
            "cited_keys": len(set(cited)),
            "reference_entries": reference_count,
            # Derived claims are excluded from both sides, as in the score.
            "citable_claims_with_citation": f"{cited_claims}/{len(citable_claims)}",
            "corpus_records": corpus_size,
            "corpus_coverage": round(coverage, 4),
            "unresolved_keys": unresolved,
        },
        findings=tuple(findings),
    )


def _dimension_provenance(
    ledger: ClaimLedger,
    *,
    min_anchored: float,
    locator_checks: Mapping[str, str] | None = None,
) -> Dimension:
    summary = ledger.summary()
    evidence = summary["evidence_channel"]
    anchored = summary["grounded"] + summary["attributed"] + summary["derived"]
    findings: list[Finding] = []
    # A locator whose quote does not occur in the cited work's own text anchors
    # nothing: it reads as provenance while pointing at words that are not there.
    failed_keys = {
        key for key, status in (locator_checks or {}).items() if status == LOCATOR_NOT_FOUND
    }
    contradicted = [
        claim
        for claim in ledger.claims
        if claim.status == "grounded"
        and claim.locator_keys
        and all(key in failed_keys for key in claim.locator_keys)
    ]
    if contradicted:
        anchored -= len(contradicted)
        findings.append(
            Finding(
                dimension="provenance",
                severity="critical",
                message=(
                    f"{len(contradicted)} grounded sentence(s) cite a locator quote that "
                    "does not occur in the bound full text: "
                    + ", ".join(sorted(failed_keys)[:5])
                ),
                remedy="copy the quote verbatim from the source, or fix the locator key",
                line=contradicted[0].line_start,
            )
        )
    ratio = anchored / evidence if evidence else 1.0
    unsupported = summary["unsupported"]
    if unsupported:
        findings.append(
            Finding(
                dimension="provenance",
                severity="critical",
                message=(
                    f"{unsupported} quantitative assertion(s) have no locator, "
                    "citation or data record"
                ),
                remedy="anchor each number to a locator, a citation or an ingested data record",
            )
        )
    if evidence and ratio < min_anchored:
        findings.append(
            Finding(
                dimension="provenance",
                severity="critical",
                message=(
                    f"anchored evidence ratio {ratio:.1%} is below the "
                    f"{min_anchored:.0%} floor"
                ),
                remedy=(
                    'add `% @locator{key: page=.., quote=".."}` annotations with '
                    "verbatim excerpts"
                ),
            )
        )
    if evidence and summary["grounded"] == 0:
        findings.append(
            Finding(
                dimension="provenance",
                severity="warning",
                message="no sentence is grounded in a verbatim source excerpt",
                remedy=(
                    "extract excerpts for the cited works and annotate the sentence "
                    "that uses each"
                ),
            )
        )
    score = ratio
    if unsupported:
        score *= 1 - min(0.5, unsupported / max(1, len(ledger.claims)) * 2)
    return Dimension(
        name="provenance",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["provenance"],
        measurements={
            "evidence_claims": evidence,
            "anchored": anchored,
            "grounded": summary["grounded"],
            "attributed": summary["attributed"],
            "derived": summary["derived"],
            "unsupported": unsupported,
            "anchored_ratio": round(ratio, 4),
            "ledger_anchored_ratio": summary["anchored_ratio"],
            "locator_quotes": dict(locator_checks) if locator_checks else None,
            "locator_quotes_not_found": sorted(failed_keys),
        },
        findings=tuple(findings),
    )


def _dimension_evidence(
    ledger: ClaimLedger, binding: CorpusBinding | None
) -> Dimension:
    summary = ledger.summary()
    findings: list[Finding] = []
    total = len(ledger.claims)
    evidence_share = summary["evidence_channel"] / total if total else 0.0
    if total and evidence_share < 0.3:
        findings.append(
            Finding(
                dimension="evidence",
                severity="critical",
                message=(
                    f"only {evidence_share:.1%} of sentences make a verifiable assertion"
                ),
                remedy=(
                    "replace procedural narration with sourced findings; a review "
                    "must report evidence, not process"
                ),
            )
        )
    corpus_size = len(binding.records) if binding else 0
    coverage = binding.coverage() if binding and corpus_size else None
    if coverage and coverage["text_coverage"] < 0.5:
        findings.append(
            Finding(
                dimension="evidence",
                severity="warning",
                message=(
                    f"only {coverage['text_coverage']:.1%} of records have a local "
                    "full text"
                ),
                remedy=(
                    "bind extraction records to the full-text corpus so quotes can "
                    "be verified"
                ),
            )
        )
    score = 0.6 * min(1.0, evidence_share / 0.6)
    if coverage:
        score += 0.4 * min(1.0, coverage["text_coverage"] / 0.9)
    else:
        score += 0.4 * min(
            1.0, summary["derived"] / max(1, summary["evidence_channel"]) / 0.3
        )
    if summary["unsupported"]:
        score *= 0.85
    return Dimension(
        name="evidence",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["evidence"],
        measurements={
            "claims": total,
            "evidence_share": round(evidence_share, 4),
            "derived": summary["derived"],
            "corpus_records": corpus_size,
            "corpus_text_coverage": (
                coverage["text_coverage"] if coverage else None
            ),
        },
        findings=tuple(findings),
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


def _dimension_formulaic_prose(text: str) -> Dimension:
    prose = _NON_PROSE_RE.sub(lambda m: " " * len(m.group(0)), text)
    prose = _ABSTRACT_RE.sub(lambda m: m.group(1), prose)
    prose = _SECTION_RE.sub(lambda m: " " * len(m.group(0)), prose)
    prose = _strip_latex(prose)

    hits = detect_formulaic_phrases(prose)
    rhythm_cv = sentence_length_cv(prose)
    uniform = is_uniform_rhythm(prose)
    findings: list[Finding] = []

    if hits:
        examples = ", ".join(f'“{hit.phrase}”' for hit in hits[:3])
        findings.append(
            Finding(
                dimension="formulaic_prose",
                severity="warning" if len(hits) < 4 else "critical",
                message=(
                    f"{len(hits)} formulaic phrase(s) for editorial review: {examples}"
                ),
                remedy=(
                    "replace only phrases that add no paper-specific meaning; "
                    "retain standard technical terminology"
                ),
            )
        )
    if uniform:
        findings.append(
            Finding(
                dimension="formulaic_prose",
                severity="info",
                message=(
                    "sentence lengths are unusually uniform "
                    f"(coefficient of variation {rhythm_cv:.2f})"
                ),
                remedy=(
                    "review sentence rhythm where it improves readability; "
                    "do not vary sentence length mechanically"
                ),
            )
        )

    score = _clamp(1.0 - min(0.6, len(hits) * 0.12) - (0.08 if uniform else 0.0))
    return Dimension(
        name="formulaic_prose",
        score=score,
        weight=DEFAULT_WEIGHTS["formulaic_prose"],
        measurements={
            "formulaic_phrase_count": len(hits),
            "formulaic_phrases": [hit.to_dict() for hit in hits],
            "sentence_length_cv": round(rhythm_cv, 4),
            "uniform_sentence_rhythm": uniform,
            "is_authorship_detector": False,
        },
        findings=tuple(findings),
    )


def _dimension_tables_figures(text: str, *, asset_root: str | None = None) -> Dimension:
    findings: list[Finding] = []
    tables = len(_TABLE_RE.findall(text))
    figures = len(_FIGURE_RE.findall(text))
    captions = len(_CAPTION_RE.findall(text))
    labels = set(_LABEL_RE.findall(text))
    refs = {
        part.strip()
        for group in _REF_RE.findall(text)
        for part in group.split(",")
        if part.strip()
    }
    floats = tables + figures
    # A label nothing references is a defect whether or not other refs exist.
    unreferenced = sorted(labels - refs)
    for label in unreferenced[:8]:
        findings.append(
            Finding(
                dimension="tables_figures",
                severity="warning",
                message=f"label '{label}' is never referenced in the text",
                remedy="reference every table and figure with \\ref{} where it is discussed",
            )
        )
    if floats and captions < floats:
        findings.append(
            Finding(
                dimension="tables_figures",
                severity="warning",
                message=f"{floats} float(s) but only {captions} caption(s)",
                remedy="give every table and figure a self-contained caption",
            )
        )
    graphics = _GRAPHICS_RE.findall(text)
    missing = 0
    for path in graphics:
        candidates = (path, path + ".pdf", path + ".png", path + ".jpg")
        if not any(_exists(candidate, asset_root) for candidate in candidates):
            missing += 1
    if missing:
        findings.append(
            Finding(
                dimension="tables_figures",
                severity="warning",
                message=(
                    f"{missing} referenced graphic(s) not found relative to "
                    + ("the manuscript folder" if asset_root else "the working directory")
                ),
                remedy="confirm figure files ship with the submission",
            )
        )
    score = 0.0
    if floats:
        score = 0.5 + 0.5 * min(1.0, captions / floats)
        if refs:
            score *= 0.7 + 0.3 * (1 - len(unreferenced) / max(1, len(labels)))
    elif labels:
        score = 0.35
    return Dimension(
        name="tables_figures",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["tables_figures"],
        measurements={
            "tables": tables,
            "figures": figures,
            "captions": captions,
            "labels": len(labels),
            "referenced_labels": len(refs & labels),
        },
        findings=tuple(findings),
    )


def _exists(path: str, asset_root: str | None = None) -> bool:
    """Whether a graphic exists, resolved like LaTeX: relative to the manuscript."""

    from pathlib import Path

    try:
        candidate = Path(path)
        if asset_root and not candidate.is_absolute():
            candidate = Path(asset_root) / candidate
        return candidate.exists()
    except (OSError, ValueError):
        return False


def _dimension_prose_style(text: str, *, allow_em_dash: bool = False) -> Dimension:
    """Enforce house prose style: no em dash, en dash only inside numeric ranges."""

    prose = _NON_PROSE_RE.sub(lambda m: " " * len(m.group(0)), text)
    prose = _ABSTRACT_RE.sub(lambda m: m.group(1), prose)
    prose = _SECTION_RE.sub(lambda m: " " * len(m.group(0)), prose)
    prose = _strip_latex(prose)

    findings: list[Finding] = []
    em_dashes = len(_EM_DASH_RE.findall(prose))
    ranges = len(_NUMERIC_RANGE_RE.findall(prose))
    en_dashes = max(0, len(_EN_DASH_RE.findall(prose)) - ranges)

    score = 1.0
    if em_dashes and not allow_em_dash:
        score -= min(0.8, em_dashes * 0.08)
        findings.append(
            Finding(
                dimension="prose_style",
                severity="warning" if em_dashes < 10 else "critical",
                message=f"{em_dashes} em dash(es) in running prose",
                remedy=(
                    "replace each em dash with a comma, a colon, or a full stop; "
                    "house style forbids the em dash"
                ),
            )
        )
    if en_dashes:
        score -= min(0.3, en_dashes * 0.04)
        findings.append(
            Finding(
                dimension="prose_style",
                severity="info",
                message=f"{en_dashes} en dash(es) outside a numeric range",
                remedy="use a hyphen for compounds and keep en dashes for ranges only",
            )
        )
    return Dimension(
        name="prose_style",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["prose_style"],
        measurements={
            "em_dashes": em_dashes,
            "en_dashes_outside_ranges": en_dashes,
            "numeric_ranges": ranges,
            "em_dash_allowed": allow_em_dash,
            "prose_words": _count_words(prose),
        },
        findings=tuple(findings),
    )


def _dimension_readability(text: str) -> Dimension:
    sentences = [
        _count_words(s)
        for s in re.split(r"(?<=[.!?])\s+", _strip_latex(text))
        if _count_words(s) > 0
    ]
    findings: list[Finding] = []
    if not sentences:
        return Dimension(
            name="readability",
            score=0.0,
            weight=DEFAULT_WEIGHTS["readability"],
            measurements={"sentences": 0},
        )
    average = sum(sentences) / len(sentences)
    long_ratio = sum(1 for count in sentences if count > 45) / len(sentences)
    score = 1.0
    if average > 32:
        score -= min(0.35, (average - 32) / 60)
        findings.append(
            Finding(
                dimension="readability",
                severity="warning",
                message=f"average sentence length is {average:.1f} words",
                remedy="split sentences above 40 words; one claim per sentence",
            )
        )
    if long_ratio > 0.12:
        score -= min(0.25, long_ratio)
        findings.append(
            Finding(
                dimension="readability",
                severity="info",
                message=f"{long_ratio:.0%} of sentences exceed 45 words",
                remedy="break the longest sentences into claim plus support",
            )
        )
    return Dimension(
        name="readability",
        score=_clamp(score),
        weight=DEFAULT_WEIGHTS["readability"],
        measurements={
            "sentences": len(sentences),
            "average_words": round(average, 2),
            "long_sentence_ratio": round(long_ratio, 4),
        },
        findings=tuple(findings),
    )


def _reference_keys(
    text: str,
    bibliography_entries: Sequence[str],
    bibliography_text: str | None,
) -> list[str]:
    keys: list[str] = list(bibliography_entries)
    if bibliography_text:
        for match in _REFERENCE_ITEM_RE.finditer(bibliography_text):
            key = match.group(1).strip()
            if key and key not in keys:
                keys.append(key)
    if not keys:
        for match in _REFERENCE_ITEM_RE.finditer(text):
            key = match.group(1).strip()
            if key not in keys:
                keys.append(key)
    return keys


def score_manuscript(
    text: str,
    *,
    ledger: ClaimLedger | None = None,
    binding: CorpusBinding | None = None,
    bibliography_entries: Sequence[str] = (),
    bibliography_text: str | None = None,
    depth_target: int = 500,
    min_anchored: float = DEFAULT_MIN_ANCHORED,
    allow_em_dash: bool = False,
    weights: Mapping[str, float] | None = None,
    corpus_size: int | None = None,
    paper_type: str | None = "auto",
    prisma_flow: FlowCheck | None = None,
    declarations: DeclarationCheck | None = None,
    reference_audit: ReferenceAudit | None = None,
    locator_checks: Mapping[str, str] | None = None,
    asset_root: str | None = None,
) -> QualityReport:
    """Score a manuscript across fourteen deterministic dimensions.

    ``paper_type`` selects the reporting standard: ``review`` (PRISMA 2020 /
    PRISMA-S signals and flow arithmetic) or ``empirical`` (design, data,
    analysis, statistics); ``auto`` decides from the corpus and the text.
    ``declarations``, ``reference_audit``, ``prisma_flow`` and
    ``locator_checks`` come from :mod:`paperassist.reporting_checks`; when a
    caller omits them, declarations are detected from the text and the other
    checks are reported as not measured.

    ``corpus_size`` is how many studies the manuscript had to synthesise. A
    binding supplies it when one exists; a caller holding extraction records
    without bound full texts passes it directly, because a review's reporting
    floor follows the corpus it claims, not the files it happens to have.
    """

    if not isinstance(text, str) or not text.strip():
        raise QualityError("manuscript text is empty")
    if depth_target <= 0:
        raise QualityError("depth_target must be positive")
    if not 0 < min_anchored <= 1:
        raise QualityError("min_anchored must be in (0, 1]")

    active_weights = dict(DEFAULT_WEIGHTS)
    if weights:
        unknown = set(weights) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise QualityError(f"unknown quality dimensions: {sorted(unknown)}")
        active_weights.update({key: float(value) for key, value in weights.items()})
    total_weight = sum(active_weights.values())
    if total_weight <= 0:
        raise QualityError("weights must sum to a positive value")

    reference_keys = _reference_keys(text, bibliography_entries, bibliography_text)

    if ledger is None:
        from .claim_ledger import build_ledger

        ledger = build_ledger(text)

    if corpus_size is None:
        corpus_size = len(binding.records) if binding else 0
    if corpus_size < 0:
        raise QualityError("corpus_size must not be negative")
    try:
        resolved_type = resolve_paper_type(paper_type, text, study_count=corpus_size)
    except ValueError as exc:
        raise QualityError(str(exc)) from exc
    if declarations is None:
        from .reporting_checks import check_declarations

        declarations = check_declarations(text, paper_type=resolved_type)
    if reference_audit is None and bibliography_text:
        from .corpus_binder import parse_bib_entries
        from .reporting_checks import audit_references, cited_keys

        cited = cited_keys(text)
        reference_audit = audit_references(parse_bib_entries(bibliography_text), cited_keys=cited)

    dimensions = (
        _dimension_structure(text, depth_target=depth_target),
        _dimension_abstract(text),
        _dimension_depth(
            text, depth_target=depth_target, corpus_size=corpus_size
        ),
        _dimension_citations(ledger, binding, reference_keys=reference_keys),
        _dimension_provenance(
            ledger, min_anchored=min_anchored, locator_checks=locator_checks
        ),
        _dimension_evidence(ledger, binding),
        _dimension_method(text, paper_type=resolved_type, flow=prisma_flow),
        _dimension_limitations(text),
        _dimension_declarations(declarations),
        _dimension_references(reference_audit),
        _dimension_prose_style(text, allow_em_dash=allow_em_dash),
        _dimension_tables_figures(text, asset_root=asset_root),
        _dimension_readability(text),
        _dimension_formulaic_prose(text),
    )

    weighted = sum(
        dimension.score * active_weights[dimension.name] for dimension in dimensions
    )
    score = weighted / total_weight
    grade, recommendation = _grade(score)
    worst = tuple(
        dimension.name
        for dimension in sorted(dimensions, key=lambda d: d.score)[:3]
        if dimension.score < 0.7
    )

    report = QualityReport(
        dimensions=dimensions,
        paper_type=resolved_type,
        score=score,
        grade=grade,
        recommendation=recommendation,
        worst_dimensions=worst,
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    digest = hashlib.sha256(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return QualityReport(
        dimensions=report.dimensions,
        paper_type=report.paper_type,
        score=report.score,
        grade=report.grade,
        recommendation=report.recommendation,
        worst_dimensions=report.worst_dimensions,
        digest=digest,
        source_sha256=report.source_sha256,
    )


def format_quality_report(report: QualityReport) -> str:
    lines = [
        "## Manuscript quality report",
        "",
        f"**Score:** {report.score:.3f}  |  **Grade:** {report.grade}  |  "
        f"**Recommendation:** {report.recommendation}  |  "
        f"**Paper type:** {report.paper_type}",
        "",
        "| Dimension | Score | Weight |",
        "|---|---|---|",
    ]
    for dimension in sorted(report.dimensions, key=lambda d: d.score):
        lines.append(
            f"| {dimension.name} | {dimension.score:.2f} | {dimension.weight:.2f} |"
        )
    critical = report.findings(min_severity="critical")
    warnings = report.findings(min_severity="warning")
    if critical:
        lines += ["", "### Blocking findings", ""]
        for finding in critical:
            location = f" (line {finding.line})" if finding.line else ""
            lines.append(
                f"- [{finding.dimension}] {finding.message}{location} — {finding.remedy}"
            )
    remaining = [finding for finding in warnings if finding not in critical]
    if remaining:
        lines += ["", "### Warnings", ""]
        for finding in remaining[:15]:
            lines.append(
                f"- [{finding.dimension}] {finding.message} — {finding.remedy}"
            )
        if len(remaining) > 15:
            lines.append(f"- and {len(remaining) - 15} more")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_WEIGHTS",
    "Dimension",
    "Finding",
    "GRADE_BANDS",
    "GRADE_SCHEMA",
    "QUALITY_SCHEMA",
    "QualityError",
    "QualityReport",
    "format_quality_report",
    "score_manuscript",
]
