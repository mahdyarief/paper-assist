from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp_servers.base import BasePaperAssistMcpServer, ResourceSpec, ToolSpec
from paperassist.agent_packs import (
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
from paperassist.harness import harness_status

_KINDS = (KIND_IDEATION, KIND_REVIEW, KIND_EXPERIMENT)
_BUILDERS = {
    KIND_IDEATION: build_ideation_pack,
    KIND_REVIEW: build_review_pack,
    KIND_EXPERIMENT: build_experiment_pack,
}
_IMPORTERS = {
    KIND_IDEATION: import_ideation,
    KIND_REVIEW: import_review,
    KIND_EXPERIMENT: import_experiment,
}
_INPUT_KEYS = frozenset(
    {
        "topic",
        "venue",
        "constraints",
        "num_ideas",
        "manuscript",
        "main_tex",
        "hypothesis",
        "dataset",
        "metrics",
        "success_criteria",
        "bibliography_path",
    }
)


def _workspace(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("workspace must be a directory")
    return path


def _kind(value: str) -> str:
    kind = str(value or "").strip().lower()
    if kind not in _KINDS:
        raise ValueError("kind must be one of " + ", ".join(_KINDS))
    return kind


def _default_run_id(kind: str, inputs: dict[str, Any]) -> str:
    canonical = json.dumps({"kind": kind, "inputs": inputs}, ensure_ascii=False, sort_keys=True, default=str)
    return f"{kind}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"


class PaperAssistMcpServer(BasePaperAssistMcpServer):
    """Model-free research tools for an external AI harness.

    Every tool builds or validates deterministic artifacts. None of them call a
    language model, and none accept credentials.
    """

    server_name = "paperassist"

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="harness_status",
                description=(
                    "Report whether the AI harness, plugin manifest, MCP servers and "
                    "LaTeX tools are ready. Replaces provider/credential preflight."
                ),
            ),
            ToolSpec(
                name="pack_scaffold",
                description=(
                    "Build an ideation, review or experiment task pack (plan, brief, "
                    "tasks, editable target) for the harness to execute."
                ),
                requires_workspace_lock=True,
            ),
            ToolSpec(name="pack_plan", description="Read one pack plan."),
            ToolSpec(name="pack_task", description="Read one task file from a pack."),
            ToolSpec(
                name="pack_import",
                description=(
                    "Validate a harness-produced JSON result against the pack gates "
                    "and record it in the workspace."
                ),
                requires_workspace_lock=True,
            ),
        ]

    def resources(self) -> list[ResourceSpec]:
        return [
            ResourceSpec(
                uri="paperassist://pack",
                description="Pack plan (requires kind and run_id).",
            ),
            ResourceSpec(
                uri="paperassist://task",
                description="Pack task (requires kind, run_id and task_id).",
            ),
        ]

    def harness_status(self, workspace: str) -> dict[str, Any]:
        return {"status": "ok", "harness": harness_status(_workspace(workspace))}

    def pack_scaffold(
        self,
        workspace: str,
        kind: str,
        run_id: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        root = _workspace(workspace)
        normalized_kind = _kind(kind)
        inputs = {
            key: value
            for key, value in payload.items()
            if key in _INPUT_KEYS and value not in (None, "", [], ())
        }
        normalized_run_id = run_id or _default_run_id(normalized_kind, inputs)
        with self.workspace_lock(root):
            pack = _BUILDERS[normalized_kind](root, run_id=normalized_run_id, payload=inputs)
        return {
            "status": "ok",
            "executor": "ai-harness",
            "provider_calls": 0,
            "pack": pack.to_dict(),
        }

    def pack_plan(self, workspace: str, kind: str, run_id: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "plan": load_plan(_workspace(workspace), run_id=run_id, kind=_kind(kind)),
        }

    def pack_task(self, workspace: str, kind: str, run_id: str, task_id: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "task": load_task(
                _workspace(workspace),
                run_id=run_id,
                kind=_kind(kind),
                task_id=task_id,
            ),
        }

    def pack_import(
        self,
        workspace: str,
        kind: str,
        run_id: str,
        result_path: str,
    ) -> dict[str, Any]:
        root = _workspace(workspace)
        normalized_kind = _kind(kind)
        with self.workspace_lock(root):
            result = _IMPORTERS[normalized_kind](
                root,
                run_id=run_id,
                result_path=result_path,
            )
        return {"status": "ok", "executor": "ai-harness", "provider_calls": 0, **result}

    def read_resource(
        self,
        resource_uri: str,
        *,
        workspace: str,
        kind: str,
        run_id: str,
        task_id: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        root = _workspace(workspace)
        normalized_kind = _kind(kind)
        if resource_uri == "paperassist://pack":
            return {"status": "ok", "plan": load_plan(root, run_id=run_id, kind=normalized_kind)}
        if resource_uri == "paperassist://task":
            if not task_id:
                raise ValueError("task resource requires task_id")
            return {
                "status": "ok",
                "task": load_task(
                    root,
                    run_id=run_id,
                    kind=normalized_kind,
                    task_id=task_id,
                ),
            }
        raise ValueError(f"Unsupported resource `{resource_uri}`")


def build_server() -> PaperAssistMcpServer:
    return PaperAssistMcpServer()


__all__ = ["PaperAssistMcpServer", "build_server"]
