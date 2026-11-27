"""Blueprint Planner: pattern + syllabus weights + difficulty target -> one Slot per question.

Code fixes the hard constraints (section counts, topic quotas, difficulty mix, figure flags,
LR generators, RC grouping, exemplars). The LLM (planner stage) only fills subtopic / archetype /
brief per slot so questions on the same chapter differ. If that call fails, slots fall back to
past-paper subtopics, so planning never blocks generation.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Optional

from pydantic import BaseModel

from agents.common import PCM, load_profiles, load_syllabus, pick_exemplars, prompt
from core.llm import LLM
from core.models import Blueprint, Pattern, Slot

# difficulty knob -> exponential tilt applied to the corpus difficulty distribution
DIFFICULTY_TILT = {"easier": -0.6, "match": 0.0, "harder": 0.6, "much_harder": 1.2}


class PlanRow(BaseModel):
    qno: int
    subtopic: str
    archetype: str
    brief: str


class PlanSection(BaseModel):
    rows: list[PlanRow]


def allocate(rng: random.Random, topics: list[dict], n: int) -> list[str]:
    """Largest-remainder quota by weight, with random tie-breaking on the remainders."""
    tot = sum(t["weight"] for t in topics) or 1.0
    quotas = [(t["name"], n * t["weight"] / tot) for t in topics]
    out = {name: int(math.floor(q)) for name, q in quotas}
    left = n - sum(out.values())
    rema = sorted(quotas, key=lambda x: -(x[1] - math.floor(x[1]) + rng.random() * 0.35))
    for name, _ in rema[:left]:
        out[name] += 1
    return [name for name, k in out.items() for _ in range(k)]


def difficulty_sampler(rng: random.Random, dist: dict[str, float], tilt: float) -> Callable[[], int]:
    ks = [1, 2, 3, 4, 5]
    base = [dist.get(str(k), 0.0) + 0.01 for k in ks]
    w = [b * math.exp(tilt * k) for b, k in zip(base, ks)]
    return lambda: rng.choices(ks, weights=w)[0]


def plan(pattern: Pattern, *, seed: int = 0, difficulty: str = "match", llm: Optional[LLM] = None,
         log: Callable[[str], None] = print, sections: Optional[list[str]] = None) -> Blueprint:
    rng = random.Random(seed)
    syl = load_syllabus()["sections"]
    prof = load_profiles()
    tilt = DIFFICULTY_TILT.get(difficulty, 0.0)
    slots: list[Slot] = []
    for sec_name, start, end in pattern.section_ranges():
        n = end - start + 1
        if sections and sec_name not in sections:
            continue
        topics = [t for t in syl[sec_name]["topics"] if t.get("enabled", True) and t["weight"] > 0]
        names = allocate(rng, topics, n)
        by_name = {t["name"]: t for t in topics}
        # English RC: one passage set of 2–4 questions, or none
        if sec_name == "English Proficiency":
            rc = [x for x in names if x == "Reading Comprehension"]
            if len(rc) == 1:
                donor = max(set(names) - {"Reading Comprehension"}, key=names.count)
                names.remove(donor)
                names.append("Reading Comprehension")
            elif len(rc) > 4:
                for _ in range(len(rc) - 4):
                    names.remove("Reading Comprehension")
                    names.append("Synonyms")
        rng.shuffle(names)
        if sec_name == "English Proficiency":  # passage set goes last, as in the papers
            names = [x for x in names if x != "Reading Comprehension"] + \
                    [x for x in names if x == "Reading Comprehension"]
        draw = difficulty_sampler(rng, prof[sec_name]["difficulty_dist"], tilt)
        for i, topic in enumerate(names):
            t = by_name[topic]
            gen = t.get("generator")
            needs_fig = bool(gen) or (sec_name in PCM and rng.random() < min(0.6, t.get("figure_rate", 0)))
            unit = t.get("unit", "")
            kind = None
            if gen:
                kind = "lr"
            elif needs_fig:
                kind = "chem" if sec_name == "Chemistry" else "plot" if unit in (
                    "Differential Calculus", "Integral Calculus", "Two-dimensional Coordinate Geometry") else \
                    ("circuit" if topic in ("Current Electricity", "Capacitance", "Alternating Current",
                                             "Semiconductor Electronics") else "diagram")
            subs = t.get("subtopics") or []
            slot = Slot(qno=start + i, section=sec_name, chapter=topic, difficulty=draw(),
                        needs_figure=needs_fig, figure_kind=kind, lr_generator=gen,
                        subtopic=rng.choice(subs) if subs else "",
                        passage_id="rc1" if topic == "Reading Comprehension" else None)
            slot.exemplar_ids = pick_exemplars(rng, sec_name, topic, slot.subtopic)
            slots.append(slot)
        log(f"planned {sec_name}: {n} slots")

    if llm is not None:
        for sec_name, _, _ in pattern.section_ranges():
            sec_slots = [s for s in slots if s.section == sec_name and not s.lr_generator
                         and s.chapter != "Reading Comprehension"]
            if sec_slots:
                _refine(llm, sec_name, sec_slots, syl[sec_name]["topics"], prof[sec_name], log)
    return Blueprint(pattern_id=pattern.id, slots=slots)


def _refine(llm: LLM, section: str, slots: list[Slot], topics: list[dict], prof: dict, log) -> None:
    by = {t["name"]: t for t in topics}
    lines = []
    for s in slots:
        t = by.get(s.chapter, {})
        arch = prof.get("archetypes", {}).get(s.chapter, [])[:6]
        lines.append(f"qno {s.qno} | chapter: {s.chapter} | difficulty {s.difficulty}/5 | "
                     f"figure: {'yes (' + str(s.figure_kind) + ')' if s.needs_figure else 'no'} | "
                     f"seen subtopics: {', '.join(t.get('subtopics', [])[:8])} | seen archetypes: {', '.join(arch)}")
    msgs = [{"role": "system", "content": prompt("planner")},
            {"role": "user", "content": f"Section: {section}\n\n" + "\n".join(lines)}]
    res = llm.call("planner", msgs, schema=PlanSection)
    if res.data is None:
        log(f"planner LLM failed for {section} ({res.error}); using past-paper subtopics")
        return
    rows = {r.qno: r for r in res.data.rows}
    for s in slots:
        r = rows.get(s.qno)
        if r:
            s.subtopic, s.archetype, s.brief = r.subtopic, r.archetype, r.brief
    log(f"planner refined {section}: {len(rows)}/{len(slots)} slots (${res.cost:.3f})")
