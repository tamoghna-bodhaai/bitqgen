"""Paper-level stages: answer-key balancing, Critic, Solution Writer."""
from __future__ import annotations

import random
import re
from typing import Optional

from agents.common import nearest_corpus, prompt, q_text, similarity
from core.llm import LLM
from core.models import LETTERS, CriticReport, SolutionText

# options whose meaning depends on their position: never permute such questions
POSITIONAL = re.compile(r"none of|all of|both|neither|\(a\)|\(b\)|\(c\)|\(d\)|\ba and b\b|above", re.I)


def balance_answers(items: list[dict], rng: random.Random) -> int:
    """Permute options of movable questions so each section's key is ~uniform over A–D with no runs ≥3.

    `items`: dicts with keys qno, section, answer, options(list), option_figs(list|None), locked(bool).
    Mutates in place; returns the number of questions changed."""
    changed = 0
    for sec in dict.fromkeys(i["section"] for i in items):
        sec_items = sorted([i for i in items if i["section"] == sec], key=lambda i: i["qno"])
        n = len(sec_items)
        target = {L: n // 4 + (1 if k < n % 4 else 0) for k, L in enumerate(rng.sample(LETTERS, 4))}
        fixed = [i for i in sec_items if i["locked"] or any(POSITIONAL.search(o or "") for o in i["options"])]
        for i in fixed:
            target[i["answer"]] -= 1
        movable = [i for i in sec_items if i not in fixed]
        prev: list[str] = []
        by_q = {i["qno"]: i for i in sec_items}
        for it in sec_items:
            if it in movable:
                ranked = sorted(LETTERS, key=lambda L: (-(target[L]), rng.random()))
                choice = next((L for L in ranked if not (len(prev) >= 2 and prev[-1] == prev[-2] == L)), ranked[0])
                target[choice] -= 1
                if choice != it["answer"]:
                    a, b = LETTERS.index(it["answer"]), LETTERS.index(choice)
                    for key in ("options", "option_figs"):
                        if it.get(key):
                            it[key][a], it[key][b] = it[key][b], it[key][a]
                    it["answer"] = choice
                    changed += 1
            prev.append(by_q[it["qno"]]["answer"])
    return changed


def critic(llm: LLM, section: str, questions: list[dict]) -> Optional[CriticReport]:
    blocks = []
    for q in questions:
        blocks.append(f"### qno {q['qno']}  [{q.get('chapter', '')}]\n" + q_text(q["stem"], q["options"]) +
                      f"\nKey: {q['answer']}" + ("\n[has figure]" if q.get("has_figure") else ""))
    msgs = [{"role": "system", "content": prompt("critic")},
            {"role": "user", "content": f"Section: {section}\n\n" + "\n\n".join(blocks)}]
    res = llm.call("critic", msgs, schema=CriticReport)
    return res.data


def duplicate_flags(questions: list[dict], corpus_threshold: float = 0.55, paper_threshold: float = 0.6) -> dict[int, str]:
    """qno -> reason, for near-copies of past questions or of another question in the paper."""
    flags = {}
    for q in questions:
        ref, s = nearest_corpus(q["stem"])
        if s >= corpus_threshold:
            flags[q["qno"]] = f"too close to past question {ref} (similarity {s:.2f})"
    for i, a in enumerate(questions):
        for b in questions[i + 1:]:
            if len(a["stem"]) > 60 and similarity(a["stem"], b["stem"]) >= paper_threshold:
                flags.setdefault(b["qno"], f"near-duplicate of Q{a['qno']} in this paper")
    return flags


def write_solution(llm: LLM, section: str, stem: str, options: list[str], answer: str, working: str) -> str:
    msgs = [{"role": "system", "content": prompt("solution_writer")},
            {"role": "user", "content": f"Section: {section}\n\n{q_text(stem, options)}\n\n"
                                        f"Correct option: ({answer}) {options[LETTERS.index(answer)]}\n\n"
                                        "Verified working (from the solvers/author). Option letters inside it may "
                                        "refer to an older option order; trust the option text above:\n"
                                        f"{working}"}]
    res = llm.call("solution_writer", msgs, schema=SolutionText)
    if res.data:
        return res.data.solution.strip()
    working = working.split("\n\nIndependent check:")[0]
    # fallback: the author's working, minus sentences naming option letters (they may be stale)
    return re.sub(r"[^.\n]*\b[Oo]ption \(?[A-D]\)?[^.\n]*\.?", "", working).strip()
