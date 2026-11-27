"""Uploaded past paper -> seed corpus paper, end to end (the seed papers' steps, automated).

  uv run python -m ingest.pipeline path/to/paper.pdf [--id 2027s1] [--pattern bitsat_130] [--pages 1-2]

layout (no LLM) -> vision transcription (stage `transcriber`) -> flag doubtful -> merge -> rebuild
syllabus + style profiles. Status lives in data/corpus/<id>/ingest.json; the PDF is kept as source.pdf.
Re-running on the same id resumes: transcribed pages are kept.
"""
from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
from pathlib import Path

from ingest import layout

ACTIVE = {"queued", "layout", "transcribing", "merging", "rebuilding"}


def status_path(pid: str) -> Path:
    return layout.CORPUS / pid / "ingest.json"


def read_status(pid: str) -> dict | None:
    p = status_path(pid)
    return json.loads(p.read_text()) if p.exists() else None


_lock = threading.Lock()


def _write(pid: str, st: dict) -> None:
    with _lock:  # progress callbacks arrive from transcription worker threads
        st["updated"] = time.time()
        p = status_path(pid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1))
        tmp.replace(p)


def stage_pdf(src: Path, pid: str) -> Path:
    d = layout.CORPUS / pid
    d.mkdir(parents=True, exist_ok=True)
    dst = d / "source.pdf"
    if Path(src).resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    _write(pid, {"id": pid, "status": "queued", "source": Path(src).name, "started": time.time()})
    return dst


def ingest_paper(pid: str, *, pattern: str | None = None, pages: set[int] | None = None,
                 llm=None, rebuild: bool = True, log=print) -> dict:
    """Run every step for data/corpus/<pid>/source.pdf (see stage_pdf). Never raises: errors go to the status."""
    from ingest import flag_doubtful, merge, transcribe

    st = read_status(pid) or {"id": pid, "started": time.time()}
    st.update(status="layout", error=None, cost=st.get("cost", 0.0))

    def save(**kw):
        st.update(kw)
        _write(pid, st)
        if "status" in kw:
            log(f"{pid}: {kw['status']}")

    save(status="layout")
    try:
        d = layout.CORPUS / pid
        src = st.get("source") or "source.pdf"
        skel = layout.run_layout(d / "source.pdf", pid, pattern)
        skel["source_pdf"] = src
        (d / "skeleton.json").write_text(json.dumps(skel, indent=1))
        n = len(skel["questions"])
        if n == 0:
            raise RuntimeError("No questions found. The layout reader expects the eSaral 'Solved Paper' format "
                               "(numbered questions, '(A)'-'(D)' options, 'Correct Option: X').")
        if not any(q["answer"] for q in skel["questions"]):
            raise RuntimeError("No 'Correct Option: X' answers found in the PDF; the answer key is required.")
        save(status="transcribing", questions=n, pattern_id=skel["pattern_id"], warnings=skel["warnings"],
             progress={"done": 0, "total": 0})

        if llm is None:
            from core.llm import LLM
            llm = LLM()
        base = llm.total_cost
        prev = st.get("cost", 0.0)
        missing = transcribe.transcribe(
            pid, llm, pages=pages,
            progress=lambda i, t: save(progress={"done": i, "total": t}, cost=round(prev + llm.total_cost - base, 4)))
        save(cost=round(prev + llm.total_cost - base, 4), untranscribed=missing)
        if missing and pages is None:
            raise RuntimeError(f"{len(missing)} question(s) could not be transcribed ({missing[:12]}...). "
                               "Retry to try those pages again.")

        save(status="merging")
        flag_doubtful.run([pid])
        paper, problems = merge.merge_report(pid)
        save(problems=problems, merged=len(paper.questions))

        if rebuild:
            save(status="rebuilding")
            from ingest import syllabus
            syllabus.main()
            from agents import common
            common.corpus_papers.cache_clear()
        save(status="done", finished=time.time())
    except Exception as e:  # noqa: BLE001
        save(status="error", error=str(e)[:500])
    return st


def main() -> None:
    from ingest.transcribe import parse_pages
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--id")
    ap.add_argument("--pattern")
    ap.add_argument("--pages", help="test on some pages only, e.g. 1-2")
    ap.add_argument("--no-rebuild", action="store_true")
    a = ap.parse_args()
    pdf = Path(a.pdf)
    pid = a.id or layout.paper_id_from(pdf.name)
    stage_pdf(pdf, pid)
    st = ingest_paper(pid, pattern=a.pattern, pages=parse_pages(a.pages), rebuild=not a.no_rebuild)
    print(json.dumps({k: st.get(k) for k in ("status", "error", "questions", "merged", "cost", "problems")}, indent=1))


if __name__ == "__main__":
    main()
