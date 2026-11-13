from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .idea_pipeline import revise_idea_package
from .rubric_loader import RubricProfile, load_rubric_profile


@dataclass(frozen=True)
class CritiqueLoopConfig:
    rubric_profile: RubricProfile | None = None
    rubric_name: str = "default"
    review_mode: str = "deterministic"
    review_model: str = "gpt-5.4-xhigh"
    reviewer_count: int = 1


def _clamp_score(value: float) -> float:
    return max(0.0, min(round(value, 2), 1.0))


def _score_dimension(name: str, *, description_present: bool, evidence_count: int, track_count: int) -> float:
    if name == "novelty":
        return 0.85 if description_present else 0.35
    if name == "methodology":
        if track_count >= 2:
            return 0.8
        if track_count == 1:
            return 0.55
        return 0.3
    if name == "evidence_support":
        if evidence_count >= 3:
            return 0.9
        if evidence_count >= 1:
            return 0.55
        return 0.2
    if name == "clarity":
        return 0.75 if description_present else 0.4
    if name == "feasibility":
        return 0.7 if track_count >= 2 else 0.45
    return 0.5


def _build_round_report(
    idea_package: Mapping[str, Any],
    round_index: int,
    profile: RubricProfile,
) -> dict[str, Any]:
    idea_brief = idea_package["idea_brief"]
    evidence_basis = list(idea_brief.get("evidence_basis", []))
    evidence_count = len(evidence_basis)
    description = str(idea_brief.get("problem") or "").strip()
    blueprint = idea_package.get("experiment_blueprint", {})
    tracks = list(blueprint.get("tracks", []))
    description_present = bool(description)

    strengths = []
    risks = []
    open_questions = []
    dimension_scores: dict[str, float] = {}

    for dimension in profile.dimensions:
        dimension_scores[dimension.name] = _score_dimension(
            dimension.name,
            description_present=description_present,
            evidence_count=evidence_count,
            track_count=len(tracks),
        )

    score = sum(dimension_scores[item.name] * item.weight for item in profile.dimensions)
    score = _clamp_score(score)

    if description_present:
        strengths.append("The problem statement is explicit, so a reviewer can judge the task boundary.")
    else:
        risks.append("The problem statement is still too vague to judge whether the claim holds.")

    if evidence_count >= 3:
        strengths.append(f"{evidence_count} evidence items are available and can support the first proposal round.")
    elif evidence_count >= 1:
        strengths.append(f"{evidence_count} evidence items exist, but coverage still needs strengthening.")
        risks.append("Evidence volume is low, so support for the key claim remains thin.")
        open_questions.append("Is there high-quality prior work that directly supports the core hypothesis?")
    else:
        risks.append("No traceable evidence items exist yet, so the proposal lacks credibility.")
        open_questions.append("Which literature, experiments or prior knowledge are needed to support the core hypothesis?")

    if len(tracks) >= 2:
        strengths.append("The experiment blueprint covers hypothesis validation and an ablation plan.")
    else:
        risks.append("The experiment blueprint is too thin to validate the key design.")

    summary = (
        f"Critique round {round_index} complete: the proposal scores {score:.2f} overall "
        f"under rubric={profile.name}."
    )
    if not open_questions:
        open_questions.append("Should the next round switch to a stricter venue/rubric profile?")

    return {
        "round": round_index,
        "overall": score,
        "summary": summary,
        "strengths": strengths,
        "risks": risks,
        "open_questions": open_questions,
        "dimension_scores": dimension_scores,
        "review_mode": "fallback_deterministic",
    }


def _collect_blocking_issues(report: Mapping[str, Any], threshold: float) -> list[str]:
    issues: list[str] = []
    overall = float(report.get("overall", 0.0))
    if overall < threshold:
        issues.append(f"overall_below_threshold:{overall:.2f}<{threshold:.2f}")
    for risk in report.get("risks", []):
        text = str(risk).strip()
        if text:
            issues.append(text)
    return issues


def _recommendation_for_report(report: Mapping[str, Any], threshold: float) -> str:
    blocking_issues = _collect_blocking_issues(report, threshold)
    if blocking_issues:
        return "revise"
    return "go"


def _decision_from_report(report: Mapping[str, Any], threshold: float) -> str:
    recommendation = _recommendation_for_report(report, threshold)
    if recommendation == "go":
        return "approved"
    return "needs_revision"


def run_critique_loop(
    idea_package: Mapping[str, Any],
    config: CritiqueLoopConfig | None = None,
) -> dict[str, Any]:
    resolved_config = config or CritiqueLoopConfig()
    profile = resolved_config.rubric_profile or load_rubric_profile(resolved_config.rubric_name)
    working_package = deepcopy(dict(idea_package))
    rounds: list[dict[str, Any]] = []
    final_report: dict[str, Any] | None = None
    decision = "needs_revision"
    review_mode = "deterministic"
    committee_decision: dict[str, Any] = {
        "status": "not_requested",
        "decision": None,
        "review_mode": review_mode,
        "note": (
            "PaperAssist owns no model; committee review is a harness task pack "
            "(paperassist pack --kind review)."
        ),
    }

    for round_index in range(1, profile.max_rounds + 1):
        round_report = _build_round_report(working_package, round_index, profile)

        rounds.append(round_report)
        final_report = round_report

        if _decision_from_report(round_report, profile.approval_threshold) == "approved":
            decision = "approved"
            break

        working_package = revise_idea_package(working_package, round_report, round_index)

    critique_report = {
        "summary": final_report["summary"] if final_report else "No critique result was produced.",
        "strengths": list(final_report["strengths"] if final_report else []),
        "risks": list(final_report["risks"] if final_report else []),
        "open_questions": list(final_report["open_questions"] if final_report else []),
    }
    blocking_issues = _collect_blocking_issues(final_report or {}, profile.approval_threshold)
    recommendation = _recommendation_for_report(final_report or {}, profile.approval_threshold)
    decision = _decision_from_report(final_report or {}, profile.approval_threshold)

    return {
        "decision": decision,
        "rounds": rounds,
        "scorecard": {
            "overall": final_report["overall"] if final_report else 0.0,
            "threshold": profile.approval_threshold,
            "max_rounds": profile.max_rounds,
            "rubric_name": profile.name,
            "dimension_scores": dict(final_report["dimension_scores"] if final_report else {}),
            "review_mode": final_report["review_mode"] if final_report else review_mode,
            "blocking_issues": blocking_issues,
            "recommendation": recommendation,
            "committee_decision": dict(committee_decision),
        },
        "committee_decision": committee_decision,
        "critique_report": critique_report,
        "idea_package": working_package,
    }
