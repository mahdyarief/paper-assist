"""Tests for depth policy, context-aware tasks, and pack integration."""

from __future__ import annotations

import json

import pytest

from paperassist.context_inventory import inventory_from_payload
from paperassist.writing_pack import (
    DEFAULT_DEPTH,
    DEPTH_PROFILES,
    build_tasks,
    build_writing_pack,
)

MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "% PAPERASSIST-PROTECTED-EXPERIMENT-START\n"
    "\\section{Results}\n"
    "A measured value is reported here.\n"
    "% PAPERASSIST-PROTECTED-EXPERIMENT-END\n"
    "\\section{Introduction}\n"
    "Prior work exists \\cite{k1}.\n"
    "\\end{document}\n"
)

BIB = "@article{k1,\n author={A.},\n title={T},\n year={2020}\n}\n"


def make_workspace(root):
    (root / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (root / "refs.bib").write_text(BIB, encoding="utf-8")
    (root / "rows.json").write_text(
        json.dumps([{"id": 1, "value": 0.5}, {"id": 2, "value": 0.7}]),
        encoding="utf-8",
    )
    (root / "notes.md").write_text("# Context\n\nSome material.\n", encoding="utf-8")


def task_ids(tasks):
    return [task.task_id for task in tasks]


def test_depth_profiles_are_ordered():
    shallow = DEPTH_PROFILES["shallow"]
    standard = DEPTH_PROFILES["standard"]
    deep = DEPTH_PROFILES["deep"]
    assert (
        shallow["min_words_per_section"]
        < standard["min_words_per_section"]
        < deep["min_words_per_section"]
    )
    assert shallow["require_evidence_tasks"] is False
    assert deep["require_evidence_tasks"] is True


def test_default_depth_is_standard():
    tasks = build_tasks(
        {}, target="main.tex", allowed_keys=("k1",), reference_count=1
    )
    assert tasks
    assert DEFAULT_DEPTH == "standard"


def test_invalid_depth_falls_back_to_standard():
    tasks = build_tasks(
        {"depth": "nonsense", "phases": ["init", "provenance"]},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
    )
    assert "provenance-locators" in task_ids(tasks)


def test_deep_depth_adds_evidence_and_provenance_tasks(tmp_path):
    make_workspace(tmp_path)
    inventory = inventory_from_payload(
        tmp_path, {"context_paths": ["rows.json", "notes.md"]}
    )
    tasks = build_tasks(
        {"depth": "deep", "phases": ["init", "evidence", "provenance"]},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
        context=inventory,
    )
    ids = task_ids(tasks)
    assert "evidence-reconciliation" in ids
    assert "provenance-locators" in ids
    evidence = next(task for task in tasks if task.task_id == "evidence-reconciliation")
    assert "records" in evidence.instructions
    assert "denominator" in evidence.instructions


def test_shallow_depth_skips_evidence_and_provenance(tmp_path):
    make_workspace(tmp_path)
    inventory = inventory_from_payload(tmp_path, {"context_paths": ["rows.json"]})
    tasks = build_tasks(
        {"depth": "shallow", "phases": ["init", "evidence", "provenance"]},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
        context=inventory,
    )
    ids = task_ids(tasks)
    assert "evidence-reconciliation" not in ids
    assert "provenance-locators" not in ids


def test_evidence_task_requires_data_sources(tmp_path):
    make_workspace(tmp_path)
    inventory = inventory_from_payload(tmp_path, {"context_paths": ["notes.md"]})
    tasks = build_tasks(
        {"depth": "deep", "phases": ["evidence"]},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
        context=inventory,
    )
    assert "evidence-reconciliation" not in task_ids(tasks)


def test_section_instructions_include_depth_target(tmp_path):
    make_workspace(tmp_path)
    inventory = inventory_from_payload(
        tmp_path, {"context_paths": ["rows.json", "notes.md"]}
    )
    tasks = build_tasks(
        {"depth": "deep", "phases": ["init"]},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
        context=inventory,
    )
    intro = next(task for task in tasks if task.section == "Introduction")
    assert "at least 900 words" in intro.instructions
    assert "tabular source" in intro.instructions
    assert "UNTRUSTED" in intro.instructions


def test_em_dash_is_banned_in_generated_instructions():
    tasks = build_tasks(
        {"phases": ["init"]},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
    )
    assert tasks
    for task in tasks:
        assert "never use an em dash" in task.instructions


def test_em_dash_can_be_allowed_explicitly():
    tasks = build_tasks(
        {"phases": ["init"], "allow_em_dash": True},
        target="main.tex",
        allowed_keys=("k1",),
        reference_count=1,
    )
    assert tasks
    for task in tasks:
        assert "never use an em dash" not in task.instructions


def test_pack_writes_context_artifacts(tmp_path):
    make_workspace(tmp_path)
    pack = build_writing_pack(
        tmp_path,
        run_id="run-1",
        payload={
            "depth": "deep",
            "context_paths": ["rows.json", "notes.md"],
            "phases": ["init", "evidence", "provenance"],
        },
        target_path="main.tex",
        original_text=MAIN_TEX,
    )
    data = pack.to_dict()
    assert data["depth"] == "deep"
    assert data["context_path"] is not None
    assert data["context_brief_path"] is not None
    assert data["context_signals"]["data_sources"] == 1
    assert data["depth_profile"]["require_evidence_tasks"] is True
    assert (tmp_path / data["context_path"]).is_file()
    assert "UNTRUSTED" in (tmp_path / data["context_brief_path"]).read_text(
        encoding="utf-8"
    )


def test_pack_without_context_has_no_context_artifacts(tmp_path):
    make_workspace(tmp_path)
    pack = build_writing_pack(
        tmp_path,
        run_id="run-2",
        payload={"depth": "standard", "phases": ["init"]},
        target_path="main.tex",
        original_text=MAIN_TEX,
    )
    data = pack.to_dict()
    assert data["context_path"] is None
    assert data["context_brief_path"] is None
    assert data["context_signals"] == {}


def test_plan_records_depth_profile(tmp_path):
    make_workspace(tmp_path)
    pack = build_writing_pack(
        tmp_path,
        run_id="run-3",
        payload={"depth": "shallow", "phases": ["init"]},
        target_path="main.tex",
        original_text=MAIN_TEX,
    )
    plan = json.loads((tmp_path / pack.plan_path).read_text(encoding="utf-8"))
    assert plan["depth"] == "shallow"
    assert plan["depth_profile"]["min_words_per_section"] == 250


def test_min_words_override(tmp_path):
    make_workspace(tmp_path)
    pack = build_writing_pack(
        tmp_path,
        run_id="run-4",
        payload={
            "depth": "standard",
            "min_words_per_section": 1200,
            "phases": ["init"],
        },
        target_path="main.tex",
        original_text=MAIN_TEX,
    )
    assert pack.to_dict()["depth_profile"]["min_words_per_section"] == 1200


def test_context_paths_must_stay_in_workspace(tmp_path):
    make_workspace(tmp_path)
    outside = tmp_path.parent / "leak.md"
    outside.write_text("secret\n", encoding="utf-8")
    with pytest.raises(Exception):
        build_writing_pack(
            tmp_path,
            run_id="run-5",
            payload={"context_paths": [str(outside)]},
            target_path="main.tex",
            original_text=MAIN_TEX,
        )
