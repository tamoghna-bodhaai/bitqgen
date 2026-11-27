"""Paper -> DOCX via Pandoc (LaTeX math becomes native, editable Word equations),
then post-processed with python-docx for the 2-column layout and fonts."""
from __future__ import annotations

import copy
import os
import re
import tempfile
from pathlib import Path

import pypandoc
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from core.models import LETTERS, Paper
from render.html import Mode, load_pattern
from core.mathfix import normalize_math
from render.text import option_cols

FONT = "Times New Roman"
TITLE_MARK = "@@END_TITLE@@"


def _fig_md(fig, scale: float = 1.0) -> str:
    # pandoc % widths are relative to the text width; our widths are relative to one column
    return f"![]({fig.path}){{width={max(5, round(fig.width_pct * 0.48 * scale))}%}}" if fig else ""


_LISTY = re.compile(r"(?m)^(\s*)(\(?)([A-Za-z0-9]{1,3})([.)])(\s)")


# "m s$^{-1}$": a superscript with no base becomes an empty placeholder box in Word equations.
# Pull the preceding unit token into the math: "m $\text{s}^{-1}$".
_BASELESS = re.compile(r"(\b[A-Za-z]{1,4})?\$\s*([\^_](?:\{[^$]*?\}|[^\s$]))\s*\$")


def _fix_baseless(text: str) -> str:
    return _BASELESS.sub(lambda m: f"$\\text{{{m.group(1)}}}{m.group(2)}$" if m.group(1) else f"${{}}{m.group(2)}$",
                         text)


def _clean(text: str) -> str:
    text = _fix_baseless(normalize_math(text or ""))
    text = re.sub(r"<u>(.+?)</u>", r"[\1]{.underline}", text, flags=re.S)
    # escape line-start list markers like "1." or "(a)"; keep paragraphs; single newlines -> hard breaks
    text = _LISTY.sub(lambda m: m.group(1) + ("\\(" if m.group(2) else "") + m.group(3)
                      + "\\" + m.group(4) + m.group(5), text or "")
    return (text or "").strip().replace("\n\n", " ").replace("\n", "\\\n").replace(" ", "\n\n")


def paper_markdown(paper: Paper, mode: Mode, *, show_key: bool | None = None,
                   show_instructions: bool = True) -> str:
    if show_key is None:
        show_key = mode == "paper"
    qs = paper.sorted()
    md = [f"**{paper.title}**\n", f"{paper.subtitle}\n" if paper.subtitle else ""]
    pat = load_pattern(paper.pattern_id)
    if show_instructions and pat and mode != "key":
        secs: list[list] = []
        for q in qs:
            if secs and secs[-1][0] == q.section:
                secs[-1][2] = q.qno
            else:
                secs.append([q.section, q.qno, q.qno])
        md.append(f"**Instructions:** Duration {pat.duration_min} minutes · {len(qs)} questions · "
                  f"+{pat.marks_correct} for each correct answer, {pat.marks_wrong} for each wrong answer. "
                  + "; ".join(f"{n}: Q{a}–{b}" for n, a, b in secs) + ".\n")
    md.append(f"{TITLE_MARK}\n")
    for q in (qs if mode != "key" else []):
        stem = _clean(q.stem) + (f" {q.source_tag}" if q.source_tag else "")
        md.append(f"**{q.qno}.** {stem}\n")
        if q.figure:
            md.append(_fig_md(q.figure) + "\n")
        opts = [f"\\({L}) " + (_fig_md(o.figure) + " " if o.figure else "") + _clean(o.text)
                for L, o in zip(LETTERS, q.options)]
        cols = option_cols([o.text for o in q.options], any(o.figure for o in q.options),
                           [o.figure.width_pct for o in q.options if o.figure])
        sep = "  "
        rows = [opts[i:i + cols] for i in range(0, 4, cols)]
        md.append("\\\n".join(sep.join(r) for r in rows) + "\n")
        if mode == "solutions":
            md.append(f"**Correct Option:** {q.answer}\n")
            md.append(f"**Solution:** {_clean(q.solution)}\n")
            if q.solution_figure:
                md.append(_fig_md(q.solution_figure) + "\n")
    if show_key or mode == "key":
        per = 4  # (Q, Ans) pairs per row: fits one column of the 2-column body
        md.append("\n**Answer Key**\n")
        md.append("|" + " Q | Ans |" * per)
        md.append("|" + "---|---|" * per)
        for i in range(0, len(qs), per):
            row = qs[i:i + per]
            cells = "".join(f" **{q.qno}** | {q.answer} |" for q in row) + " | |" * (per - len(row))
            md.append("|" + cells)
        md.append("")
    return "\n".join(md)


def _cols_el(n: int) -> OxmlElement:
    c = OxmlElement("w:cols")
    c.set(qn("w:num"), str(n))
    c.set(qn("w:space"), "397")  # ~7mm
    if n > 1:
        c.set(qn("w:sep"), "1")
    return c


def _style_tables(doc, col_width_mm: float) -> None:
    """Answer-key tables: fixed layout that fits the column, thin borders, compact centred cells."""
    for t in doc.tables:
        ncols = len(t.columns)
        w = Mm(col_width_mm / max(1, ncols))
        tblPr = t._tbl.tblPr
        tw = str(int(col_width_mm * 56.7))
        for old in tblPr.findall(qn("w:tblW")):
            tblPr.remove(old)
        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), tw)
        tblW.set(qn("w:type"), "dxa")
        tblPr.append(tblW)
        grid = t._tbl.tblGrid
        for gc in grid.findall(qn("w:gridCol")):
            gc.set(qn("w:w"), str(int(col_width_mm * 56.7 / ncols)))
        lay = OxmlElement("w:tblLayout")
        lay.set(qn("w:type"), "fixed")
        tblPr.append(lay)
        borders = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), "4")
            b.set(qn("w:color"), "888888")
            borders.append(b)
        tblPr.append(borders)
        for row in t.rows:
            for c in row.cells:
                c.width = w
                for p in c.paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p.paragraph_format.space_after = Pt(0)
                    for r in p.runs:
                        r.font.size = Pt(9.5)


def _postprocess(path: Path, body_cols: int = 2) -> None:
    doc = Document(str(path))
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONT, Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    for name in ("Body Text", "First Paragraph", "Compact"):
        if name in doc.styles:
            s = doc.styles[name]
            s.font.name, s.font.size = FONT, Pt(10.5)
            s.paragraph_format.space_after = Pt(4)
            s.paragraph_format.space_before = Pt(0)

    body_sect = doc.sections[-1]
    body_sect.page_width, body_sect.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin"):
        setattr(body_sect, side, Mm(12))
    body_sect.top_margin, body_sect.bottom_margin = Mm(14), Mm(14)

    paras = doc.paragraphs
    marker = next((p for p in paras if TITLE_MARK in p.text), None)
    if marker is not None:
        # title paragraphs: centred, bold, larger
        for k, p in enumerate(paras[:paras.index(marker)]):
            if k == 0 or (k == 1 and not p.text.startswith("Instructions")):  # title, subtitle
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for r in p.runs:
                    r.font.size = Pt(14 if k == 0 else 10)
            else:  # instructions line
                for r in p.runs:
                    r.font.size = Pt(9.5)
        # the marker paragraph ends a 1-column section; the rest becomes 2 columns
        sp = copy.deepcopy(body_sect._sectPr)
        for old in sp.findall(qn("w:cols")):
            sp.remove(old)
        sp.append(_cols_el(1))
        for r in list(marker.runs):
            r._r.getparent().remove(r._r)
        marker._p.get_or_add_pPr().append(sp)
        final = body_sect._sectPr
        for old in final.findall(qn("w:cols")):
            final.remove(old)
        t = OxmlElement("w:type")
        t.set(qn("w:val"), "continuous")
        final.insert(0, t)
        final.append(_cols_el(body_cols))
    _style_tables(doc, 186 if body_cols == 1 else 88)
    doc.save(str(path))


def export_docx(paper: Paper, out: Path, mode: Mode = "paper", assets_dir: Path | None = None, *,
                show_key: bool | None = None, show_instructions: bool = True) -> Path:
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    md = paper_markdown(paper, mode, show_key=show_key, show_instructions=show_instructions)
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "paper.md"
        src.write_text(md, encoding="utf-8")
        try:
            # run pandoc from the assets dir so relative figure paths resolve
            os.chdir(assets_dir or td)
            pypandoc.convert_file(str(src), "docx", outputfile=str(out),
                                  format="markdown+tex_math_dollars+link_attributes")
        finally:
            os.chdir(cwd)
    _postprocess(out, body_cols=1 if mode == "key" else 2)
    return out
