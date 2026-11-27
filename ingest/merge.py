"""Merge layout skeleton + transcription batches (t*.json) into a validated corpus paper.

  uv run python -m ingest.merge 2026s1

Output: data/corpus/<id>/paper.json  (a core.models.Paper; figure paths relative to that dir)
The answer key always comes from the skeleton (parsed from the PDF), never from transcription.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

from core.models import LETTERS, Figure, Option, Paper, Question
from ingest.layout import CORPUS


def _fig(f: dict, kind: str | None) -> Figure:
    w = f["bbox"][2] - f["bbox"][0]
    # source column is ~265pt wide; keep the original relative size
    return Figure(kind=kind or "image", path=f["path"], width_pct=max(15, min(100, round(w / 265 * 100))))


def _stack(d: Path, figs: list[dict], name: str) -> dict:
    """Combine several crops (top-to-bottom) into one image; returns a pseudo-figure dict."""
    if len(figs) == 1:
        return figs[0]
    ims = [Image.open(d / f["path"]).convert("RGB") for f in figs]
    w = max(i.width for i in ims)
    out = Image.new("RGB", (w, sum(i.height for i in ims) + 12 * (len(ims) - 1)), "white")
    y = 0
    for im in ims:
        out.paste(im, (0, y))
        y += im.height + 12
    path = f"figs/{name}"
    out.save(d / path)
    x0 = min(f["bbox"][0] for f in figs)
    x1 = max(f["bbox"][2] for f in figs)
    return {"path": path, "bbox": [x0, 0, x1, 0]}


def merge_report(pid: str) -> tuple[Paper, list[str]]:
    d = CORPUS / pid
    skel = json.loads((d / "skeleton.json").read_text())
    trans: dict[int, dict] = {}
    for f in sorted(d.glob("t[0-9]*.json")):
        for q in json.loads(f.read_text()):
            if q["qno"] in trans:
                raise ValueError(f"duplicate qno {q['qno']} in {f.name}")
            trans[q["qno"]] = q

    out, problems = [], []
    for sq in skel["questions"]:
        n = sq["qno"]
        t = trans.get(n)
        if t is None:
            problems.append(f"Q{n}: not transcribed")
            continue
        if not sq.get("answer"):
            problems.append(f"Q{n}: no 'Correct Option' in the PDF, left out")
            continue
        kind = t.get("figure_kind")
        stem_figs = [f for f in sq["figures"] if f["role"] == "stem"]
        sol_figs = [f for f in sq["figures"] if f["role"] == "sol"]
        # if a letter has several figures (e.g. stem figures labelled (A)/(B)/(C) before the
        # real answer figures), the last one is the option and the earlier ones belong to the stem
        opt_figs: dict[str, dict] = {}
        for f in sq["figures"]:
            if f["role"] == "option":
                if f["letter"] in opt_figs:
                    stem_figs.append(opt_figs[f["letter"]])
                opt_figs[f["letter"]] = f
        opts = []
        for L, text in zip(LETTERS, t["options"]):
            fig = opt_figs.get(L)
            if not text and not fig:
                problems.append(f"Q{n}({L}): empty option with no figure")
            if fig:  # the drawing is authoritative; keep the transcription as alt text
                opts.append(Option(text="", figure=_fig(fig, kind), alt=text or None))
            else:
                opts.append(Option(text=text))
        if t.get("stem_figure_transcribed"):  # stem drawing was rewritten as LaTeX text
            stem_figs = []
        stem_fig = _stack(d, stem_figs, f"q{n:03d}_stem_all.png") if stem_figs else None
        sol_fig = _stack(d, sol_figs, f"q{n:03d}_sol_all.png") if sol_figs else None
        q = Question(
            qno=n, section=sq["section"], answer=sq["answer"],
            stem=t["stem"], options=opts, solution=t.get("solution", ""),
            figure=_fig(stem_fig, kind) if stem_fig else None,
            solution_figure=_fig(sol_fig, kind) if sol_fig else None,
            source_tag=t.get("source_tag"),
            exemplar_ok=t.get("exemplar_ok", True),
            **{k: t.get(k) for k in ("chapter", "subtopic", "archetype", "difficulty",
                                     "figure_kind", "passage_id", "notes")},
        )
        out.append(q)
    extra = sorted(set(trans) - {q["qno"] for q in skel["questions"]})
    if extra:
        problems.append(f"transcribed but not in skeleton: {extra}")

    m = re.fullmatch(r"(20\d\d)(?:s(\d))?", pid)
    if m:
        title = f"BITSAT Solved Paper {m.group(1)}" + (f" Session-{'I' * int(m.group(2))}" if m.group(2) else "")
    else:
        title = skel.get("title") or f"BITSAT Solved Paper ({pid})"
    paper = Paper(title=title, pattern_id=skel["pattern_id"], questions=out)
    (d / "paper.json").write_text(paper.model_dump_json(indent=1, exclude_none=True))
    print(f"{pid}: {len(out)} questions merged -> {d / 'paper.json'}")
    for p in problems:
        print("  !", p)
    return paper, problems


def merge(pid: str) -> Paper:
    return merge_report(pid)[0]


if __name__ == "__main__":
    merge(sys.argv[1])
