"""LaTeX skeletons for paper and thesis packs, including the protected blocks."""

from __future__ import annotations

from .writing_content import (
    THESIS_BARE_SECTIONS,
    _document_kind,
    _slug,
)


def _declarations_block() -> str:
    from .protected_blocks import PROTECTED_END, PROTECTED_START

    # Author-owned and protected: the harness can neither write nor alter these
    # statements. They stay commented until the authors fill them in, so the
    # quality audit reports them missing rather than accepting a template.
    return (
        f"{PROTECTED_START}\n"
        "% Declarations: author-owned, filled in by the authors before submission.\n"
        "% Uncomment and complete what the target journal requires.\n"
        "% \\section*{Declarations}\n"
        "% \\paragraph{Competing interests} The authors declare ...\n"
        "% \\paragraph{Funding} This work was supported by ... (grant ...).\n"
        "% \\paragraph{Data availability} The data are available at ...\n"
        "% \\paragraph{Author contributions (CRediT)} A: Conceptualization, ...\n"
        "% \\paragraph{Use of generative AI} During the preparation of this work the\n"
        "%   authors used [tool] for [purpose]. The authors reviewed and edited the\n"
        "%   content and take full responsibility for it.\n"
        f"{PROTECTED_END}\n"
    )


_DECLARATIONS_BLOCK = _declarations_block()


def _method_outline_comment(research_design: str | None) -> str:
    """Suggested Method subsections for ``research_design``, as LaTeX comments.

    They are comments, not headings: the Method task replaces its TODO marker,
    and empty headings left below the drafted prose would only be noise. The
    agent sees the outline here and in its brief, and writes the subsections.
    """

    if research_design in (None, "", "auto"):
        return ""
    from .research_designs import get_design

    design = get_design(str(research_design))
    if not design.method_outline:
        return ""
    lines = [f"% Suggested subsections ({design.guideline}):"]
    lines += [f"%   - {name}" for name in design.method_outline]
    return "\n".join(lines) + "\n"


def _skeleton(title: str, protected_body: str = "", research_design: str | None = None) -> str:
    safe_title = str(title or "").strip() or "Untitled Research Manuscript"
    from .protected_blocks import PROTECTED_END, PROTECTED_START

    protected = (
        f"{PROTECTED_START}\n"
        f"{protected_body or '% Author-supplied experimental setup and results remain unchanged.'}\n"
        f"{PROTECTED_END}\n"
    )
    return (
        "\\documentclass{article}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage{graphicx}\n"
        "\\title{" + safe_title + "}\n"
        "\\author{}\n"
        "\\date{}\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        "\\begin{abstract}\n"
        "% TODO(agent): title-and-abstract\n"
        "\\end{abstract}\n"
        "\\section{Introduction}\n"
        "% TODO(agent): section-introduction\n"
        "\\section{Related Work}\n"
        "% TODO(agent): section-related-work\n"
        "\\section{Background}\n"
        "% TODO(agent): section-background\n"
        "\\section{Method}\n"
        "% TODO(agent): section-method\n"
        + _method_outline_comment(research_design)
        + protected
        + "\\section{Discussion}\n"
        "% TODO(agent): section-discussion\n"
        "\\section{Limitations}\n"
        "% TODO(agent): section-limitations\n"
        "\\section{Conclusion}\n"
        "% TODO(agent): section-conclusion\n"
        + _DECLARATIONS_BLOCK
        + "\\bibliographystyle{plain}\n"
        "\\bibliography{references}\n"
        "\\end{document}\n"
    )


def skeleton_document(
    title: str, protected_body: str = "", research_design: str | None = None
) -> str:
    return _skeleton(title, protected_body, research_design)


def _thesis_skeleton(
    title: str,
    *,
    thesis_type: str = "thesis",
    protected_body: str = "",
    research_design: str | None = None,
) -> str:
    """Generic thesis skeleton (document_kind="thesis").

    The structure is intentionally institution/language agnostic: front matter,
    chapter headings, and a generic bibliography. It generalises from common
    thesis conventions (illustrated by the Telkom S2 example the user supplied)
    without depending on any single template.
    """

    safe_title = str(title or "").strip() or "Judul Tesis"
    from .protected_blocks import PROTECTED_END, PROTECTED_START

    protected = (
        f"{PROTECTED_START}\n"
        f"{protected_body or '% Data/eksperimen yang disediakan penulis tetap tidak berubah.'}\n"
        f"{PROTECTED_END}\n"
    )
    outline = _method_outline_comment(research_design).rstrip("\n")
    chapter_block = "\n".join(
        f"\\chapter{{{name}}}\\label{{ch:{_slug(name)}}}\n% TODO(agent): section-{_slug(name)}"
        + (f"\n{outline}" if outline and "metod" in name.lower() else "")
        for name in THESIS_BARE_SECTIONS
    )
    type_note = {
        "skripsi": "Skripsi (Sarjana)",
        "tesis": "Tesis (Magister)",
        "disertasi": "Disertasi (Doktor)",
    }.get(thesis_type, "Tesis")
    return (
        "\\documentclass[12pt]{report}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage[indonesian]{babel}\n"
        "\\usepackage{graphicx}\n"
        "\\title{" + safe_title + "}\n"
        "\\author{}\n"
        "\\date{}\n"
        "\\begin{document}\n"
        "\\begin{titlepage}\n"
        f"% {type_note} -- judul, nama penulis, dan lembar pengesahan diisi sesuai pedoman kampus.\n"
        "\\maketitle\n"
        "\\end{titlepage}\n"
        "\\begin{abstract}\n"
        "% TODO(agent): abstract\n"
        "\\end{abstract}\n"
        "\\tableofcontents\n"
        "\\listoffigures\n"
        "\\listoftables\n"
        + chapter_block
        + "\n"
        + protected
        + "\\bibliographystyle{plain}\n"
        "\\bibliography{references}\n"
        "\\end{document}\n"
    )


def skeleton_document_kind(
    title: str,
    *,
    document_kind: str = "paper",
    thesis_type: str = "thesis",
    protected_body: str = "",
    research_design: str | None = None,
) -> str:
    """Dispatch skeleton by document kind; thesis uses the chapter scaffold."""

    if _document_kind({"document_kind": document_kind}) == "thesis":
        return _thesis_skeleton(
            title,
            thesis_type=thesis_type,
            protected_body=protected_body,
            research_design=research_design,
        )
    return _skeleton(title, protected_body, research_design)
