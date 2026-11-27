"""Paper -> self-contained HTML (2-column, KaTeX)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.models import LETTERS, Paper, Pattern
from render.text import option_cols, to_html, visible_len

ROOT = Path(__file__).resolve().parent
PATTERNS = ROOT.parent / "patterns"
_env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                   autoescape=select_autoescape(["html", "j2"]))

Mode = Literal["paper", "solutions", "key"]


def load_pattern(pattern_id: str) -> Optional[Pattern]:
    p = PATTERNS / f"{pattern_id}.yaml"
    return Pattern(**yaml.safe_load(p.read_text())) if p.exists() else None


def _view(q, mode: Mode) -> dict:
    texts = [o.text for o in q.options]
    has_fig = any(o.figure for o in q.options)
    cols = option_cols(texts, has_fig, [o.figure.width_pct for o in q.options if o.figure])
    stem = q.stem + (f" {q.source_tag}" if q.source_tag else "")
    v = q.model_dump()
    v.update(
        figure=q.figure, solution_figure=q.solution_figure,
        _stem=to_html(stem),
        _cols=cols,
        # option figure widths are stored relative to the column; convert to the cell
        _opts=[{"letter": L, "html": to_html(o.text) if o.text.strip() else "",
                "figure": o.figure,
                "fig_w": min(100, round(o.figure.width_pct * cols * 1.1)) if o.figure else None}
               for L, o in zip(LETTERS, q.options)],
        _sol=to_html(q.solution) if mode == "solutions" else "",
        # very long items (passages, long solutions) may split across columns
        _long=visible_len(q.stem) > 900 or (mode == "solutions" and visible_len(q.solution) > 700),
    )
    return v


def render_html(paper: Paper, mode: Mode = "paper", *, static: str = "static",
                show_key: bool | None = None, show_instructions: bool = True) -> str:
    """`static` is the URL/path prefix where render/static is served."""
    if show_key is None:
        show_key = mode == "paper"
    qs = [_view(q, mode) for q in paper.sorted()]
    key_rows = [qs[i:i + 10] for i in range(0, len(qs), 10)]
    sections: list[list] = []  # actual ranges present in this paper
    for q in paper.sorted():
        if sections and sections[-1][0] == q.section:
            sections[-1][2] = q.qno
        else:
            sections.append([q.section, q.qno, q.qno])
    return _env.get_template("paper.html.j2").render(
        paper=paper, questions=qs, mode=mode, static=static, key_rows=key_rows,
        show_key=show_key, show_instructions=show_instructions, sections=sections,
        pattern=load_pattern(paper.pattern_id),
    )
