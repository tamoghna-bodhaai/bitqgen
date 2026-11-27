"""Blind-solve corpus questions with candidate solver models and score against the PDF answer key.

  uv run python -m evals.solver_bakeoff --paper 2026s1 --models google/gemini-3.8-flash,qwen/qwen4-max
  options: --sections Physics,Chemistry,Mathematics  --limit N  --reasoning high  --workers 8

Writes data/evals/solver_<paper>_<timestamp>.jsonl and prints a summary table.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.llm import LLM, image_part
from core.models import LETTERS, Paper

ROOT = Path(__file__).resolve().parent.parent
TEXT_ONLY = {"z-ai/glm-5.3", "deepseek/deepseek-v4-pro-0813", "z-ai/glm-5.3-prime"}
EXCLUDE = {"2026s1": {32, 52, 93}}  # doubtful key / garbled source text

SYSTEM = ("You are an expert solver for the BITSAT engineering entrance exam (Physics, Chemistry, "
          "Mathematics). Each question has exactly one correct option. Solve carefully and check "
          "your work, then report the final option letter.")


class SolverVerdict(BaseModel):
    working: str = Field(description="Brief key steps (max ~6 lines)")
    answer: Literal["A", "B", "C", "D"]
    confidence: float = Field(description="0 to 1")


def build_messages(q, base: Path, images: bool) -> list[dict] | None:
    needs_img = bool(q.figure) or any(o.figure and not o.alt for o in q.options)
    if needs_img and not images:
        return None
    lines = [q.stem]
    for L, o in zip(LETTERS, q.options):
        lines.append(f"({L}) {o.text or o.alt or '[see figure]'}")
    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    if images and q.figure:
        content.append(image_part(base / q.figure.path))
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default="2026s1")
    ap.add_argument("--models", required=True)
    ap.add_argument("--sections", default="Physics,Chemistry,Mathematics")
    ap.add_argument("--reasoning", default="high")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    base = ROOT / "data" / "corpus" / a.paper
    paper = Paper(**json.loads((base / "paper.json").read_text()))
    secs = set(a.sections.split(","))
    qs = [q for q in paper.sorted() if q.section in secs and q.qno not in EXCLUDE.get(a.paper, set())]
    if a.limit:
        qs = qs[:a.limit]
    models = a.models.split(",")
    llm = LLM()
    out = ROOT / "data" / "evals" / f"solver_{a.paper}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    jobs = []
    for m in models:
        for q in qs:
            msgs = build_messages(q, base, images=m not in TEXT_ONLY)
            if msgs is not None:
                jobs.append((m, q, msgs))
    print(f"{len(qs)} questions x {len(models)} models -> {len(jobs)} calls")

    results = []
    t0 = time.time()

    def run(job):
        m, q, msgs = job
        r = llm.call("solver", msgs, schema=SolverVerdict, model=m, reasoning=a.reasoning,
                     max_tokens=16000, fallbacks=[])
        ans = r.data.answer if r.data else None
        loose = False
        if ans is None and r.text:  # model ignored the JSON format: recover the letter from prose
            m_ = (re.search(r'"answer"\s*:\s*"([A-D])"', r.text)
                  or re.search(r"(?:correct (?:option|answer) is|answer is|Answer:)\s*\**\s*\(?([A-D])\b", r.text))
            if m_:
                ans, loose = m_.group(1), True
        return {"format_ok": not loose and r.data is not None,"model": m, "qno": q.qno, "section": q.section, "difficulty": q.difficulty,
                "has_figure": bool(q.figure), "key": q.answer, "answer": ans,
                "correct": ans == q.answer, "confidence": r.data.confidence if r.data else None,
                "working": r.data.working if r.data else r.text[:400], "error": r.error,
                "cost": r.cost, "completion_tokens": r.completion_tokens, "served_by": r.model}

    with ThreadPoolExecutor(a.workers) as ex, out.open("w") as f:
        futs = [ex.submit(run, j) for j in jobs]
        for i, fu in enumerate(as_completed(futs), 1):
            row = fu.result()
            results.append(row)
            f.write(json.dumps(row) + "\n")
            if i % 25 == 0:
                print(f"  {i}/{len(jobs)}  ${llm.total_cost:.2f}  {time.time() - t0:.0f}s", flush=True)

    # ---- summary -----------------------------------------------------------
    common = set(q.qno for q in qs if not q.figure)
    print(f"\nTotal cost ${llm.total_cost:.2f}, {time.time() - t0:.0f}s. Results: {out}\n")
    hdr = f"{'model':34s} {'all':>9s} {'text-only':>9s} {'Phy':>6s} {'Chem':>6s} {'Math':>6s} {'d>=3':>6s} {'fmt!':>5s} {'$':>6s} {'tok/q':>6s}"
    print(hdr)
    for m in models:
        rs = [r for r in results if r["model"] == m]
        def acc(sel):
            s = [r for r in rs if sel(r)]
            return f"{sum(r['correct'] for r in s)}/{len(s)}" if s else "-"
        errs = sum(1 for r in rs if not r["format_ok"])
        cost = sum(r["cost"] for r in rs)
        tok = sum(r["completion_tokens"] for r in rs) / max(1, len(rs))
        print(f"{m:34s} {acc(lambda r: True):>9s} {acc(lambda r: r['qno'] in common):>9s} "
              f"{acc(lambda r: r['section'] == 'Physics'):>6s} {acc(lambda r: r['section'] == 'Chemistry'):>6s} "
              f"{acc(lambda r: r['section'] == 'Mathematics'):>6s} {acc(lambda r: (r['difficulty'] or 0) >= 3):>6s} "
              f"{errs:>5d} {cost:>6.2f} {tok:>6.0f}")
    # questions every model got wrong -> likely key/transcription issues worth checking
    wrong_all = defaultdict(list)
    for r in results:
        wrong_all[r["qno"]].append(r["correct"])
    suspects = sorted(q for q, v in wrong_all.items() if len(v) == len(models) and not any(v))
    print(f"\nWrong for every model (check key/transcription): {suspects}")


if __name__ == "__main__":
    main()
