"""Vision transcription of an uploaded past paper: column images -> t*.json batches.

  uv run python -m ingest.transcribe <paper_id> [--pages 1-2]

Replaces the hand transcription step used for the seed corpus. Needs ingest.layout to have run
(skeleton.json + cols/*.png). Writes data/corpus/<id>/tNN.json (one file per page, the format
ingest.merge reads). Pages whose tNN.json already exists are skipped, so a re-run only pays for
what is missing. The answer key never comes from here: merge takes it from the skeleton.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import yaml

from agents.common import PROMPTS
from core.llm import image_part
from core.models import TranscriptionBatch
from ingest import layout

SYLLABUS = layout.ROOT / "config" / "syllabus.yaml"


def _chapters() -> dict[str, list[str]]:
    try:
        d = yaml.safe_load(SYLLABUS.read_text())
        return {sec: [t["name"] for t in s["topics"]] for sec, s in d["sections"].items()}
    except Exception:  # noqa: BLE001
        return {}


def _columns(d: Path) -> list[str]:
    return sorted(p.stem for p in (d / "cols").glob("p*.png"))


def plan(skel: dict, cols: list[str]) -> dict[str, list[dict]]:
    """column name (e.g. p03L) -> skeleton questions that start in it."""
    out: dict[str, list[dict]] = defaultdict(list)
    for q in skel["questions"]:
        out[f"p{q['loc']['page']:02d}{q['loc']['col']}"].append(q)
    return {c: out[c] for c in cols if out.get(c)}


def _ask(llm, d: Path, col: str, nxt: str | None, qs: list[dict], chapters: dict) -> list[dict]:
    secs = sorted({q["section"] for q in qs})
    lines = [f"Transcribe questions {', '.join(str(q['qno']) for q in qs)} "
             f"(they start in the FIRST image; the second image is the next column, where the last one may continue)."]
    for s in secs:
        lines.append(f"Section {s}: questions {[q['qno'] for q in qs if q['section'] == s]}.")
        if chapters.get(s):
            lines.append(f"  Chapter / type names for {s}: " + "; ".join(chapters[s]))
    content = [{"type": "text", "text": "\n".join(lines)}, image_part(d / "cols" / f"{col}.png")]
    if nxt:
        content.append(image_part(d / "cols" / f"{nxt}.png"))
    msgs = [{"role": "system", "content": (PROMPTS / "transcriber.md").read_text()},
            {"role": "user", "content": content}]
    res = llm.call("transcriber", msgs, schema=TranscriptionBatch)
    if res.data is None:
        raise RuntimeError(f"{col}: {res.error or 'no data'}")
    want = {q["qno"] for q in qs}
    return [q.model_dump(exclude_none=True) for q in res.data.questions if q.qno in want]


def transcribe(pid: str, llm, *, pages: set[int] | None = None, workers: int = 4,
               progress: Callable[[int, int], None] | None = None) -> list[int]:
    """Transcribe every page without a tNN.json. Returns the qnos still missing afterwards."""
    d = layout.CORPUS / pid
    skel = json.loads((d / "skeleton.json").read_text())
    cols = _columns(d)
    work = plan(skel, cols)
    chapters = _chapters()
    by_page: dict[int, list[str]] = defaultdict(list)
    for c in work:
        p = int(c[1:3])
        if (pages is None or p in pages) and not (d / f"t{p:02d}.json").exists():
            by_page[p].append(c)
    total, done = sum(len(v) for v in by_page.values()), 0
    if progress:
        progress(0, total)

    def do_col(c: str) -> list[dict]:
        nxt = cols[cols.index(c) + 1] if cols.index(c) + 1 < len(cols) else None
        qs = work[c]
        try:
            got = _ask(llm, d, c, nxt, qs, chapters)
        except RuntimeError:
            got = []
        missing = [q for q in qs if q["qno"] not in {g["qno"] for g in got}]
        if missing:  # one retry, only for what is missing
            try:
                got += _ask(llm, d, c, nxt, missing, chapters)
            except RuntimeError:
                pass
        return got

    def do_page(p: int) -> None:
        nonlocal done
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(do_col, by_page[p]))
        seen, out = set(), []
        for q in sorted((q for r in res for q in r), key=lambda q: q["qno"]):
            if q["qno"] not in seen:
                seen.add(q["qno"])
                out.append(q)
        want = {q["qno"] for c in by_page[p] for q in work[c]}
        if out and seen >= want:  # only complete pages are saved, so a re-run retries the rest
            (d / f"t{p:02d}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
        done += len(by_page[p])
        if progress:
            progress(done, total)

    with ThreadPoolExecutor(max(1, workers // 2)) as ex:
        list(ex.map(do_page, sorted(by_page)))

    have = set()
    for f in d.glob("t[0-9]*.json"):
        have |= {q["qno"] for q in json.loads(f.read_text())}
    scope = [q for c, qs in work.items() for q in qs if pages is None or int(c[1:3]) in pages]
    return sorted(q["qno"] for q in scope if q["qno"] not in have)


def parse_pages(s: str | None) -> set[int] | None:
    if not s:
        return None
    out = set()
    for part in s.split(","):
        a, _, b = part.partition("-")
        out |= set(range(int(a), int(b or a) + 1))
    return out


def main() -> None:
    from core.llm import LLM
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--pages")
    a = ap.parse_args()
    llm = LLM()
    missing = transcribe(a.pid, llm, pages=parse_pages(a.pages), progress=lambda i, n: print(f"{i}/{n} columns"))
    print(f"cost ${llm.total_cost:.3f}; missing: {missing}")


if __name__ == "__main__":
    main()
