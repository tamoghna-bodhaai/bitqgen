"""Helpers for the question text format: plain text + `$inline$` / `$$display$$` LaTeX.

Supported light markup: `**bold**`, blank line = paragraph, single newline = line break.
"""
from __future__ import annotations

import html
import re

from core.mathfix import normalize_math

_MATH = re.compile(r"(\$\$.+?\$\$|\$.+?\$)", re.S)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITAL = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", re.S)
_CMD = re.compile(r"\\[a-zA-Z]+")


def split_math(text: str) -> list[tuple[bool, str]]:
    """Split into (is_math, chunk) pieces; math chunks keep their $ delimiters."""
    out, pos = [], 0
    for m in _MATH.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def _is_sep(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip()) and any(cells)


def _table(lines: list[str]) -> str:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    head = None
    if len(rows) > 1 and _is_sep(rows[1]):
        head, rows = rows[0], rows[2:]
    cell = lambda c: _inline(c)
    h = "".join(f"<th>{cell(c)}</th>" for c in head) if head else ""
    body = "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="qt">{"<thead><tr>" + h + "</tr></thead>" if h else ""}<tbody>{body}</tbody></table>'


def to_html(text: str) -> str:
    """Escape for HTML, keep math for KaTeX auto-render, apply light markup and pipe tables."""
    out, buf, tbl = [], [], []
    for ln in normalize_math(text or "").split("\n"):
        if ln.lstrip().startswith("|"):
            if buf:
                out.append(("t", "\n".join(buf))); buf = []
            tbl.append(ln)
        else:
            if tbl:
                out.append(("tbl", tbl)); tbl = []
            buf.append(ln)
    if tbl:
        out.append(("tbl", tbl))
    if buf:
        out.append(("t", "\n".join(buf)))
    html_parts = []
    for kind, val in out:
        if kind == "tbl":
            html_parts.append(_table(val))
        elif val.strip():
            html_parts.append("<p>" + _inline(val.strip("\n")) + "</p>")
    return "".join(html_parts) or "<p></p>"


_U = re.compile(r"&lt;u&gt;(.+?)&lt;/u&gt;", re.S)
_GLUE = re.compile(r"^[.,;:?!)\]]+")


def _inline(text: str) -> str:
    parts = []
    pieces = split_math(text or "")
    for k, (is_math, chunk) in enumerate(pieces):
        if is_math:
            m = html.escape(chunk, quote=False)
            # keep trailing punctuation on the same line as inline math
            nxt = pieces[k + 1][1] if k + 1 < len(pieces) and not pieces[k + 1][0] else ""
            g = _GLUE.match(nxt) if not chunk.startswith("$$") else None
            if g:
                m = f'<span class="nobr">{m}{html.escape(g.group(0))}</span>'
                pieces[k + 1] = (False, nxt[g.end():])
            parts.append(m)
        else:
            esc = html.escape(chunk, quote=False)
            esc = _U.sub(r"<u>\1</u>", esc)
            esc = _BOLD.sub(r"<b>\1</b>", esc)
            esc = _ITAL.sub(r"<i>\1</i>", esc)
            esc = esc.replace("\n\n", "</p><p>").replace("\n", "<br>")
            parts.append(esc)
    return "".join(parts)


def visible_len(text: str) -> int:
    """Rough rendered width of a snippet (used to choose the option grid layout)."""
    t = re.sub(r"\\(?:,|;|!|quad|qquad|left|right|text|mathrm|dfrac|frac|tfrac|sqrt)", "", text or "")
    t = _CMD.sub("x", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[\$\{\}\^_\\*]", "", t)
    # fractions render roughly half as wide as their source
    if "frac" in (text or ""):
        return max(1, int(_w(t) * 0.6))  # stacked fractions are narrow
    return int(_w(t))


def _w(t: str) -> float:
    """Capitals are ~1.4x the width of lowercase letters in a serif face."""
    return sum(1.4 if c.isupper() else 1.15 if c.isdigit() else 1.0 for c in t)


def option_cols(options: list[str], has_figures: bool = False, fig_widths: list[int] | None = None) -> int:
    """4 per row if all short, 2 if medium, else 1 (as in the source papers).
    `fig_widths` are option-figure widths as % of the column."""
    m = max(visible_len(o) for o in options)
    if has_figures:
        fw = max(fig_widths or [20])
        by_fig = 4 if fw <= 22 else 2 if fw <= 45 else 1
        # option text sits under its figure and may wrap, so it never forces a single column
        by_text = 4 if m <= 7 else 2
        return min(by_fig, by_text)
    if m <= 7:
        return 4
    if m <= 17:
        return 2
    return 1
