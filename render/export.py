"""One entry point for every export: content x format x options, plus a ZIP bundle.

    from render.export import ExportOptions, export, export_bundle
    path = export(paper, ExportOptions(content="solutions", fmt="docx"), out_dir, assets_dir)
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from core.models import Paper
from render.html import ROOT as RENDER_ROOT, render_html

Content = Literal["paper", "solutions", "key"]
Fmt = Literal["pdf", "docx", "html"]


class ExportOptions(BaseModel):
    content: Content = "paper"           # question paper | paper with solutions | answer key only
    fmt: Fmt = "pdf"
    sections: Optional[list[str]] = None  # None = all sections (original numbering is kept)
    instructions: bool = True
    answer_key: Optional[bool] = None     # default: appended to the question paper only


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")[:40] or "paper"


def filtered(paper: Paper, sections: Optional[list[str]]) -> Paper:
    if not sections:
        return paper
    return paper.model_copy(update={"questions": [q for q in paper.questions if q.section in sections]})


def filename(paper: Paper, o: ExportOptions) -> str:
    name = {"paper": "paper", "solutions": "solutions", "key": "answer_key"}[o.content]
    sec = ("_" + "_".join(_slug(s)[:12] for s in o.sections)) if o.sections else ""
    ext = "zip" if o.fmt == "html" else o.fmt
    return f"{_slug(paper.title)}_{name}{sec}.{ext}"


def _figure_files(paper: Paper) -> set[str]:
    out = set()
    for q in paper.questions:
        for f in [q.figure, q.solution_figure, *[o.figure for o in q.options]]:
            if f:
                out.add(f.path)
    return out


def export(paper: Paper, o: ExportOptions, out_dir: Path, assets_dir: Optional[Path]) -> Path:
    p = filtered(paper, o.sections)
    if not p.questions:
        raise ValueError("no questions in the selected sections")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename(paper, o)
    kw = {"show_key": o.answer_key, "show_instructions": o.instructions}
    if o.fmt == "pdf":
        from render.pdf import export_pdf
        export_pdf(p, target, o.content, assets_dir, **kw)
    elif o.fmt == "docx":
        from render.docx import export_docx
        export_docx(p, target, o.content, assets_dir, **kw)
    else:  # offline HTML bundle: page + KaTeX + figures
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "index.html").write_text(render_html(p, o.content, static="static", **kw), encoding="utf-8")
            shutil.copytree(RENDER_ROOT / "static", work / "static")
            for rel in _figure_files(p):
                src = Path(assets_dir or ".") / rel
                if src.exists():
                    (work / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(src, work / rel)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
                for f in work.rglob("*"):
                    if f.is_file():
                        z.write(f, f.relative_to(work))
    return target


def export_bundle(paper: Paper, out_dir: Path, assets_dir: Optional[Path], paper_json: Optional[Path] = None) -> Path:
    """ZIP with paper / solutions / answer key as PDF and DOCX (+ paper.json)."""
    out_dir = Path(out_dir)
    files = []
    for content in ("paper", "solutions", "key"):
        for fmt in ("pdf", "docx"):
            files.append(export(paper, ExportOptions(content=content, fmt=fmt), out_dir, assets_dir))
    target = out_dir / f"{_slug(paper.title)}_all.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
        if paper_json and paper_json.exists():
            z.write(paper_json, "paper.json")
    return target
