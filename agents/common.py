"""Shared helpers for the generation agents: corpus access, exemplars, prompts, events."""
from __future__ import annotations

import json
import random
import re
from functools import lru_cache
from pathlib import Path

import yaml

from core.models import LETTERS, Paper, Question

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
PROMPTS = Path(__file__).resolve().parent / "prompts"
SYLLABUS = ROOT / "config" / "syllabus.yaml"
PROFILES = ROOT / "data" / "style" / "profiles.json"

PCM = ("Physics", "Chemistry", "Mathematics")


@lru_cache(maxsize=None)
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def load_syllabus() -> dict:
    return yaml.safe_load(SYLLABUS.read_text())


def load_profiles() -> dict:
    return json.loads(PROFILES.read_text())


@lru_cache(maxsize=None)
def corpus_papers() -> dict[str, Paper]:
    out = {}
    for d in sorted(CORPUS.iterdir()):
        f = d / "paper.json"
        if f.exists():
            out[d.name] = Paper(**json.loads(f.read_text()))
    return out


def corpus_question(ref: str) -> Question | None:
    pid, qno = ref.split(":")
    p = corpus_papers().get(pid)
    if not p:
        return None
    return next((q for q in p.questions if q.qno == int(qno)), None)


def all_corpus_questions() -> list[tuple[str, Question]]:
    return [(pid, q) for pid, p in corpus_papers().items() for q in p.questions]


def format_question(q: Question, *, with_solution: bool = True, label: str = "") -> str:
    lines = [f"{label}{q.stem}"]
    if q.figure:
        lines.append("[figure shown with the question]")
    for L, o in zip(LETTERS, q.options):
        lines.append(f"({L}) {o.text or o.alt or '[figure]'}")
    lines.append(f"Correct Option: {q.answer}")
    if with_solution and q.solution:
        lines.append(f"Solution: {q.solution}")
    return "\n".join(lines)


def exemplar_block(refs: list[str]) -> str:
    parts = []
    for i, r in enumerate(refs, 1):
        q = corpus_question(r)
        if q and q.exemplar_ok:
            meta = f"[{q.chapter} / {q.subtopic} / difficulty {q.difficulty}]"
            parts.append(f"--- Example {i} {meta}\n{format_question(q)}")
    return "\n\n".join(parts)


def pick_exemplars(rng: random.Random, section: str, topic: str, subtopic: str = "", k: int = 3) -> list[str]:
    ids = [i for i in load_profiles().get(section, {}).get("exemplars", {}).get(topic, [])
           if (q := corpus_question(i)) is None or q.exemplar_ok]
    if not ids:
        return []
    same = [i for i in ids if (q := corpus_question(i)) and subtopic and q.subtopic == subtopic]
    rest = [i for i in ids if i not in same]
    rng.shuffle(same)
    rng.shuffle(rest)
    return (same + rest)[:k]


def q_text(stem: str, options: list[str]) -> str:
    return stem + "\n" + "\n".join(f"({L}) {o}" for L, o in zip(LETTERS, options))


# ------------------------------------------------------------------ near-duplicate check

def _shingles(text: str, n: int = 5) -> set[str]:
    t = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


@lru_cache(maxsize=1)
def _corpus_shingles() -> list[tuple[str, set[str]]]:
    return [(f"{pid}:{q.qno}", _shingles(q.stem)) for pid, q in all_corpus_questions() if len(q.stem) > 60]


def nearest_corpus(stem: str) -> tuple[str, float]:
    """Most similar corpus stem by character-shingle Jaccard (0..1)."""
    s = _shingles(stem)
    if len(stem) <= 60:
        return "", 0.0
    best, score = "", 0.0
    for ref, cs in _corpus_shingles():
        j = len(s & cs) / max(1, len(s | cs))
        if j > score:
            best, score = ref, j
    return best, score


def similarity(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    return len(sa & sb) / max(1, len(sa | sb))
