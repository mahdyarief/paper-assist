from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engine.secret_redaction import contains_secret, redact_secrets

from .agent_packs import (
    KIND_EXPERIMENT,
    KIND_IDEATION,
    KIND_REVIEW,
    build_experiment_pack,
    build_ideation_pack,
    build_review_pack,
    import_experiment,
    import_ideation,
    import_review,
    load_plan,
    load_task,
)
from .api import load_service
from .compute import job_manifest_inputs
from .harness import harness_status
from .models import ExecutionProfile
from .writing_pack import load_writing_plan

_FORBIDDEN_SECRET_OPTIONS = {
    "--api-key",
    "--openai-api-key",
    "--openai-writeup-api-key",
    "--anthropic-api-key",
    "--auth-token",
    "--password",
}
_MAX_JOB_MANIFEST_BYTES = 1024 * 1024
WRITING_JOB_MANIFEST_SCHEMA = "paperassist.writing-job/v1"
_WRITING_MANIFEST_FIELDS = frozenset(
    {
        "abstract",
        "bibliography_path",
        "claim_ids",
        "document_path",
        "instructions",
        "main_tex",
        "main_tex_path",
        "outline",
        "reference_paths",
        "template",
        "title",
        "topic",
    }
)


def _emit(payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    print(redact_secrets(rendered))


def _reject_secret_argv(argv: Sequence[str]) -> None:
    for item in argv:
        option = item.split("=", 1)[0]
        if option in _FORBIDDEN_SECRET_OPTIONS:
            raise SystemExit(
                f"{option} is forbidden; store credentials in the PaperAssist user config directory"
            )


def _load_job_manifest(
    workspace: Path,
    raw_path: str,
    *,
    profile: ExecutionProfile | str,
) -> dict[str, Any]:
    lexical = Path(raw_path).expanduser()
    lexical = lexical if lexical.is_absolute() else workspace / lexical
    if lexical.is_symlink():
        raise ValueError("job manifest must not be a symbolic link")
    path = lexical.resolve(strict=True)
    if workspace != path and workspace not in path.parents:
        raise ValueError("job manifest must be inside the workspace")
    if not path.is_file() or path.stat().st_size > _MAX_JOB_MANIFEST_BYTES:
        raise ValueError("job manifest is missing or exceeds 1 MiB")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("job manifest must contain a JSON object")
    if contains_secret(payload):
        raise ValueError("job manifest must not contain credentials")
    normalized_profile = ExecutionProfile(profile)
    if normalized_profile is ExecutionProfile.FULL:
        return job_manifest_inputs(payload)
    if normalized_profile is not ExecutionProfile.WRITING_ONLY:
        raise ValueError("research profile does not accept a job manifest")
    if payload.get("schema") != WRITING_JOB_MANIFEST_SCHEMA:
        raise ValueError(
            f"writing manifest schema must be {WRITING_JOB_MANIFEST_SCHEMA}"
        )
    unknown = sorted(set(payload) - {"schema"} - _WRITING_MANIFEST_FIELDS)
    if unknown:
        raise ValueError(
            "writing manifest contains unsupported fields: "
            + ", ".join(unknown)
        )
    normalized = {
        str(key): value for key, value in payload.items() if key != "schema"
    }
    if not normalized:
        raise ValueError("writing manifest must contain a writing request")
    return normalized


def _add_writing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--abstract", default=None)
    parser.add_argument("--instructions", default=None)
    parser.add_argument("--main-tex", default=None)
    parser.add_argument("--bibliography", default=None)


def _writing_cli_inputs(args: argparse.Namespace) -> dict[str, str]:
    values = {
        "title": getattr(args, "title", None),
        "topic": getattr(args, "topic", None),
        "abstract": getattr(args, "abstract", None),
        "instructions": getattr(args, "instructions", None),
        "main_tex": getattr(args, "main_tex", None),
        "bibliography_path": getattr(args, "bibliography", None),
    }
    return {
        key: str(value)
        for key, value in values.items()
        if value is not None and str(value).strip()
    }


def _workspace_text_file(workspace: Path, raw_path: str, *, what: str) -> Path:
    lexical = Path(raw_path).expanduser()
    lexical = lexical if lexical.is_absolute() else workspace / lexical
    if lexical.is_symlink():
        raise ValueError(f"{what} must not be a symbolic link")
    path = lexical.resolve(strict=True)
    if workspace != path and workspace not in path.parents:
        raise ValueError(f"{what} must be inside the workspace")
    if not path.is_file():
        raise ValueError(f"{what} must be a regular file")
    return path


def _static_preflight(workspace: Path) -> dict[str, Any]:
    tools = {
        name: shutil.which(name)
        for name in ("pdflatex", "bibtex", "latexmk", "pdftoppm")
    }
    checks = {
        "python_supported": (3, 10) <= sys.version_info[:2] <= (3, 12),
        "workspace_exists": workspace.is_dir(),
        "workspace_writable": workspace.is_dir() and os_access_write(workspace),
        "latex_compiler_available": bool(tools["latexmk"] or tools["pdflatex"]),
        "bibtex_available": bool(tools["bibtex"]),
        "pdf_renderer_available": bool(tools["pdftoppm"]),
    }
    required = (
        "python_supported",
        "workspace_exists",
        "workspace_writable",
    )
    return {
        "status": "CODE_VERIFIED" if all(checks[key] for key in required) else "FAILED",
        "checks": checks,
        "tools": {key: bool(value) for key, value in tools.items()},
    }


def os_access_write(path: Path) -> bool:
    import os

    return os.access(path, os.W_OK)


def _run_write_command(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if args.scaffold and args.import_path:
        raise ValueError("--scaffold and --import are mutually exclusive")
    if args.patch:
        if not args.target or not args.anchor:
            raise ValueError("--patch requires --target and --anchor")
        if bool(args.replacement) == bool(args.replacement_file):
            raise ValueError(
                "--patch requires exactly one of --replacement or --replacement-file"
            )
        if args.replacement_file:
            replacement_path = _workspace_text_file(
                workspace, args.replacement_file, what="replacement file"
            )
            replacement = replacement_path.read_text(encoding="utf-8")
        else:
            replacement = str(args.replacement)
        target_path = _workspace_text_file(workspace, args.target, what="patch target")
        source_sha = args.source_sha or hashlib.sha256(
            target_path.read_bytes()
        ).hexdigest()
        from .writing_patch import apply_patch

        _, service = load_service(workspace, profile=ExecutionProfile.WRITING_ONLY)
        result = apply_patch(
            workspace,
            memory=service.memory,
            run_id=args.run_id or "cli-patch",
            target=args.target,
            source_sha256=source_sha,
            anchor=args.anchor,
            replacement=replacement,
            instructions=str(args.instructions or ""),
        )
        _emit(result.to_dict())
        return 0

    _, service = load_service(workspace, profile=ExecutionProfile.WRITING_ONLY)
    if args.import_path:
        if not args.run_id:
            raise ValueError("--import requires --run-id of the writing pack")
        plan = load_writing_plan(workspace, run_id=args.run_id)
        inputs: dict[str, Any] = dict(plan.get("inputs") or {})
        inputs.update(_writing_cli_inputs(args))
        draft_file = _workspace_text_file(workspace, args.import_path, what="draft")
        inputs["draft_path"] = draft_file.relative_to(workspace).as_posix()
        inputs["writing_pack_run_id"] = args.run_id
        handle = service.run(profile=ExecutionProfile.WRITING_ONLY, inputs=inputs)
        payload = handle.to_dict()
        payload["writing_pack_run_id"] = args.run_id
        _emit(payload)
        return 0

    scaffold_inputs: dict[str, Any] = (
        _load_job_manifest(
            workspace,
            args.job_manifest,
            profile=ExecutionProfile.WRITING_ONLY,
        )
        if args.job_manifest
        else {}
    )
    scaffold_inputs.update(_writing_cli_inputs(args))
    handle = service.run(
        profile=ExecutionProfile.WRITING_ONLY,
        inputs=scaffold_inputs or None,
    )
    payload = handle.to_dict()
    try:
        payload["writing_pack"] = load_writing_plan(
            workspace, run_id=handle.run_id
        )
    except FileNotFoundError:
        payload["writing_pack"] = None
    _emit(payload)
    return 0


def _pack_inputs(args: argparse.Namespace) -> dict[str, Any]:
    values = {
        "topic": args.topic,
        "venue": args.venue,
        "constraints": args.constraints,
        "num_ideas": args.num_ideas,
        "manuscript": args.manuscript,
        "hypothesis": args.hypothesis,
        "dataset": args.dataset,
        "metrics": args.metrics,
        "success_criteria": args.success_criteria,
        "bibliography_path": args.bibliography,
    }
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != []
    }


def _default_pack_run_id(kind: str, inputs: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"kind": kind, "inputs": inputs},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"{kind}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"


def _run_pack_command(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("workspace does not exist")
    kind = str(args.kind)
    if args.plan or args.task:
        if not args.run_id:
            raise ValueError("--plan/--task require --run-id")
        payload = (
            load_plan(workspace, run_id=args.run_id, kind=kind)
            if args.plan
            else load_task(
                workspace,
                run_id=args.run_id,
                kind=kind,
                task_id=str(args.task),
            )
        )
        _emit(payload)
        return 0

    if args.import_path:
        if not args.run_id:
            raise ValueError("--import requires --run-id of the pack")
        importer = {
            KIND_IDEATION: import_ideation,
            KIND_REVIEW: import_review,
            KIND_EXPERIMENT: import_experiment,
        }[kind]
        _emit(importer(workspace, run_id=args.run_id, result_path=args.import_path))
        return 0

    inputs = _pack_inputs(args)
    run_id = args.run_id or _default_pack_run_id(kind, inputs)
    builder = {
        KIND_IDEATION: build_ideation_pack,
        KIND_REVIEW: build_review_pack,
        KIND_EXPERIMENT: build_experiment_pack,
    }[kind]
    pack = builder(workspace, run_id=run_id, payload=inputs)
    _emit(
        {
            "run_id": run_id,
            "provider_calls": 0,
            "pack": pack.to_dict(),
            "next_action": (
                "Execute every task in the pack with the AI harness, then import "
                f"the result with `paperassist pack --kind {kind} --run-id {run_id} "
                f"--import {pack.target_path}`."
            ),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperassist")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--workspace", default=".")

    pack = subparsers.add_parser(
        "pack",
        help="Scaffold or import an agent-executable ideation/review/experiment pack",
    )
    pack.add_argument("--workspace", default=".")
    pack.add_argument(
        "--kind",
        required=True,
        choices=[KIND_IDEATION, KIND_REVIEW, KIND_EXPERIMENT],
    )
    pack.add_argument("--run-id", default=None)
    pack.add_argument("--scaffold", action="store_true")
    pack.add_argument("--import", dest="import_path", default=None)
    pack.add_argument("--plan", action="store_true", help="Print the pack plan only")
    pack.add_argument("--task", default=None, help="Print one task file by id")
    pack.add_argument("--topic", default=None)
    pack.add_argument("--venue", default=None)
    pack.add_argument("--constraints", default=None)
    pack.add_argument("--num-ideas", type=int, default=None)
    pack.add_argument("--manuscript", default=None)
    pack.add_argument("--hypothesis", default=None)
    pack.add_argument("--dataset", default=None)
    pack.add_argument("--metrics", action="append", default=None)
    pack.add_argument("--success-criteria", default=None)
    pack.add_argument("--bibliography", default=None)

    run = subparsers.add_parser("run")
    run.add_argument(
        "--profile",
        required=True,
        choices=[profile.value for profile in ExecutionProfile],
    )
    run.add_argument("--workspace", default=".")
    run.add_argument(
        "--legacy-mode",
        choices=["writeup", "research_partner", "mvp", "scientist"],
        default=None,
    )
    run.add_argument("--proposal-id", default=None)
    run.add_argument("--idempotency-key", default=None)
    run.add_argument("--job-manifest", default=None)
    _add_writing_arguments(run)

    write = subparsers.add_parser(
        "write",
        help="Scaffold agent writing tasks, import a finished draft, or patch one anchor",
    )
    write.add_argument("--workspace", default=".")
    write.add_argument("--job-manifest", default=None)
    write.add_argument("--run-id", default=None)
    write.add_argument(
        "--scaffold",
        action="store_true",
        help="Only build the writing pack (default when no --import is given)",
    )
    write.add_argument(
        "--import",
        dest="import_path",
        default=None,
        help="Path to the harness-produced .tex document to verify and register",
    )
    write.add_argument(
        "--patch",
        action="store_true",
        help="Apply an anchored replacement produced by the AI harness",
    )
    write.add_argument("--target", default=None)
    write.add_argument("--anchor", default=None)
    write.add_argument("--replacement", default=None)
    write.add_argument("--replacement-file", default=None)
    write.add_argument("--source-sha", default=None)
    _add_writing_arguments(write)

    approve = subparsers.add_parser("approve")
    approve.add_argument("--proposal-id", required=True)
    approve.add_argument("--workspace", default=".")
    approve.add_argument("--scope", choices=["static", "mini", "full"], default="full")

    experiment = subparsers.add_parser("experiment")
    experiment.add_argument("--proposal-id", required=True)
    experiment.add_argument("--workspace", default=".")
    experiment.add_argument(
        "--stage",
        required=True,
        choices=["static_check", "mini_experiment"],
    )

    resume = subparsers.add_parser("resume")
    resume.add_argument("--workspace", default=".")
    resume.add_argument("--run-id", default=None)

    status = subparsers.add_parser("status")
    status.add_argument("--workspace", default=".")
    status.add_argument("--run-id", default=None)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--workspace", default=".")
    publish.add_argument(
        "--template",
        required=True,
        choices=["generic", "cvpr", "ieee", "elsevier"],
    )
    publish.add_argument("--main-tex", default=None)

    release = subparsers.add_parser("release")
    release.add_argument("--workspace", default=".")
    release.add_argument("--run-id", default=None)

    for alias, profile in (
        ("writeup", ExecutionProfile.WRITING_ONLY.value),
        ("research_partner", ExecutionProfile.RESEARCH.value),
        ("mvp", ExecutionProfile.FULL.value),
        ("scientist", ExecutionProfile.FULL.value),
    ):
        compatibility = subparsers.add_parser(alias)
        compatibility.add_argument("--workspace", default=".")
        if alias == "writeup":
            compatibility.add_argument("--job-manifest", default=None)
            _add_writing_arguments(compatibility)
        compatibility.set_defaults(compatibility_profile=profile, legacy_mode=alias)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    _reject_secret_argv(arguments)
    args = build_parser().parse_args(arguments)

    if args.command == "preflight":
        workspace = Path(args.workspace).expanduser().resolve()
        payload = _static_preflight(workspace)
        payload["harness"] = harness_status(workspace)
        _emit(payload)
        return 1 if payload["status"] == "FAILED" else 0

    if args.command == "pack":
        return _run_pack_command(args)

    if args.command == "write":
        return _run_write_command(args)

    if hasattr(args, "compatibility_profile"):
        _, service = load_service(args.workspace, profile=args.compatibility_profile)
        compatibility_inputs = None
        if args.legacy_mode == "writeup":
            workspace = Path(args.workspace).expanduser().resolve()
            compatibility_inputs = (
                _load_job_manifest(
                    workspace,
                    args.job_manifest,
                    profile=ExecutionProfile.WRITING_ONLY,
                )
                if args.job_manifest
                else {}
            )
            compatibility_inputs.update(_writing_cli_inputs(args))
        result = service.run(
            profile=args.compatibility_profile,
            legacy_mode=args.legacy_mode,
            inputs=compatibility_inputs,
        )
        _emit(result.to_dict())
        return 0

    _, service = load_service(
        args.workspace,
        profile=getattr(args, "profile", None),
    )
    if args.command == "run":
        workspace = Path(args.workspace).expanduser().resolve()
        run_inputs: dict[str, Any] = (
            _load_job_manifest(
                workspace,
                args.job_manifest,
                profile=args.profile,
            )
            if args.job_manifest
            else {}
        )
        writing_inputs = _writing_cli_inputs(args)
        if (
            writing_inputs
            and ExecutionProfile(args.profile)
            is not ExecutionProfile.WRITING_ONLY
        ):
            raise ValueError(
                "writing arguments require --profile writing-only"
            )
        overlap = sorted(set(run_inputs) & set(writing_inputs))
        if overlap:
            raise ValueError(
                "writing argument duplicates manifest fields: "
                + ", ".join(overlap)
            )
        run_inputs.update(writing_inputs)
        result = service.run(
            profile=args.profile,
            legacy_mode=args.legacy_mode,
            proposal_id=args.proposal_id,
            idempotency_key=args.idempotency_key,
            inputs=run_inputs or None,
        )
        _emit(result.to_dict())
    elif args.command == "approve":
        _emit(
            service.approve(
                args.proposal_id,
                scope={"maximum_stage": args.scope},
            )
        )
    elif args.command == "experiment":
        _emit(
            service.execute_experiment_stage(
                args.proposal_id,
                args.stage,
            )
        )
    elif args.command == "resume":
        _emit(service.resume(args.run_id).to_dict())
    elif args.command == "status":
        _emit(service.unified_status(args.run_id))
    elif args.command == "publish":
        _emit(service.publish(template=args.template, main_tex=args.main_tex))
    elif args.command == "release":
        _emit(service.release(run_id=args.run_id).to_dict())
    else:
        raise AssertionError(args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
