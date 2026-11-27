"""Layout pass over a source paper PDF (no LLM).

Produces data/corpus/<paper_id>/skeleton.json with, for every question:
  qno, section, answer (parsed from "Correct Option:"), location (page/column/y-span),
  and figure crops (PNG) assigned to the stem, an option letter, or the solution.
Also renders one PNG per page column (data/corpus/<id>/cols/) for transcription.

Usage: uv run python -m ingest.layout "bitsat/<file>.pdf" [--id 2026s1] [--pattern bitsat_130]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from render.html import load_pattern

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"

QSTART = re.compile(r"^\s*(\d{1,3})\.(?:\s|$)")
OPT = re.compile(r"\(([A-D])\)")
ANS = re.compile(r"Correct Option:\s*([A-D])")
HEADER_Y = 85      # page header/logo zone (pt)
FOOTER_Y = 815     # footer url zone (pt)
LOGO_MAX_H = 30    # tiny images in the header are the eSaral logo


@dataclass
class Q:
    qno: int
    page: int
    col: int
    y0: float
    answer: str | None = None
    marks: list = field(default_factory=list)  # (page, col, y, kind, letter)  kind: opt|ans|sol
    figures: list = field(default_factory=list)


def col_of(x0: float, mid: float) -> int:
    return 0 if x0 < mid else 1


def paper_id_from(name: str) -> str:
    n = name.lower()
    ym = re.search(r"20\d\d", n)
    if not ym:
        return re.sub(r"[^a-z0-9]+", "-", Path(n).stem).strip("-")[:40] or "upload"
    y = ym.group(0)
    s = re.search(r"session[\s-]*(\d)", n)
    return f"{y}s{s.group(1)}" if s else y


def run_layout(pdf: Path, pid: str | None = None, pattern: str | None = None, dpi: int = 130,
               corpus: Path | None = None) -> dict:
    """Layout pass for one PDF; writes skeleton.json, figs/ and cols/ and returns the skeleton
    (plus `warnings`: missing question numbers, questions without a parsed answer)."""
    pdf = Path(pdf)
    pid = pid or paper_id_from(pdf.name)
    out = (corpus or CORPUS) / pid
    shutil.rmtree(out / "figs", ignore_errors=True)  # crops are regenerated each run
    (out / "figs").mkdir(parents=True, exist_ok=True)
    (out / "cols").mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    mid = doc[0].rect.width / 2

    # ---- pass 1: collect events in reading order (page, col, y) ----------------
    events = []  # (page, col, y, type, payload)
    for pno, page in enumerate(doc):
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                text = "".join(s["text"] for s in line["spans"])
                x0, y0, x1, y1 = line["bbox"]
                if y0 < HEADER_Y - 20 and pno == 0 and "Solved Paper" in text:
                    continue
                c = col_of(x0, mid)
                m = QSTART.match(text)
                if m and x0 < (mid if c == 0 else 2 * mid) - 200:
                    events.append((pno, c, y0, "q", int(m.group(1))))
                for om in OPT.finditer(text):
                    # x of this "(X)" label: approximate from span positions
                    lx = x0
                    for s in line["spans"]:
                        if f"({om.group(1)})" in s["text"]:
                            lx = s["bbox"][0]
                            break
                    events.append((pno, c, y0, "opt", (om.group(1), lx)))
                am = ANS.search(text)
                if am:
                    events.append((pno, c, y0, "ans", am.group(1)))
                if text.strip().startswith("Solution:"):
                    events.append((pno, c, y0, "sol", None))
        for info in page.get_image_info(xrefs=True):
            x0, y0, x1, y1 = info["bbox"]
            if y1 - y0 < LOGO_MAX_H and y0 < HEADER_Y:
                continue
            if x1 - x0 < 6 or y1 - y0 < 6:
                continue
            # order images by their vertical centre: figures often start a few pt above
            # the question-number / option-label baseline they belong to
            events.append((pno, col_of((x0 + x1) / 2, mid), (y0 + y1) / 2, "img", (x0, y0, x1, y1)))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    # ---- pass 2: walk events, attach to current question ----------------------
    qs: dict[int, Q] = {}
    cur: Q | None = None
    state = "stem"
    pending_imgs = []  # images before the first question
    for pno, c, y, kind, pay in events:
        if kind == "q":
            if pay in qs or (cur and pay != cur.qno + 1 and pay < cur.qno):
                continue  # numbered list inside a question (e.g. "1. If Socrates")
            cur = qs[pay] = Q(pay, pno, c, y)
            state = "stem"
        elif cur is None:
            if kind == "img":
                pending_imgs.append((pno, pay))
        elif kind == "opt":
            if state in ("stem", "opt"):
                state = "opt"
                cur.marks.append((pno, c, y, "opt", pay))
        elif kind == "ans":
            cur.answer = pay
            state = "ans"
        elif kind == "sol":
            state = "sol"
        elif kind == "img":
            role = {"ans": "sol", "opt": "stem"}.get(state, state)  # options resolved below
            cur.figures.append({"page": pno, "col": c, "bbox": [round(v, 1) for v in pay],
                                "role": role, "letter": None, "_state": state})

    # ---- resolve option figures using all option labels of the question -------
    for q in qs.values():
        labels = [(mp, mc, my, L, lx) for (mp, mc, my, mk, (L, lx)) in q.marks]
        for f in q.figures:
            st = f.pop("_state")
            c = f.pop("col")
            if f["role"] == "sol" or not labels:
                continue
            x0, y0, x1, y1 = f["bbox"]
            same = [l for l in labels if l[0] == f["page"] and l[1] == c and l[4] <= x0 + 10]
            # 1) a label inside the image's row band, just to its left
            band = [l for l in same if y0 - 8 <= l[2] <= y1 + 4 and x0 - l[4] < 45]
            if band:
                f["role"], f["letter"] = "option", max(band, key=lambda l: l[4])[3]
            elif st == "opt":
                # 2) continuation below a label (multi-part option drawing)
                above = [l for l in same if l[2] <= y0 + 4]
                if above:
                    f["role"], f["letter"] = "option", max(above, key=lambda l: (l[2], l[4]))[3]

    # ---- crops ---------------------------------------------------------------
    zoom = 200 / 72
    for q in qs.values():
        counters = {}
        for f in q.figures:
            key = f["role"] + (f["letter"] or "")
            counters[key] = counters.get(key, 0) + 1
            name = f"q{q.qno:03d}_{key}{'' if counters[key] == 1 else counters[key]}.png"
            r = pymupdf.Rect(f["bbox"])  # exact image box; padding picks up neighbouring text
            doc[f["page"]].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=r).save(out / "figs" / name)
            f["path"] = f"figs/{name}"

    # ---- column images for transcription ---------------------------------------
    for pno, page in enumerate(doc):
        W, H = page.rect.width, page.rect.height
        for c, (x0, x1) in enumerate([(22, mid + 2), (mid - 6, W - 8)]):
            clip = pymupdf.Rect(x0, 30, x1, FOOTER_Y + 5)
            page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), clip=clip).save(
                out / "cols" / f"p{pno + 1:02d}{'LR'[c]}.png")

    # ---- sections from pattern -------------------------------------------------
    nmax = max(qs) if qs else 0
    pat_id = pattern or ("bitsat_150" if nmax > 130 else "bitsat_130")
    pattern = load_pattern(pat_id)
    def section(n):
        for name, s, e in pattern.section_ranges():
            if s <= n <= e:
                return name
        return "?"

    skel = {
        "paper_id": pid, "source_pdf": pdf.name, "pattern_id": pat_id, "pages": len(doc),
        "questions": [
            {"qno": q.qno, "section": section(q.qno), "answer": q.answer,
             "loc": {"page": q.page + 1, "col": "LR"[q.col], "y": round(q.y0)},
             "figures": q.figures}
            for q in sorted(qs.values(), key=lambda q: q.qno)
        ],
    }
    (out / "skeleton.json").write_text(json.dumps(skel, indent=1))
    missing = sorted(set(range(1, nmax + 1)) - set(qs))
    noans = [q.qno for q in qs.values() if not q.answer]
    print(f"{pid}: {len(qs)} questions (max {nmax}), figures={sum(len(q.figures) for q in qs.values())}, "
          f"missing={missing}, no-answer={noans}, pending_imgs={len(pending_imgs)}")
    skel["warnings"] = {"missing": missing, "no_answer": sorted(noans)}
    return skel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--id")
    ap.add_argument("--pattern")
    ap.add_argument("--dpi", type=int, default=130)
    a = ap.parse_args()
    run_layout(Path(a.pdf), a.id, a.pattern, a.dpi)


if __name__ == "__main__":
    main()
