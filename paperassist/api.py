from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from engine.secret_redaction import contains_secret

from .compute import JobSpec, build_compute_binding
from .config import PaperAssistConfig
from .experiments import ExperimentManager
from .models import CompletionGate, ExecutionProfile, ExperimentStage, WorkflowStatus
from .policy import ExecutionPolicy
from .workflow import InvalidTransition, WorkflowEngine


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    profile: str
    status: str
    checkpoint: str | None
    workspace: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaperAssistService:
    """Single public facade used by the CLI, frontend and compatibility wrappers."""

    _WRITING_ONLY_SCALAR_FIELDS = frozenset(
        {
            "abstract",
            "citation_query",
            "draft_text",
            "instructions",
            "template",
            "title",
            "topic",
            "writing_pack_run_id",
        }
    )
    _WRITING_ONLY_SEQUENCE_FIELDS = frozenset({"claim_ids", "outline"})
    _WRITING_ONLY_PATH_FIELDS = frozenset(
        {
            "bibliography_path",
            "document_path",
            "draft_path",
            "draft_file",
            "main_tex",
            "main_tex_path",
            "reference_paths",
        }
    )
    _WRITING_ONLY_SUFFIXES = frozenset(
        {".bib", ".docx", ".md", ".pdf", ".rst", ".tex", ".txt"}
    )

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workflow = WorkflowEngine(self.workspace)
        self.memory = self.workflow.memory

    @staticmethod
    def _handle(state: Mapping[str, Any]) -> RunHandle:
        return RunHandle(
            run_id=str(state["id"]),
            profile=str(state["profile"]),
            status=str(state["status"]),
            checkpoint=state.get("checkpoint"),
            workspace=str(state["workspace"]),
            metadata=dict(state.get("metadata") or {}),
        )

    @classmethod
    def _validate_writing_only_inputs(
        cls,
        inputs: Mapping[str, Any],
    ) -> list[Path]:
        allowed = (
            cls._WRITING_ONLY_SCALAR_FIELDS
            | cls._WRITING_ONLY_SEQUENCE_FIELDS
            | cls._WRITING_ONLY_PATH_FIELDS
        )
        unknown = sorted(str(key) for key in inputs if str(key) not in allowed)
        if unknown:
            raise PermissionError(
                "writing-only inputs contain unsupported fields: "
                + ", ".join(unknown)
            )
        paths: list[Path] = []
        for key, value in inputs.items():
            if key in cls._WRITING_ONLY_SCALAR_FIELDS:
                if not isinstance(value, str):
                    raise TypeError(f"writing-only input {key} must be a string")
                continue
            if key in cls._WRITING_ONLY_SEQUENCE_FIELDS:
                if not isinstance(value, list | tuple) or any(
                    not isinstance(item, str) for item in value
                ):
                    raise TypeError(
                        f"writing-only input {key} must be a sequence of strings"
                    )
                continue
            raw_paths = value if isinstance(value, list | tuple) else (value,)
            if key != "reference_paths" and len(raw_paths) != 1:
                raise TypeError(f"writing-only input {key} accepts one path")
            for raw_path in raw_paths:
                if not isinstance(raw_path, str | Path):
                    raise TypeError(
                        f"writing-only input {key} must contain filesystem paths"
                    )
                path = Path(raw_path)
                if path.suffix.lower() not in cls._WRITING_ONLY_SUFFIXES:
                    raise PermissionError(
                        f"writing-only context denies non-document path: {path.name}"
                    )
                paths.append(path)
        return paths

    def run(
        self,
        *,
        profile: str | ExecutionProfile,
        legacy_mode: str | None = None,
        proposal_id: str | None = None,
        idempotency_key: str | None = None,
        inputs: Mapping[str, Any] | None = None,
    ) -> RunHandle:
        normalized = ExecutionProfile(profile)
        policy = ExecutionPolicy(normalized)
        normalized_inputs = dict(inputs or {})
        if contains_secret(normalized_inputs):
            raise ValueError(
                "workflow inputs must not contain credentials or secret-like values"
            )
        context_paths = (
            self._validate_writing_only_inputs(normalized_inputs)
            if normalized is ExecutionProfile.WRITING_ONLY
            else [
                Path(value)
                for key, value in normalized_inputs.items()
                if key.endswith(("_path", "_file"))
                and isinstance(value, str | Path)
            ]
        )
        policy.validate_context_paths(context_paths)
        effective_proposal_id = proposal_id
        manager = ExperimentManager(
            self.workspace,
            profile=normalized,
            memory=self.memory,
        )
        raw_job = normalized_inputs.get("job_spec")
        compute_binding: dict[str, Any] | None = None
        experiment_stage_bindings: dict[str, dict[str, Any]] = {}
        cost_limit: float | None = None
        if raw_job is not None:
            if normalized is not ExecutionProfile.FULL:
                raise ValueError("job_spec is only accepted by the full profile")
            if not isinstance(raw_job, Mapping):
                raise TypeError("job_spec must be a mapping")
            raw_config = normalized_inputs.get("compute_config") or {}
            if not isinstance(raw_config, Mapping):
                raise TypeError("compute_config must be a mapping")
            canonical_spec, compute_binding = build_compute_binding(
                self.workspace,
                job_spec=raw_job,
                compute_backend=str(
                    normalized_inputs.get("compute_backend") or "local"
                ),
                compute_config=raw_config,
            )
            raw_cost_limit = normalized_inputs.get("cost_limit")
            if raw_cost_limit is not None:
                if (
                    isinstance(raw_cost_limit, bool)
                    or not isinstance(raw_cost_limit, int | float)
                    or not math.isfinite(float(raw_cost_limit))
                    or float(raw_cost_limit) <= 0
                ):
                    raise ValueError(
                        "cost_limit must be a finite positive number"
                    )
                cost_limit = float(raw_cost_limit)
            normalized_inputs.update(
                {
                    "job_spec": canonical_spec.to_dict(),
                    "compute_backend": compute_binding["backend"],
                    "compute_config": dict(compute_binding["compute_config"]),
                }
            )
            raw_stages = normalized_inputs.get("experiment_stages") or {}
            if not isinstance(raw_stages, Mapping):
                raise TypeError("experiment_stages must be a mapping")
            for stage_name in ("static_check", "mini_experiment"):
                raw_stage = raw_stages.get(stage_name)
                if raw_stage is None:
                    continue
                if not isinstance(raw_stage, Mapping):
                    raise TypeError(
                        f"experiment stage {stage_name} must be a mapping"
                    )
                raw_stage_spec = raw_stage.get("job_spec")
                raw_stage_config = raw_stage.get("compute_config") or {}
                if not isinstance(raw_stage_spec, Mapping) or not isinstance(
                    raw_stage_config,
                    Mapping,
                ):
                    raise TypeError(
                        f"experiment stage {stage_name} requires job_spec and config"
                    )
                stage_spec, stage_binding = build_compute_binding(
                    self.workspace,
                    job_spec=raw_stage_spec,
                    compute_backend=str(
                        raw_stage.get("compute_backend") or "local"
                    ),
                    compute_config=raw_stage_config,
                )
                if stage_binding["backend"] != "local" or not stage_spec.execute:
                    raise ValueError(
                        f"experiment stage {stage_name} must be an executable "
                        "local sandbox job"
                    )
                if tuple(stage_spec.command) == tuple(canonical_spec.command):
                    raise ValueError(
                        f"experiment stage {stage_name} must use a distinct "
                        "stage-limited command"
                    )
                if stage_name == "static_check" and (
                    stage_spec.resources.gpus != 0
                    or (
                        stage_spec.resources.timeout_seconds is not None
                        and stage_spec.resources.timeout_seconds > 300
                    )
                ):
                    raise ValueError(
                        "static_check must use zero GPUs and at most 300 seconds"
                    )
                if stage_name == "mini_experiment" and (
                    stage_spec.resources.gpus > 1
                    or (
                        stage_spec.resources.timeout_seconds is not None
                        and stage_spec.resources.timeout_seconds > 1800
                    )
                ):
                    raise ValueError(
                        "mini_experiment is limited to one GPU and 1800 seconds"
                    )
                experiment_stage_bindings[stage_name] = stage_binding
            if canonical_spec.execute and set(experiment_stage_bindings) != {
                "static_check",
                "mini_experiment",
            }:
                raise ValueError(
                    "executable full jobs require immutable static_check and "
                    "mini_experiment stage jobs"
                )
            if canonical_spec.execute:
                bound_specs = [
                    canonical_spec,
                    *[
                        JobSpec.from_dict(binding["job_spec"])
                        for binding in experiment_stage_bindings.values()
                    ],
                ]
                estimated_costs: list[float] = []
                for bound_spec in bound_specs:
                    raw_estimate = bound_spec.metadata.get("estimated_cost")
                    if (
                        isinstance(raw_estimate, bool)
                        or not isinstance(raw_estimate, int | float)
                        or not math.isfinite(float(raw_estimate))
                        or float(raw_estimate) <= 0
                    ):
                        raise ValueError(
                            "every executable experiment stage requires a "
                            "finite positive metadata.estimated_cost"
                        )
                    estimated_costs.append(float(raw_estimate))
                if cost_limit is None or sum(estimated_costs) > cost_limit:
                    raise ValueError(
                        "experiment estimated cost exceeds its approved cost_limit"
                    )
            normalized_inputs["experiment_stages"] = {
                stage: {
                    "compute_backend": binding["backend"],
                    "compute_config": dict(binding["compute_config"]),
                    "job_spec": dict(binding["job_spec"]),
                }
                for stage, binding in experiment_stage_bindings.items()
            }
        if normalized is ExecutionProfile.FULL:
            if effective_proposal_id:
                existing = manager.get_proposal(effective_proposal_id)
                if cost_limit is not None and existing.cost_limit != cost_limit:
                    raise ValueError(
                        "job manifest cost_limit does not match the proposal"
                    )
                persisted_binding = existing.metadata.get("compute_binding")
                persisted_stages = existing.metadata.get(
                    "experiment_stage_bindings"
                )
                if compute_binding is not None:
                    if isinstance(persisted_binding, Mapping):
                        if persisted_binding.get(
                            "binding_sha256"
                        ) != compute_binding.get("binding_sha256"):
                            raise ValueError(
                                "job manifest does not match the immutable "
                                "proposal binding"
                            )
                        if {
                            stage: binding.get("binding_sha256")
                            for stage, binding in experiment_stage_bindings.items()
                        } != {
                            str(stage): dict(binding).get("binding_sha256")
                            for stage, binding in dict(
                                persisted_stages or {}
                            ).items()
                            if isinstance(binding, Mapping)
                        }:
                            raise ValueError(
                                "experiment stage manifests do not match the "
                                "immutable proposal bindings"
                            )
                    else:
                        if not isinstance(raw_job, Mapping):
                            raise TypeError("job_spec must be a mapping")
                        normalized_inputs["job_spec"] = JobSpec.from_dict(
                            raw_job
                        ).to_dict()
                        compute_binding = None
            else:
                command = (
                    tuple(compute_binding["job_spec"]["command"])
                    if compute_binding is not None
                    else ()
                )
                provenance_spec = (
                    JobSpec.from_dict(compute_binding["job_spec"])
                    if compute_binding is not None
                    else None
                )
                bound_metadata = (
                    dict(provenance_spec.metadata)
                    if provenance_spec is not None
                    else {}
                )
                effective_proposal_id = manager.propose(
                    title="PaperAssist full workflow",
                    command=command,
                    code_paths=bound_metadata.get("code_paths", ()),
                    config_paths=bound_metadata.get(
                        "config_paths",
                        (),
                    ),
                    data_paths=bound_metadata.get("data_paths", ()),
                    cost_limit=cost_limit,
                    metadata={
                        "workflow_idempotency_key": idempotency_key or "",
                        **(
                            {"compute_binding": compute_binding}
                            if compute_binding is not None
                            else {}
                        ),
                        **(
                            {
                                "experiment_stage_bindings": (
                                    experiment_stage_bindings
                                )
                            }
                            if experiment_stage_bindings
                            else {}
                        ),
                    },
                ).proposal_id
        metadata = {
            "legacy_mode": legacy_mode,
            "inputs": normalized_inputs,
            "proposal_id": effective_proposal_id,
            "executor": "ai-harness",
        }
        run_id = self.workflow.create(
            normalized,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        self.workflow.transition(
            run_id,
            WorkflowStatus.RUNNING,
            checkpoint="policy",
            detail=f"execution profile {normalized.value} activated",
            idempotency_key=f"{run_id}:policy",
        )

        if normalized is ExecutionProfile.FULL:
            try:
                manager.require_approval(
                    str(effective_proposal_id),
                    ExperimentStage.FULL_EXPERIMENT,
                )
            except PermissionError:
                state = self.workflow.transition(
                    run_id,
                    WorkflowStatus.AWAITING_APPROVAL,
                    checkpoint="proposal",
                    detail=f"full profile requires approved proposal {effective_proposal_id}",
                    idempotency_key=f"{run_id}:awaiting-approval",
                )
                return self._handle(state)

        return self._handle(self._scaffold_pack(run_id))

    _PACK_KINDS = frozenset({"ideation", "review", "experiment", "writing"})

    @classmethod
    def _pack_kind(cls, inputs: Mapping[str, Any]) -> str:
        explicit = str(inputs.get("pack_kind") or "").strip().lower()
        if explicit in cls._PACK_KINDS:
            return explicit
        if inputs.get("manuscript") or inputs.get("document_path"):
            return "review"
        if inputs.get("hypothesis") or inputs.get("metrics"):
            return "experiment"
        if inputs.get("num_ideas") or inputs.get("venue") or inputs.get("constraints"):
            return "ideation"
        return "writing"

    def _scaffold_pack(self, run_id: str) -> dict[str, Any]:
        """Build the task pack the AI harness will execute.

        PaperAssist is model-free: a run never calls a provider. It scaffolds
        deterministic work and waits for the harness to return a result.
        """
        from .agent_packs import (
            build_experiment_pack,
            build_ideation_pack,
            build_review_pack,
        )
        from .writing import WritingEngine

        state = self.workflow.get(run_id)
        metadata = dict(state.get("metadata") or {})
        inputs = dict(metadata.get("inputs") or {})
        if metadata.get("proposal_id") and "proposal_id" not in inputs:
            inputs["proposal_id"] = metadata["proposal_id"]
        kind = self._pack_kind(inputs)
        if kind == "writing" and not any(
            inputs.get(key)
            for key in (
                "abstract",
                "draft_path",
                "draft_text",
                "existing_draft",
                "instructions",
                "main_tex",
                "title",
                "topic",
            )
        ):
            return self.workflow.record_checkpoint(
                run_id,
                checkpoint="pack",
                detail="waiting for the harness to supply a writing request",
                metadata_updates={
                    "executor": "ai-harness",
                    "provider_calls": 0,
                    "pack_kind": kind,
                    "pack_state": "AWAITING_REQUEST",
                },
                idempotency_key=f"{run_id}:pack",
            )
        if kind == "writing":
            pack = WritingEngine(self.workspace, memory=self.memory).scaffold(
                run_id=run_id,
                payload=inputs,
            )
        else:
            builder = {
                "ideation": build_ideation_pack,
                "review": build_review_pack,
                "experiment": build_experiment_pack,
            }[kind]
            pack = builder(self.workspace, run_id=run_id, payload=inputs)
        return self.workflow.record_checkpoint(
            run_id,
            checkpoint="pack",
            detail=f"{kind} task pack ready for the AI harness",
            metadata_updates={
                "executor": "ai-harness",
                "provider_calls": 0,
                "pack_kind": kind,
                "pack_run_id": pack.run_id,
                "pack_plan": pack.plan_path,
                "pack_target": pack.target_path,
                "pack_brief": pack.brief_path,
                "pack_tasks": [task.task_id for task in pack.tasks],
                "pack_state": "AWAITING_HARNESS",
            },
            idempotency_key=f"{run_id}:pack",
        )

    def import_pack(self, run_id: str, result_path: str) -> dict[str, Any]:
        """Validate a harness result against the run's pack and record it."""
        from .agent_packs import import_experiment, import_ideation, import_review
        from .writing import WritingEngine

        state = self.workflow.get(run_id)
        metadata = dict(state.get("metadata") or {})
        kind = str(metadata.get("pack_kind") or "")
        if not kind:
            raise InvalidTransition("workflow has no task pack to import into")
        inputs = dict(metadata.get("inputs") or {})
        if kind == "writing":
            result = WritingEngine(self.workspace, memory=self.memory).import_draft(
                run_id=run_id,
                payload={**inputs, "writing_pack_run_id": metadata.get("pack_run_id") or run_id},
                draft_path=result_path,
            ).to_dict()
        else:
            result = {
                "ideation": import_ideation,
                "review": import_review,
                "experiment": import_experiment,
            }[kind](self.workspace, run_id=str(metadata.get("pack_run_id") or run_id), result_path=result_path)
        return self.workflow.record_checkpoint(
            run_id,
            checkpoint="pack-import",
            detail=f"harness result validated for the {kind} pack",
            metadata_updates={
                "provider_calls": 0,
                "pack_state": "IMPORTED",
                "pack_result_path": result_path,
                "pack_result": result,
            },
            idempotency_key=f"{run_id}:pack-import",
        )

    def approve(
        self,
        proposal_id: str,
        *,
        approved_by: str = "local-owner",
        scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_scope = dict(scope or {})
        if contains_secret(normalized_scope):
            raise ValueError("approval scope must not contain credentials")
        manager = ExperimentManager(
            self.workspace,
            profile=ExecutionProfile.FULL,
            memory=self.memory,
        )
        proposal = manager.get_proposal(proposal_id)
        binding = proposal.metadata.get("compute_binding")
        if isinstance(binding, Mapping):
            maximum = str(
                normalized_scope.get("maximum_stage")
                or normalized_scope.get("stage")
                or "full"
            )
            normalized_scope["maximum_stage"] = maximum
            immutable_scope = {
                "compute_binding_sha256": binding.get("binding_sha256"),
                "job_fingerprint": binding.get("job_fingerprint"),
                "compute_backend": binding.get("backend"),
                "worktree": binding.get("worktree"),
                "compute_config_sha256": binding.get("compute_config_sha256"),
                "executable_sha256": dict(
                    binding.get("executable") or {}
                ).get("sha256"),
                "inputs_sha256": binding.get("inputs_sha256"),
            }
            for key, expected in immutable_scope.items():
                supplied = normalized_scope.get(key)
                if supplied is not None and supplied != expected:
                    raise ValueError(
                        f"approval scope cannot override immutable field {key}"
                    )
                normalized_scope[key] = expected
        approval_id = manager.approve(
            proposal_id,
            approved_by=approved_by,
            scope=normalized_scope,
        )
        return {"approval_id": approval_id, "proposal_id": proposal_id, "status": "APPROVED"}

    def execute_experiment_stage(
        self,
        proposal_id: str,
        stage: str | ExperimentStage,
    ) -> dict[str, Any]:
        normalized_stage = (
            stage
            if isinstance(stage, ExperimentStage)
            else {
                "static_check": ExperimentStage.STATIC_CHECK,
                "mini_experiment": ExperimentStage.MINI_EXPERIMENT,
                "full_experiment": ExperimentStage.FULL_EXPERIMENT,
            }[str(stage).strip().lower()]
        )
        if normalized_stage is ExperimentStage.FULL_EXPERIMENT:
            raise ValueError(
                "the full experiment is executed by the AI harness under its approval"
            )
        manager = ExperimentManager(
            self.workspace,
            profile=ExecutionProfile.FULL,
            memory=self.memory,
        )
        return manager.execute_stage(
            proposal_id,
            normalized_stage,
        ).to_dict()

    def status(self, run_id: str | None = None) -> RunHandle:
        state = self.workflow.get(run_id) if run_id else self.workflow.latest()
        return self._handle(state)

    def unified_status(
        self,
        run_id: str | None = None,
        process_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Shared read-only projection for CLI/API/frontend. No side effects."""
        from .run_status import build_unified_status

        state = self.workflow.get(run_id) if run_id else self.workflow.latest()
        handle = self._handle(state)
        unified = build_unified_status(state, process_payload)
        payload = handle.to_dict()
        payload["unified"] = unified.to_dict()
        return payload

    def resume(self, run_id: str | None = None) -> RunHandle:
        state = self.workflow.get(run_id) if run_id else self.workflow.latest()
        current = WorkflowStatus(state["status"])
        metadata = dict(state.get("metadata") or {})
        if metadata.get("pack_state") == "IMPORTED":
            if current is not WorkflowStatus.RUNNING:
                state = self.workflow.transition(
                    str(state["id"]),
                    WorkflowStatus.RUNNING,
                    checkpoint="resumed-existing-result",
                    detail="workflow reused its persisted harness result",
                    idempotency_key=f"{state['id']}:resume-existing-result",
                )
            return self._handle(state)
        if current is WorkflowStatus.AWAITING_APPROVAL:
            proposal_id = metadata.get("proposal_id")
            if not proposal_id:
                raise PermissionError("workflow has no proposal identifier")
            ExperimentManager(
                self.workspace,
                profile=ExecutionProfile.FULL,
                memory=self.memory,
            ).require_approval(
                str(proposal_id),
                ExperimentStage.FULL_EXPERIMENT,
            )
        resumed = self.workflow.transition(
            str(state["id"]),
            WorkflowStatus.RUNNING,
            checkpoint="resumed",
            detail="workflow resumed from persisted state",
            idempotency_key=f"{state['id']}:resume:{state.get('version', 0)}",
        )
        return self._handle(self._scaffold_pack(str(resumed["id"])))

    def publish(
        self,
        *,
        template: str,
        main_tex: str | Path | None = None,
    ) -> dict[str, Any]:
        from .publication import PublicationEngine

        engine = PublicationEngine()
        result = engine.publish(
            self.workspace,
            template=template,
            main_tex=str(main_tex) if main_tex else "main.tex",
            scientific_memory=self.memory,
        )
        payload = result.to_dict() if hasattr(result, "to_dict") else asdict(result)
        if not payload.get("success"):
            raise RuntimeError("publication pipeline did not pass")
        return payload

    def release(
        self,
        *,
        run_id: str | None = None,
        gate: CompletionGate | None = None,
    ) -> RunHandle:
        from .release import ReleaseVerifier

        state = self.workflow.get(run_id) if run_id else self.workflow.latest()
        if gate is not None:
            raise InvalidTransition("caller-supplied release gates are not accepted")
        verifier = ReleaseVerifier(self.workspace, memory=self.memory)
        gate = verifier.verify()
        verifier.write_report(gate)
        completed = self.workflow.transition(
            str(state["id"]),
            WorkflowStatus.COMPLETED,
            checkpoint="release",
            gate=gate,
            detail="all release gates verified",
            idempotency_key=f"{state['id']}:release",
        )
        return self._handle(completed)


def load_service(
    workspace: str | Path,
    *,
    profile: str | ExecutionProfile | None = None,
) -> tuple[PaperAssistConfig, PaperAssistService]:
    config = PaperAssistConfig.load(workspace, profile=profile)
    return config, PaperAssistService(config.workspace)
