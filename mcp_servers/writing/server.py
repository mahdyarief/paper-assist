from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp_servers.base import BasePaperAssistMcpServer, ResourceSpec, ToolSpec
from paperassist.path_safety import safe_mkdir
from paperassist.scientific_memory import ScientificMemory
from paperassist.writing import WritingEngine
from paperassist.writing_pack import (
    load_writing_plan,
    load_writing_task,
)
from paperassist.writing_patch import apply_patch

_WRITING_KEYS = (
    "abstract",
    "bibliography_path",
    "cite_rounds",
    "document_path",
    "instructions",
    "main_tex",
    "main_tex_path",
    "outline",
    "phases",
    "sections",
    "title",
    "topic",
)


def _workspace_path(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve(strict=True)


def _memory(workspace: Path) -> ScientificMemory:
    state_dir = safe_mkdir(workspace / ".paperassist", anchor=workspace)
    return ScientificMemory(state_dir / "paperassist.db", trusted_root=workspace)


def _default_run_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"mcp-{digest}"


class WritingMcpServer(BasePaperAssistMcpServer):
    """Expose PaperAssist writing as agent-executable tasks.

    The MCP client (OpenClaude, Claude Code, Freebuff, a human) is the single
    language model. These tools never call a model provider.
    """

    server_name = "writing"

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="writing_pack",
                description=(
                    "Build a deterministic writing pack (plan, brief, tasks, "
                    "allowed citations) for the AI harness to execute."
                ),
                requires_workspace_lock=True,
            ),
            ToolSpec(name="writing_plan", description="Read a writing pack plan."),
            ToolSpec(
                name="writing_task",
                description="Read one writing task from a pack.",
            ),
            ToolSpec(
                name="writing_import",
                description=(
                    "Verify a harness-produced .tex document against the writing "
                    "gates and register it as a draft artifact."
                ),
                requires_workspace_lock=True,
            ),
            ToolSpec(
                name="writing_patch",
                description=(
                    "Apply an agent-supplied replacement for one unique anchor "
                    "with all protected-block and citation gates enforced."
                ),
                requires_workspace_lock=True,
            ),
        ]

    def resources(self) -> list[ResourceSpec]:
        return [
            ResourceSpec(
                uri="writing://plan",
                description="Serialized writing pack plan for a workspace run.",
            ),
            ResourceSpec(
                uri="writing://brief",
                description="Agent-facing writing brief for a workspace run.",
            ),
        ]

    def writing_pack(
        self,
        workspace: str,
        run_id: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        root = _workspace_path(workspace)
        inputs = {
            key: value
            for key, value in payload.items()
            if key in _WRITING_KEYS and value not in (None, "", [], ())
        }
        normalized_run_id = run_id or _default_run_id(inputs)
        with self.workspace_lock(root):
            pack = WritingEngine(root, memory=_memory(root)).scaffold(
                run_id=normalized_run_id,
                payload=inputs,
            )
        return {
            "status": "ok",
            "writer": "ai-harness",
            "provider_calls": 0,
            "pack": pack.to_dict(),
        }

    def writing_plan(self, workspace: str, run_id: str) -> dict[str, Any]:
        root = _workspace_path(workspace)
        return {
            "status": "ok",
            "plan": load_writing_plan(root, run_id=run_id),
        }

    def writing_task(
        self,
        workspace: str,
        run_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        root = _workspace_path(workspace)
        return {
            "status": "ok",
            "task": load_writing_task(root, run_id=run_id, task_id=task_id),
        }

    def writing_import(
        self,
        workspace: str,
        run_id: str,
        draft_path: str | None = None,
        draft_text: str | None = None,
        plan_run_id: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        root = _workspace_path(workspace)
        plan = load_writing_plan(root, run_id=plan_run_id or run_id)
        inputs: dict[str, Any] = {
            key: value
            for key, value in dict(plan.get("inputs") or {}).items()
            if key in _WRITING_KEYS
        }
        inputs.update(
            {
                key: value
                for key, value in payload.items()
                if key in _WRITING_KEYS and value not in (None, "", [], ())
            }
        )
        inputs["writing_pack_run_id"] = plan_run_id or run_id
        with self.workspace_lock(root):
            result = WritingEngine(root, memory=_memory(root)).import_draft(
                run_id=run_id,
                payload=inputs,
                draft_text=draft_text,
                draft_path=draft_path,
            )
        return {"status": "ok", "draft": result.to_dict()}

    def writing_patch(
        self,
        workspace: str,
        run_id: str,
        target: str,
        anchor: str,
        replacement: str | None = None,
        replacement_path: str | None = None,
        source_sha256: str | None = None,
        instructions: str = "",
        allow_line_range: list[int] | None = None,
    ) -> dict[str, Any]:
        root = _workspace_path(workspace)
        if bool(replacement) == bool(replacement_path):
            raise ValueError(
                "provide exactly one of replacement or replacement_path"
            )
        text = replacement
        if replacement_path:
            candidate = root / replacement_path
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError("replacement_path must be a regular workspace file")
            text = candidate.read_text(encoding="utf-8")
        line_range: tuple[int, int] | None = None
        if allow_line_range:
            if len(allow_line_range) != 2:
                raise ValueError("allow_line_range must be [start, end]")
            line_range = (int(allow_line_range[0]), int(allow_line_range[1]))
        with self.workspace_lock(root):
            result = apply_patch(
                root,
                memory=_memory(root),
                run_id=run_id,
                target=target,
                source_sha256=str(source_sha256 or ""),
                anchor=anchor,
                replacement=str(text or ""),
                instructions=instructions,
                allow_line_range=line_range,
            )
        return {"status": "ok", "patch": result.to_dict()}

    def read_resource(self, resource_uri: str, **payload: Any) -> dict[str, Any]:
        root = _workspace_path(str(payload["workspace"]))
        run_id = str(payload["run_id"])
        if resource_uri == "writing://plan":
            return {
                "server": self.server_name,
                "resource": resource_uri,
                "plan": load_writing_plan(root, run_id=run_id),
            }
        if resource_uri == "writing://brief":
            plan = load_writing_plan(root, run_id=run_id)
            brief = (root / str(plan["brief_path"])).read_text(encoding="utf-8")
            return {
                "server": self.server_name,
                "resource": resource_uri,
                "brief": brief,
            }
        return super().read_resource(resource_uri, **payload)


def build_server() -> WritingMcpServer:
    return WritingMcpServer()
