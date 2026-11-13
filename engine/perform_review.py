"""Deterministic review helpers.

Peer review used to be an in-process LLM call. PaperAssist now scaffolds a
review pack (``paperassist.agent_packs.build_review_pack``) that the external AI
harness executes; this module keeps only the deterministic pieces: reading the
manuscript and turning an accepted review into revision tasks.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_paper(pdf_path, num_pages=None, min_size=100):
    """Extract text from a PDF.

    Imported lazily so the deterministic core can run without the PDF stack.
    """
    import pymupdf
    import pymupdf4llm
    from pypdf import PdfReader

    try:
        if num_pages is None:
            text = pymupdf4llm.to_markdown(pdf_path)
        else:
            reader = PdfReader(pdf_path)
            min_pages = min(len(reader.pages), num_pages)
            text = pymupdf4llm.to_markdown(pdf_path, pages=list(range(min_pages)))
        if len(text) < min_size:
            raise Exception("Text too short")
    except Exception as e:
        print(f"Error with pymupdf4llm, falling back to pymupdf: {e}")
        try:
            doc = pymupdf.open(pdf_path)  # open a document
            if num_pages:
                doc = doc[:num_pages]
            text = ""
            for page in doc:  # iterate the document pages
                text = text + page.get_text()  # get plain text encoded as UTF-8
            if len(text) < min_size:
                raise Exception("Text too short")
        except Exception as e:
            print(f"Error with pymupdf, falling back to pypdf: {e}")
            reader = PdfReader(pdf_path)
            if num_pages is None:
                text = "".join(page.extract_text() for page in reader.pages)
            else:
                text = "".join(page.extract_text() for page in reader.pages[:num_pages])
            if len(text) < min_size:
                raise Exception("Text too short") from e

    return text


def load_review(path):
    with open(path, encoding="utf-8") as json_file:
        loaded = json.load(json_file)
    return loaded["review"]


def perform_improvement(review, folder_name: str) -> dict:
    """Turn a harness-produced review into ordered revision tasks.

    PaperAssist does not edit the manuscript itself: it records exactly which
    review points must be addressed and how the result is verified.
    """
    root = Path(folder_name).expanduser().resolve()
    target = root / ".paperassist" / "revision"
    target.mkdir(parents=True, exist_ok=True)

    tasks: list[dict] = []
    for field, prefix, priority in (
        ("Weaknesses", "Address this weakness", "high"),
        ("Questions", "Clarify this reviewer question", "medium"),
        ("Limitations", "Strengthen the stated limitation", "low"),
    ):
        raw = review.get(field) if isinstance(review, dict) else None
        items = raw if isinstance(raw, list) else ([raw] if raw else [])
        for index, item in enumerate(items, start=1):
            tasks.append(
                {
                    "task_id": f"{field.lower()}-{index}",
                    "source": field,
                    "priority": priority,
                    "instructions": (
                        f"{prefix}: {item}\n\n"
                        "Edit only non-experimental prose. Do not invent results, "
                        "datasets, or citations. Preserve every PAPERASSIST protected "
                        "experiment block byte-for-byte."
                    ),
                }
            )
    payload = {
        "schema": "paperassist.revision-tasks/v1",
        "executor": "ai-harness",
        "provider_calls": 0,
        "target": "latex/template.tex",
        "review": review,
        "tasks": tasks,
        "acceptance": [
            "The revised draft keeps the same protected experiment blocks.",
            "No new numeric claims or citations are introduced.",
            "Every weakness/question above is answered or explicitly scoped out.",
        ],
        "next_action": (
            "Apply the tasks with the AI harness, then import with "
            f"`paperassist write --workspace {root} --import latex/template.tex`."
        ),
    }
    (target / "review-revision.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "review-revision.md").write_text(
        "# Review-driven revision tasks\n\n"
        + "\n".join(
            f"{index}. **{task['task_id']}** — {task['instructions']}\n"
            for index, task in enumerate(tasks, start=1)
        )
        + "",
        encoding="utf-8",
    )
    return payload


__all__ = ["load_paper", "load_review", "perform_improvement"]
