from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .contracts import research_partner_output_skeletons


@dataclass(frozen=True)
class EvidenceContext:
    limitations: tuple[str, ...] = ()
    bottlenecks: tuple[str, ...] = ()
    metrics_summary: tuple[str, ...] = ()
    sources: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class IdeaContext:
    title: str
    description: str
    evidence_basis: tuple[str, ...] = ()
    evidence_context: EvidenceContext = EvidenceContext()


def _normalize_lines(values: tuple[str, ...]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


def _problem_statement(
    description: str,
    *,
    limitations: list[str],
    bottlenecks: list[str],
    metrics_summary: list[str],
) -> str:
    segments: list[str] = []
    cleaned = description.strip()
    if cleaned:
        segments.append(cleaned)
    if limitations:
        segments.append(f"Known limitation: {limitations[0]}")
    if bottlenecks:
        segments.append(f"Known bottleneck: {bottlenecks[0]}")
    if metrics_summary:
        segments.append(f"Existing metric signals: {metrics_summary[0]}")
    if segments:
        return " ".join(segments)
    return "The proposal still frames its problem too coarsely; add concrete task context and constraints."


def _novelty_claim(title: str, evidence_basis: list[str]) -> str:
    if evidence_basis:
        return f"Integrate the current evidence signals around \"{title}\" into a testable, structured research hypothesis tied to follow-up ablations."
    return f"State a research hypothesis for \"{title}\" that still needs evidence support, and scaffold an iterable proposal first."


def _claim_graph(title: str, evidence_basis: list[str]) -> dict[str, Any]:
    evidence_refs = [f"evidence:{idx}" for idx, _ in enumerate(evidence_basis, start=1)]
    return {
        "nodes": [
            {
                "id": "problem",
                "label": "Problem Framing",
                "type": "problem",
                "summary": "Pin down the key bottleneck of current methods and the failure modes on the target task.",
                "evidence_refs": evidence_refs,
            },
            {
                "id": "method_hypothesis",
                "label": title,
                "type": "method",
                "summary": "Form a core method hypothesis that critique can refine across rounds.",
                "evidence_refs": evidence_refs,
            },
            {
                "id": "expected_result",
                "label": "Expected Result",
                "type": "expected_result",
                "summary": "Use ablations and metrics to verify the method actually addresses the target problem.",
                "evidence_refs": evidence_refs,
            },
        ],
        "edges": [
            {"source": "problem", "target": "method_hypothesis", "relation": "motivates"},
            {"source": "method_hypothesis", "target": "expected_result", "relation": "validated_by"},
        ],
    }


def _experiment_blueprint(title: str, evidence_basis: list[str]) -> dict[str, Any]:
    evidence_note = "Validate the hypothesis against existing literature first." if evidence_basis else "Direct evidence is missing; add literature or experimental support."
    return {
        "title": title,
        "objective": "Test the core hypothesis and confirm that the key change really improves performance.",
        "tracks": [
            {
                "id": "core-hypothesis",
                "question": f"Does the core method hypothesis behind {title} produce a measurable improvement on the target problem?",
                "success_criteria": [
                    "The primary metric improves consistently over a strong baseline",
                    evidence_note,
                ],
            },
            {
                "id": "ablation-plan",
                "question": "Can ablations explain the gain from each key module or design choice?",
                "success_criteria": [
                    "Include at least one removal or replacement ablation of the main module",
                    "Record the performance change and its likely cause",
                ],
            },
        ],
        "evidence_basis": evidence_basis,
    }


def run_idea_pipeline(context: IdeaContext) -> dict[str, Any]:
    evidence_basis = _normalize_lines(context.evidence_basis)
    limitations = _normalize_lines(context.evidence_context.limitations)
    bottlenecks = _normalize_lines(context.evidence_context.bottlenecks)
    metrics_summary = _normalize_lines(context.evidence_context.metrics_summary)
    sources = [dict(source) for source in context.evidence_context.sources]
    skeletons = research_partner_output_skeletons()
    idea_brief = {
        **deepcopy(skeletons["idea_brief"]),
        "title": context.title.strip() or "Untitled Proposal",
        "problem": _problem_statement(
            context.description,
            limitations=limitations,
            bottlenecks=bottlenecks,
            metrics_summary=metrics_summary,
        ),
        "novelty_claim": _novelty_claim(context.title.strip() or "Untitled Proposal", evidence_basis),
        "evidence_basis": evidence_basis,
    }
    pipeline_notes = [
        f"evidence_count={len(evidence_basis)}",
        f"limitations={len(limitations)}",
        f"bottlenecks={len(bottlenecks)}",
        f"metrics={len(metrics_summary)}",
        f"sources={len(sources)}",
        "assembled deterministic idea package",
    ]
    if not context.description.strip():
        pipeline_notes.append("description_gap_detected")

    return {
        "idea_brief": idea_brief,
        "claim_graph": _claim_graph(idea_brief["title"], evidence_basis),
        "experiment_blueprint": _experiment_blueprint(idea_brief["title"], evidence_basis),
        "pipeline_notes": pipeline_notes,
        "revision_history": [],
        "evidence_context": {
            "limitations": limitations,
            "bottlenecks": bottlenecks,
            "metrics_summary": metrics_summary,
            "sources": sources,
        },
    }


def revise_idea_package(
    idea_package: Mapping[str, Any],
    critique_report: Mapping[str, Any],
    round_index: int,
) -> dict[str, Any]:
    revised_package = deepcopy(dict(idea_package))
    revised_idea_brief = deepcopy(dict(revised_package["idea_brief"]))
    revised_blueprint = deepcopy(dict(revised_package["experiment_blueprint"]))
    revised_notes = list(revised_package.get("pipeline_notes", []))
    revised_history = list(revised_package.get("revision_history", []))

    revised_idea_brief["novelty_claim"] = (
        revised_idea_brief["novelty_claim"].rstrip(".")
        + f"; claim boundaries tightened after critique round {round_index}."
    )

    tracks = list(revised_blueprint.get("tracks", []))
    track_ids = {track.get("id") for track in tracks}
    if "evidence-gap-review" not in track_ids:
        tracks.append(
            {
                "id": "evidence-gap-review",
                "question": "Does the current evidence gap undermine the credibility of the conclusions?",
                "success_criteria": [
                    "List the literature or experiments still required",
                    "Avoid overclaiming while evidence is thin",
                ],
            }
        )
    revised_blueprint["tracks"] = tracks

    revised_notes.append(f"round_{round_index}_revision_applied")
    revised_history.append(
        {
            "round": round_index,
            "summary": critique_report.get("summary", ""),
            "risks": list(critique_report.get("risks", [])),
        }
    )

    return {
        **revised_package,
        "idea_brief": revised_idea_brief,
        "experiment_blueprint": revised_blueprint,
        "pipeline_notes": revised_notes,
        "revision_history": revised_history,
    }
