"""Question bank of generated questions that passed verification.

    data/bank/questions.jsonl   one annotated record per question (append-only)
    data/bank/figs/             figure files copied out of the job dir

Kept separate from the past-paper corpus (data/corpus): bank questions are never used as style
exemplars, but new generations are checked against them so later papers do not repeat them.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from agents.common import _shingles, similarity

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "bank"
FILE = BANK / "questions.jsonl"
DUP_THRESHOLD = 0.8   # stem similarity at which a question is treated as already in the bank
_lock = threading.Lock()


def load() -> list[dict]:
    if not FILE.exists():
        return []
    return [json.loads(l) for l in FILE.read_text(encoding="utf-8").splitlines() if l.strip()]


@lru_cache(maxsize=1)
def _shingle_index(mtime: float) -> list[tuple[str, set[str]]]:
    return [(r["id"], _shingles(r["stem"])) for r in load() if len(r.get("stem", "")) > 60]


def nearest(stem: str) -> tuple[str, float]:
    """Most similar banked stem (id, Jaccard 0..1)."""
    if len(stem) <= 60 or not FILE.exists():
        return "", 0.0
    s = _shingles(stem)
    best, score = "", 0.0
    for bid, bs in _shingle_index(FILE.stat().st_mtime):
        j = len(s & bs) / max(1, len(s | bs))
        if j > score:
            best, score = bid, j
    return best, score


def _copy_fig(job_dir: Path, rel: Optional[str], qid: str, tag: str) -> Optional[str]:
    if not rel or not (job_dir / rel).exists():
        return None
    dst = BANK / "figs" / f"{qid}_{tag}{Path(rel).suffix}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job_dir / rel, dst)
    return str(dst.relative_to(BANK))


def record(item: dict, *, job_id: str, job_dir: Path, pattern_id: str, profile: str,
           critic_notes: Optional[str] = None) -> dict:
    """Annotated bank record for one verified job item."""
    s = item["slot"]
    qid = "g" + hashlib.sha1(f"{job_id}:{item['qno']}:{item['stem']}".encode()).hexdigest()[:12]
    verdicts = item.get("verdicts") or []
    solver_diff = [v["difficulty"] for v in verdicts if isinstance(v.get("difficulty"), int)]
    draft = item.get("draft") or {}
    fig = item.get("figure")
    return {
        "id": qid,
        "source": "lr_generator" if s.get("lr_generator") else "generated",
        "status": "verified",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "job_id": job_id, "job_qno": item["qno"], "pattern_id": pattern_id, "profile": profile,
        # syllabus annotation
        "section": item["section"], "chapter": s.get("chapter"), "subtopic": s.get("subtopic") or None,
        "archetype": s.get("archetype") or None, "brief": s.get("brief") or None,
        "difficulty": item.get("difficulty") or s.get("difficulty"),
        "difficulty_target": s.get("difficulty"),
        "difficulty_author": draft.get("difficulty_estimate"),
        "difficulty_solvers": solver_diff or None,
        # content
        "stem": item["stem"], "options": item["options"], "answer": item["answer"],
        "solution": item.get("solution", ""), "working": item.get("working", ""),
        "distractor_notes": draft.get("distractor_notes") or None,
        "passage": item.get("passage"), "passage_id": s.get("passage_id"),
        "figure": ({"path": _copy_fig(job_dir, fig.get("path"), qid, "stem"), "kind": fig.get("kind"),
                    "width_pct": fig.get("width_pct")} if fig else None),
        "option_figs": ([_copy_fig(job_dir, p, qid, f"opt{'ABCD'[k]}") for k, p in enumerate(item["option_figs"])]
                        if item.get("option_figs") else None),
        # provenance / quality
        "author_model": item.get("author_model"),
        "verification": {
            "method": "by construction" if s.get("lr_generator") else "independent solver (+ tiebreaker)",
            "solvers": [{"stage": v.get("stage"), "model": v.get("model"), "answer": v.get("answer"),
                         "confidence": v.get("confidence")} for v in verdicts],
            "attempts": item.get("attempts"),
        },
        "critic_notes": critic_notes,
        "notes": item.get("notes") or [],
        "times_used": 0,
    }


def add_job(items: list[dict], *, job_id: str, job_dir: Path, pattern_id: str, profile: str,
            critic: Optional[dict[int, str]] = None) -> tuple[int, int]:
    """Append every verified question of a job; returns (added, skipped_as_duplicate)."""
    critic = critic or {}
    added = skipped = 0
    with _lock:
        existing = {(r["job_id"], r["job_qno"]) for r in load()}
        new: list[dict] = []
        for it in items:
            if it.get("status") != "ok" or not it.get("stem") or (job_id, it["qno"]) in existing:
                continue
            _, score = nearest(it["stem"])
            if score >= DUP_THRESHOLD or any(similarity(it["stem"], r["stem"]) >= DUP_THRESHOLD for r in new):
                skipped += 1
                continue
            new.append(record(it, job_id=job_id, job_dir=job_dir, pattern_id=pattern_id, profile=profile,
                              critic_notes=critic.get(it["qno"])))
        if new:
            BANK.mkdir(parents=True, exist_ok=True)
            with open(FILE, "a", encoding="utf-8") as f:
                for r in new:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        added = len(new)
    return added, skipped


def stats() -> dict:
    rows = load()
    out: dict = {"total": len(rows), "by_section": {}}
    for r in rows:
        out["by_section"][r["section"]] = out["by_section"].get(r["section"], 0) + 1
    return out


if __name__ == "__main__":  # uv run python -m agents.bank <job_id> ...   (backfill finished jobs)
    import sys
    from pipeline.job import Job
    for jid in sys.argv[1:]:
        j = Job(jid)
        st = j.state()
        a, sk = add_job(j.load_items(), job_id=jid, job_dir=j.dir, pattern_id=st["config"]["pattern_id"],
                        profile=st["config"].get("profile") or "default")
        print(f"{jid}: added {a}, skipped {sk} near-duplicates")
    print(stats())
