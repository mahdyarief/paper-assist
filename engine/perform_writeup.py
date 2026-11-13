"""Legacy writeup entrypoint, converted to the agent-operated contract.

The previous implementation drove an in-process Aider coder through the
abstract/section/citation/refinement prompts. PaperAssist no longer owns a
language model: this module now prepares a deterministic writing pack for the
external AI harness and compiles the resulting manuscript.
"""

from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from paperassist.protected_blocks import extract_protected_blocks
from paperassist.writing_pack import (
    DEFAULT_SECTIONS,
    EXPERIMENTAL_SECTIONS,
    build_writing_pack,
    skeleton_document,
)

ORIGINAL_NUM_CITE_ROUNDS = 3
ORIGINAL_NUM_ERROR_CORRECTIONS = 2

PAPERASSIST_DEFAULT_NUM_CITE_ROUNDS = 3
PAPERASSIST_DEFAULT_NUM_ERROR_CORRECTIONS = 2
WRITEUP_CHECKPOINT_FILENAME = "writeup_checkpoint.json"
WRITEUP_CHECKPOINT_STAGE_ORDER = {
    "start": 0,
    "init": 1,
    "cite": 2,
    "refine": 3,
    "latex_fix": 4,
    "done": 5,
}
WRITEUP_CHECKPOINT_STAGE_DEFAULT = "start"


def _atomic_write_text(path: str, content: str) -> None:
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    finally:
        try:
            if osp.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _checkpoint_path(folder_name: str) -> str:
    return osp.join(folder_name, WRITEUP_CHECKPOINT_FILENAME)


def _checkpoint_snapshot_dir(folder_name: str) -> str:
    return osp.join(folder_name, "latex", "checkpoints")


def _default_writeup_checkpoint() -> dict:
    return {
        "stage": WRITEUP_CHECKPOINT_STAGE_DEFAULT,
        "current_round": 0,
        "latest_tex_file": None,
        "updated_at": None,
    }


def _normalize_checkpoint_stage(stage: object) -> str:
    if isinstance(stage, str) and stage in WRITEUP_CHECKPOINT_STAGE_ORDER:
        return stage
    return WRITEUP_CHECKPOINT_STAGE_DEFAULT


def _checkpoint_stage_rank(stage: str) -> int:
    return WRITEUP_CHECKPOINT_STAGE_ORDER.get(stage, 0)


def _load_writeup_checkpoint(folder_name: str) -> dict:
    path = _checkpoint_path(folder_name)
    if not osp.exists(path):
        return _default_writeup_checkpoint()
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[writeup][checkpoint] invalid checkpoint ignored: {exc}")
        return _default_writeup_checkpoint()

    state = _default_writeup_checkpoint()
    if isinstance(payload, dict):
        state["stage"] = _normalize_checkpoint_stage(payload.get("stage"))
        current_round = payload.get("current_round")
        if isinstance(current_round, int) and current_round >= 0:
            state["current_round"] = current_round
        latest_tex_file = payload.get("latest_tex_file")
        if isinstance(latest_tex_file, str) and latest_tex_file.strip():
            state["latest_tex_file"] = latest_tex_file.strip()
        updated_at = payload.get("updated_at")
        if isinstance(updated_at, str) and updated_at.strip():
            state["updated_at"] = updated_at.strip()
    return state


def _save_writeup_checkpoint(
    folder_name: str,
    stage: str,
    current_round: int,
    writeup_tex_file: str,
    snapshot_name: str,
) -> dict:
    normalized_stage = _normalize_checkpoint_stage(stage)
    normalized_round = max(0, int(current_round))
    snapshot_dir = _checkpoint_snapshot_dir(folder_name)
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot_path = osp.join(snapshot_dir, snapshot_name)
    shutil.copy2(writeup_tex_file, snapshot_path)
    relative_snapshot = osp.relpath(snapshot_path, folder_name)
    payload = {
        "stage": normalized_stage,
        "current_round": normalized_round,
        "latest_tex_file": relative_snapshot,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _atomic_write_text(
        _checkpoint_path(folder_name),
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return payload


def _restore_writeup_tex_from_checkpoint(
    folder_name: str, writeup_tex_file: str, state: dict
) -> bool:
    latest_tex_file = state.get("latest_tex_file")
    if not isinstance(latest_tex_file, str) or not latest_tex_file.strip():
        return False
    snapshot_path = osp.join(folder_name, latest_tex_file)
    if not osp.exists(snapshot_path):
        print(f"[writeup][checkpoint] snapshot missing: {snapshot_path}")
        return False
    shutil.copy2(snapshot_path, writeup_tex_file)
    return True


def _remove_writeup_checkpoint(folder_name: str) -> None:
    path = _checkpoint_path(folder_name)
    if osp.exists(path):
        os.remove(path)


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _deprecated_env_override(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    print(
        f"[deprecated] {name} is deprecated; use CLI arguments or workspace_config.json instead."
    )
    return raw


def _blocked_citation_keys() -> set[str]:
    raw = os.getenv("WRITEUP_BLOCKED_CITATION_KEYS", "").strip()
    if not raw:
        return set()
    return {key.strip() for key in raw.split(",") if key.strip()}


def _sanitize_author_block(tex_text: str) -> str:
    """Normalize author / header lines that generated drafts sometimes inject."""

    direct_replacements = {
        r"\author{GPT-4o \& Claude\\": r"\author{Anonymous Authors\\",
        r"\author{LLM\\": r"\author{Anonymous Authors\\",
        r"Department of Computer Science\\": "",
        r"University of LLMs\\": r"Affiliation withheld for review\\",
    }
    for src, dst in direct_replacements.items():
        tex_text = tex_text.replace(src, dst)

    tex_text = re.sub(
        r"\n?This work was generated by\s*\\textsc\{[^}]+\}(?:\s*\\citep\{[^}]+\})?\.?\n?",
        "\n",
        tex_text,
        flags=re.IGNORECASE,
    )
    tex_text = re.sub(
        r"(Affiliation withheld for review\\\\)\s*\n\s*(Affiliation withheld for review\\\\)",
        r"\1",
        tex_text,
    )
    return tex_text


def _sanitize_template_tex_contents(tex_text: str) -> str:
    tex_text = _sanitize_author_block(tex_text)
    blocked_keys = _blocked_citation_keys()
    if not blocked_keys:
        return tex_text

    for key in blocked_keys:
        tex_text = re.sub(
            rf"@\w+\s*\{{\s*{re.escape(key)}\s*,.*?\n\}}\s*",
            "",
            tex_text,
            flags=re.DOTALL,
        )

    def _rewrite_cites(match: re.Match) -> str:
        command = match.group(1)
        keys = [key.strip() for key in match.group(2).split(",")]
        keys = [key for key in keys if key and key not in blocked_keys]
        if not keys:
            return ""
        return f"{command}{{{', '.join(keys)}}}"

    return re.sub(r"(\\cite[a-zA-Z*]*)\{([^}]*)\}", _rewrite_cites, tex_text)


def _sanitize_template_tex_file(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        tex_text = f.read()
    sanitized = _sanitize_template_tex_contents(tex_text)
    if sanitized != tex_text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(sanitized)


_LATEX_FIGURE_EXTENSIONS = (".png", ".pdf", ".jpg", ".jpeg", ".webp", ".svg", ".eps")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LATEX_TEMPLATE_DIR = _REPO_ROOT / "templates" / "paper_writer" / "latex"
_LATEX_SUPPORT_FILES = ("ieeecolor.cls", "generic.sty", "TII.eps")


def _extract_external_bibliography_targets(tex_text: str) -> list[str]:
    matches = re.findall(r"\\bibliography\{([^}]*)\}", tex_text)
    targets: list[str] = []
    for item in matches:
        for name in item.split(","):
            cleaned = name.strip()
            if cleaned:
                targets.append(cleaned)
    return targets


def _resolve_external_bib_files(cwd: str, tex_text: str) -> list[str]:
    resolved: list[str] = []
    seen = set()
    for target in _extract_external_bibliography_targets(tex_text):
        candidate = target if target.endswith(".bib") else f"{target}.bib"
        path = candidate if osp.isabs(candidate) else osp.join(cwd, candidate)
        normalized = osp.abspath(path)
        if osp.exists(normalized) and normalized not in seen:
            seen.add(normalized)
            resolved.append(normalized)
    return resolved


def _load_available_bibliography_text(cwd: str, tex_text: str) -> tuple[str | None, bool]:
    embedded = _extract_embedded_references_bib(tex_text)
    if embedded is not None:
        return embedded, True
    if _has_inline_thebibliography(tex_text):
        return None, False
    external_files = _resolve_external_bib_files(cwd, tex_text)
    if external_files:
        contents: list[str] = []
        for path in external_files:
            with open(path, encoding="utf-8") as f:
                contents.append(f.read())
        return "\n".join(contents), True
    return None, False


def _extract_embedded_references_bib(tex_text: str) -> str | None:
    match = re.search(
        r"\\begin{filecontents}{references.bib}(.*?)\\end{filecontents}",
        tex_text,
        re.DOTALL,
    )
    if match is None:
        return None
    return match.group(1)


def _has_inline_thebibliography(tex_text: str) -> bool:
    return re.search(r"\\begin{thebibliography}", tex_text) is not None


def _list_available_figures(cwd: str) -> list[str]:
    available: list[str] = []
    for root, _, files in os.walk(cwd):
        for filename in files:
            if Path(filename).suffix.lower() not in _LATEX_FIGURE_EXTENSIONS:
                continue
            available.append(osp.relpath(osp.join(root, filename), cwd))
    return sorted(available)


def _figure_exists(cwd: str, figure: str) -> bool:
    candidate = figure.strip()
    if not candidate:
        return False

    candidates = [candidate]
    _, ext = osp.splitext(candidate)
    if not ext:
        candidates.extend(f"{candidate}{suffix}" for suffix in _LATEX_FIGURE_EXTENSIONS)

    for item in candidates:
        path = item if osp.isabs(item) else osp.join(cwd, item)
        if osp.exists(path):
            return True
    return False


def _ensure_latex_support_files(cwd: str) -> None:
    target_dir = Path(cwd)
    for filename in _LATEX_SUPPORT_FILES:
        target = target_dir / filename
        if target.exists():
            continue
        for source_dir in (_DEFAULT_LATEX_TEMPLATE_DIR,):
            source = source_dir / filename
            if source.exists():
                shutil.copy2(source, target)
                break


@dataclass
class ChktexResult:
    errors: list[str]
    warnings: list[str]
    raw_output: str


def run_chktex(latex_dir: str, tex_file: str) -> ChktexResult:
    if shutil.which("chktex") is None:
        return ChktexResult(
            errors=[],
            warnings=[],
            raw_output="chktex is not installed; lint step skipped",
        )
    proc = subprocess.run(
        ["chktex", tex_file, "-q", "-v0", "-f", "%k|%n|%l|%c|%m\n"],
        cwd=latex_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    raw_output = proc.stdout or ""
    errors: list[str] = []
    warnings: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("|", 4)
        if len(parts) == 5:
            kind, msg_id, row, col, message = parts
            rendered = f"{kind} {msg_id} at {row}:{col}: {message}".strip()
            lowered = kind.lower()
            if lowered.startswith("error"):
                errors.append(rendered)
            else:
                warnings.append(rendered)
            continue
        lowered = stripped.lower()
        if lowered.startswith("error"):
            errors.append(stripped)
        else:
            warnings.append(stripped)
    return ChktexResult(errors=errors, warnings=warnings, raw_output=raw_output)


@dataclass
class WriteupDiagnostics:
    """Deterministic findings the AI harness must fix itself."""

    findings: list[dict[str, Any]] = field(default_factory=list)

    def add(self, kind: str, message: str, **detail: Any) -> None:
        entry = {"kind": kind, "message": message}
        entry.update({key: value for key, value in detail.items() if value is not None})
        self.findings.append(entry)

    def write(self, latex_dir: str) -> str | None:
        if not self.findings:
            return None
        path = Path(latex_dir) / "writing_diagnostics.json"
        path.write_text(
            json.dumps(self.findings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return str(path)


# COMPILE LATEX
def generate_latex(
    folder_name,
    pdf_file,
    timeout=30,
    num_error_corrections=PAPERASSIST_DEFAULT_NUM_ERROR_CORRECTIONS,
    checkpoint_enabled: bool = False,
    checkpoint_resume_round: int = 0,
    skip_chktex_fix: bool = False,
    diagnostics: WriteupDiagnostics | None = None,
):
    """Check and compile the manuscript; report problems instead of fixing them.

    The AI harness owns prose edits. This function only detects issues
    (unknown cites, missing/duplicate figures, duplicate sections, chktex
    errors) and compiles the PDF.
    """

    findings = diagnostics or WriteupDiagnostics()
    folder = osp.abspath(folder_name)
    cwd = osp.join(folder, "latex")
    _ensure_latex_support_files(cwd)
    writeup_file = osp.join(cwd, "template.tex")
    _sanitize_template_tex_file(writeup_file)

    with open(writeup_file, encoding="utf-8") as f:
        tex_text = f.read()
    cites = re.findall(r"\\cite[a-z]*{([^}]*)", tex_text)
    bib_text, _use_bibtex = _load_available_bibliography_text(cwd, tex_text)
    if bib_text is None and not _has_inline_thebibliography(tex_text):
        print("No references.bib, external bibliography, or inline thebibliography found in template.tex")
        return False
    if bib_text is not None:
        cites = [cite.strip() for item in cites for cite in item.split(",")]
        for cite in cites:
            if cite and cite not in bib_text:
                print(f"Reference {cite} not found in references.")
                findings.add(
                    "missing_citation",
                    f"Reference {cite} not found in references.bib",
                    citation=cite,
                )

    with open(writeup_file, encoding="utf-8") as f:
        tex_text = f.read()
    referenced_figs = re.findall(r"\\includegraphics.*?{(.*?)}", tex_text)
    available_figs = _list_available_figures(cwd)
    for figure in referenced_figs:
        if not _figure_exists(cwd, figure):
            print(f"Figure {figure} not found in directory.")
            findings.add(
                "missing_figure",
                f"Figure {figure} not found in the directory",
                figure=figure,
                available=available_figs,
            )

    duplicates = {x for x in referenced_figs if referenced_figs.count(x) > 1}
    for dup in sorted(duplicates):
        print(f"Duplicate figure found: {dup}.")
        findings.add("duplicate_figure", f"Duplicate figure: {dup}", figure=dup)

    sections = re.findall(r"\\section{([^}]*)}", tex_text)
    section_duplicates = {x for x in sections if sections.count(x) > 1}
    for dup in sorted(section_duplicates):
        print(f"Duplicate section header found: {dup}")
        findings.add(
            "duplicate_section",
            f"Duplicate section header: {dup}",
            section=dup,
        )

    if skip_chktex_fix:
        print("[writeup] skipping chktex auto-fix in existing manuscript mode.")
        chktex_result = run_chktex(cwd, writeup_file)
        if chktex_result.errors:
            error_path = Path(cwd) / "chktex_errors.txt"
            error_path.write_text("\n".join(chktex_result.errors) + "\n", encoding="utf-8")
            findings.write(cwd)
            raise RuntimeError(f"chktex blocking errors: {error_path}")
        if chktex_result.warnings:
            warning_path = Path(cwd) / "chktex_warnings.txt"
            warning_path.write_text("\n".join(chktex_result.warnings) + "\n", encoding="utf-8")
    else:
        for i in range(num_error_corrections):
            round_idx = i + 1
            if checkpoint_enabled and round_idx <= max(0, checkpoint_resume_round):
                print(f"[writeup][checkpoint] skipping latex_fix round {round_idx}")
                continue
            chktex_result = run_chktex(cwd, writeup_file)
            if chktex_result.errors:
                error_path = Path(cwd) / "chktex_errors.txt"
                error_path.write_text("\n".join(chktex_result.errors) + "\n", encoding="utf-8")
                findings.write(cwd)
                raise RuntimeError(f"chktex blocking errors: {error_path}")
            if chktex_result.warnings:
                warning_path = Path(cwd) / "chktex_warnings.txt"
                warning_path.write_text("\n".join(chktex_result.warnings) + "\n", encoding="utf-8")
            break
    findings.write(cwd)
    with open(writeup_file, encoding="utf-8") as f:
        tex_text = f.read()
    use_bibtex = _load_available_bibliography_text(cwd, tex_text)[1]
    return compile_latex(cwd, pdf_file, timeout=timeout, use_bibtex=use_bibtex)


def compile_latex(cwd, pdf_file, timeout=30, use_bibtex: bool = True):
    print("GENERATING LATEX")
    compile_log_path = Path(cwd) / "compile_output.log"
    compile_chunks: list[str] = []

    commands = [["pdflatex", "-interaction=nonstopmode", "template.tex"]]
    if use_bibtex:
        commands.append(["bibtex", "template"])
    commands.extend(
        [
            ["pdflatex", "-interaction=nonstopmode", "template.tex"],
            ["pdflatex", "-interaction=nonstopmode", "template.tex"],
        ]
    )

    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            compile_chunks.append(
                "## Command: {cmd}\n\n### STDOUT\n{stdout}\n\n### STDERR\n{stderr}\n".format(
                    cmd=" ".join(command),
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
            print("Standard Output:\n", result.stdout)
            print("Standard Error:\n", result.stderr)
        except subprocess.TimeoutExpired:
            print(f"Latex timed out after {timeout} seconds")
            compile_chunks.append(f"## Command timed out after {timeout}s: {' '.join(command)}\n")
        except subprocess.CalledProcessError as e:
            print(f"Error running command {' '.join(command)}: {e}")
            compile_chunks.append(f"## Command error: {' '.join(command)} -> {e}\n")

    compile_log_path.write_text("\n".join(compile_chunks), encoding="utf-8")

    print("FINISHED GENERATING LATEX")

    try:
        shutil.move(osp.join(cwd, "template.pdf"), pdf_file)
        return True
    except FileNotFoundError:
        print("Failed to rename PDF.")
        return False


def build_idea_writing_payload(
    idea: dict,
    *,
    folder_name: str,
    sections: list[str] | None = None,
    literature_engine: str = "openalex",
    skip_chktex_fix: bool | None = None,
) -> dict[str, Any]:
    """Translate legacy idea metadata into a writing pack payload."""

    writeup_file = osp.join(folder_name, "latex", "template.tex")
    bibliography = osp.join(folder_name, "latex", "references.bib")
    if not osp.exists(bibliography):
        bibliography = osp.join(folder_name, "references.bib")
    payload: dict[str, Any] = {
        "title": str(idea.get("Title") or idea.get("Name") or "").strip(),
        "topic": str(idea.get("Topic") or idea.get("Experiment") or "").strip(),
        "instructions": str(idea.get("Experiment") or "").strip(),
        "main_tex": writeup_file,
        "bibliography_path": bibliography,
        "literature_engine": literature_engine,
        "cite_rounds": _env_int("WRITEUP_CITE_ROUNDS", PAPERASSIST_DEFAULT_NUM_CITE_ROUNDS),
    }
    selected = sections
    if selected is None and _env_bool("WRITEUP_SKIP_EXPERIMENTAL_SECTIONS", "0"):
        selected = [
            section for section in DEFAULT_SECTIONS if section not in EXPERIMENTAL_SECTIONS
        ]
        payload["skip_experimental_sections"] = True
    if selected is not None:
        payload["sections"] = selected
    if skip_chktex_fix is not None:
        payload["skip_chktex_fix"] = skip_chktex_fix
    return payload


# PERFORM WRITEUP
def perform_writeup(
    idea,
    folder_name,
    *,
    existing_draft_path: str | None = None,
    skip_chktex_fix: bool | None = None,
    sections: list[str] | None = None,
    literature_engine: str = "openalex",
    compile_pdf: bool = True,
) -> dict[str, Any]:
    """Prepare the writing pack and compile; the AI harness writes the prose."""

    if skip_chktex_fix is None:
        deprecated = _deprecated_env_override("WRITEUP_SKIP_CHKTEX_FIX")
        if deprecated is not None:
            skip_chktex_fix = _env_bool("WRITEUP_SKIP_CHKTEX_FIX", "0")
        else:
            skip_chktex_fix = existing_draft_path is not None
    checkpoint_enabled = _env_bool("WRITEUP_ENABLE_CHECKPOINT", "1")
    reset_checkpoint = _env_bool("WRITEUP_RESET_CHECKPOINT", "0")

    writeup_tex_file = osp.join(folder_name, "latex", "template.tex")
    Path(writeup_tex_file).parent.mkdir(parents=True, exist_ok=True)
    final_pdf_file = f"{folder_name}/{idea['Name']}.pdf"

    if not osp.exists(writeup_tex_file):
        Path(writeup_tex_file).write_text(
            skeleton_document(str(idea.get("Title") or idea.get("Name") or "")),
            encoding="utf-8",
        )
    if existing_draft_path:
        source_draft = Path(existing_draft_path).expanduser().resolve()
        target_draft = Path(writeup_tex_file).resolve()
        if not source_draft.exists():
            raise FileNotFoundError(f"existing draft not found: {source_draft}")
        if source_draft != target_draft:
            shutil.copy2(source_draft, target_draft)
    _sanitize_template_tex_file(writeup_tex_file)

    if checkpoint_enabled:
        if reset_checkpoint:
            _remove_writeup_checkpoint(folder_name)
            print("[writeup][checkpoint] reset requested; previous checkpoint cleared.")
        checkpoint_state = _load_writeup_checkpoint(folder_name)
        if _checkpoint_stage_rank(checkpoint_state["stage"]) > _checkpoint_stage_rank("start"):
            _restore_writeup_tex_from_checkpoint(
                folder_name, writeup_tex_file, checkpoint_state
            )

    payload = build_idea_writing_payload(
        idea,
        folder_name=folder_name,
        sections=sections,
        literature_engine=literature_engine,
        skip_chktex_fix=skip_chktex_fix,
    )
    protected_blocks = extract_protected_blocks(
        Path(writeup_tex_file).read_text(encoding="utf-8")
    )
    run_id = Path(folder_name).name or str(idea.get("Name") or "writeup")
    pack = build_writing_pack(
        folder_name,
        run_id=run_id,
        payload=payload,
        target_path=osp.relpath(writeup_tex_file, folder_name).replace("\\", "/"),
        original_text=Path(writeup_tex_file).read_text(encoding="utf-8"),
    )
    print(f"[writeup] writing pack ready: {pack.plan_path}")
    print(
        f"[writeup] {len(pack.tasks)} task(s) for the AI harness; "
        f"protected blocks: {len(protected_blocks)}"
    )

    latex_ok = False
    diagnostics = WriteupDiagnostics()
    if compile_pdf:
        if checkpoint_enabled:
            _save_writeup_checkpoint(
                folder_name,
                stage="latex_fix",
                current_round=0,
                writeup_tex_file=writeup_tex_file,
                snapshot_name="template_pack.tex",
            )
        latex_ok = generate_latex(
            folder_name,
            final_pdf_file,
            num_error_corrections=_env_int(
                "WRITEUP_LATEX_FIX_ROUNDS", PAPERASSIST_DEFAULT_NUM_ERROR_CORRECTIONS
            ),
            checkpoint_enabled=checkpoint_enabled,
            skip_chktex_fix=bool(skip_chktex_fix),
            diagnostics=diagnostics,
        )
        _sanitize_template_tex_file(writeup_tex_file)
        if checkpoint_enabled and latex_ok:
            _save_writeup_checkpoint(
                folder_name,
                stage="done",
                current_round=0,
                writeup_tex_file=writeup_tex_file,
                snapshot_name="template_done.tex",
            )
        elif checkpoint_enabled:
            print("[writeup][checkpoint] latex generation incomplete, checkpoint remains resumable.")

    return {
        "schema": "paperassist.writeup-result/v1",
        "writer": "ai-harness",
        "provider_calls": 0,
        "run_id": run_id,
        "pack": pack.to_dict(),
        "latex_ok": latex_ok,
        "pdf_path": final_pdf_file if latex_ok else None,
        "diagnostics": diagnostics.findings,
        "protected_block_count": len(protected_blocks),
        "next_action": (
            "Execute the pack tasks with the AI harness, then run "
            f"`paperassist write --workspace {folder_name} --run-id {run_id} "
            "--import latex/template.tex`."
        ),
        "import_command": (
            f"paperassist write --workspace {folder_name} --run-id {run_id} "
            "--import latex/template.tex"
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare the agent-operated writeup")
    parser.add_argument("--folder", type=str, required=True)
    parser.add_argument("--no-writing", action="store_true", help="Only compile the manuscript")
    parser.add_argument(
        "--engine",
        type=str,
        default="openalex",
        choices=["semanticscholar", "openalex"],
        help="Scholar engine recorded for the harness citation tasks.",
    )
    parser.add_argument("--existing-draft", default=None)
    parser.add_argument("--skip-chktex-fix", dest="skip_chktex_fix", action="store_true")
    parser.add_argument("--no-skip-chktex-fix", dest="skip_chktex_fix", action="store_false")
    parser.set_defaults(skip_chktex_fix=None)
    args = parser.parse_args()
    folder_name = args.folder
    idea_name = osp.basename(folder_name)
    ideas_file = osp.join(folder_name, "ideas.json")
    idea: dict[str, Any] = {"Name": idea_name, "Title": idea_name}
    if osp.exists(ideas_file):
        with open(ideas_file, encoding="utf-8") as f:
            ideas = json.load(f)
        for candidate in ideas:
            if candidate.get("Name") in idea_name:
                idea = candidate
                break
    if args.no_writing:
        ok = generate_latex(
            folder_name,
            f"{folder_name}/test.pdf",
            skip_chktex_fix=bool(args.skip_chktex_fix),
        )
        print(json.dumps({"latex_ok": ok}, indent=2))
    else:
        try:
            result = perform_writeup(
                idea,
                folder_name,
                existing_draft_path=args.existing_draft,
                skip_chktex_fix=args.skip_chktex_fix,
                literature_engine=args.engine,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"Failed to perform writeup: {e}")
