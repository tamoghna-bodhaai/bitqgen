"""Build config/syllabus.yaml and data/style/profiles.json from the extracted corpus.

    uv run python -m ingest.syllabus

Syllabus = official BITSAT units (admissions brochure; NCERT 11–12 based) x corpus chapters.
Each planner "topic" carries a weight = smoothed, recency-weighted share of corpus questions.
English and Logical Reasoning are planned at question-type level (synonyms, syllogism, mirror
image ...), because that is how those sections vary. The YAML is meant to be hand-edited
(weights, enabled flags) in the UI; re-running this script overwrites it.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from core.models import Paper

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
SYLLABUS = ROOT / "config" / "syllabus.yaml"
PROFILES = ROOT / "data" / "style" / "profiles.json"

# Recent papers count more: the 2026 papers are visibly harder than 2024–25.
RECENCY = {"2026": 2.0, "2025": 1.5, "2024": 1.0, "2023": 0.8, "2022": 0.7, "2021": 0.6}

# Questions whose notes contain these are not used as exemplars or for difficulty stats.
BAD_NOTE = re.compile(r"doubtful|missing|garbled|misplaced|duplicate|not bitsat|wrong key|source key",
                      re.I)

OFFICIAL = {
    "Physics": {
        "Units and Measurement": ["Units and Measurements"],
        "Kinematics": ["Kinematics"],
        "Newton's Laws of Motion": ["Laws of Motion"],
        "Impulse, Work and Energy": ["Work, Energy and Power"],
        "Rotational Motion": ["Rotational Motion"],
        "Gravitation": ["Gravitation"],
        "Mechanics of Solids and Fluids": ["Mechanical Properties of Solids", "Mechanical Properties of Fluids"],
        "Oscillations": ["Oscillations"],
        "Waves": ["Waves"],
        "Heat and Thermodynamics": ["Thermodynamics", "Thermal Properties of Matter", "Kinetic Theory of Gases"],
        "Electrostatics": ["Electrostatics", "Capacitance"],
        "Current Electricity": ["Current Electricity"],
        "Magnetic Effect of Current": ["Moving Charges and Magnetism", "Magnetism and Matter"],
        "Electromagnetic Induction": ["Electromagnetic Induction", "Alternating Current", "Electromagnetic Waves"],
        "Optics": ["Ray Optics", "Wave Optics"],
        "Modern Physics": ["Dual Nature of Radiation and Matter", "Atoms", "Nuclei"],
        "Electronic Devices": ["Semiconductor Electronics"],
    },
    "Chemistry": {
        "States of Matter": ["States of Matter", "Solid State", "Solutions", "Some Basic Concepts of Chemistry"],
        "Atomic Structure": ["Structure of Atom", "Classification of Elements and Periodicity"],
        "Chemical Bonding and Molecular Structure": ["Chemical Bonding"],
        "Thermodynamics": ["Thermodynamics (Chemistry)"],
        "Physical and Chemical Equilibria": ["Equilibrium", "Redox Reactions"],
        "Electrochemistry": ["Electrochemistry"],
        "Chemical Kinetics": ["Chemical Kinetics", "Surface Chemistry"],
        "Hydrogen and s-block Elements": ["Hydrogen", "s-Block Elements"],
        "p-, d- and f-block Elements": ["p-Block Elements", "d- and f-Block Elements", "Coordination Compounds",
                                        "Metallurgy"],
        "Principles of Organic Chemistry and Hydrocarbons": ["Organic Chemistry – Basic Principles", "Hydrocarbons"],
        "Stereochemistry": ["Stereochemistry"],
        "Organic Compounds with Functional Groups (O, N)": [
            "Alcohols, Phenols and Ethers", "Aldehydes, Ketones and Carboxylic Acids", "Amines",
            "Haloalkanes and Haloarenes"],
        "Biological, Industrial and Environmental Chemistry": [
            "Biomolecules", "Polymers", "Environmental Chemistry", "Chemistry in Everyday Life"],
        "Theoretical Principles of Experimental Chemistry": ["Practical Chemistry"],
    },
    "Mathematics": {
        "Algebra": ["Complex Numbers", "Quadratic Equations", "Sequences and Series", "Binomial Theorem",
                    "Permutations and Combinations", "Matrices and Determinants", "Sets, Relations and Functions",
                    "Mathematical Reasoning", "Linear Inequalities"],
        "Trigonometry": ["Trigonometry", "Inverse Trigonometric Functions"],
        "Two-dimensional Coordinate Geometry": ["Coordinate Geometry", "Conic Sections"],
        "Three-dimensional Coordinate Geometry": ["Three Dimensional Geometry"],
        "Differential Calculus": ["Limits and Continuity", "Differential Calculus"],
        "Integral Calculus": ["Integral Calculus"],
        "Ordinary Differential Equations": ["Differential Equations"],
        "Probability": ["Probability"],
        "Vectors": ["Vector Algebra"],
        "Statistics": ["Statistics"],
        "Linear Programming": ["Linear Programming"],
    },
}

# English / LR: question-type topics. `match` = regex on corpus subtopic; `generator` = the
# deterministic figure generator that builds the item (answer correct by construction).
TYPED = {
    "English Proficiency": {
        "Synonyms": {"unit": "Vocabulary", "match": r"synonym"},
        "Antonyms": {"unit": "Vocabulary", "match": r"antonym"},
        "Idioms and Phrases": {"unit": "Vocabulary", "match": r"idiom|phrasal"},
        "Sentence Completion (vocabulary)": {"unit": "Vocabulary", "match": r"sentence completion|spelling|analogy"},
        "Error Spotting / Sentence Improvement": {"unit": "Grammar",
                                                  "match": r"agreement|gerund|correlative|parallel|dangling|preposition|inversion|stative|tense|subjunctive|used to"},
        "Active and Passive Voice": {"unit": "Grammar", "match": r"passive"},
        "Sentence Rearrangement (para jumbles)": {"unit": "Composition", "match": r"rearrange"},
        "Reading Comprehension": {"unit": "Reading Comprehension", "match": r"main idea|inference|detail"},
    },
    "Logical Reasoning": {
        "Syllogism": {"unit": "Verbal Reasoning", "match": r"syllogism"},
        "Coding-Decoding": {"unit": "Verbal Reasoning", "match": r"coding|mathematical operations"},
        "Blood Relations": {"unit": "Verbal Reasoning", "match": r"blood"},
        "Classification (odd one out)": {"unit": "Verbal Reasoning", "match": r"classification"},
        "Letter / Number Series": {"unit": "Verbal Reasoning", "match": r"letter series|alpha-numeric|word series|date series"},
        "Analogy": {"unit": "Verbal Reasoning", "match": r"analogy"},
        "Word Formation / Dictionary Order": {"unit": "Verbal Reasoning", "match": r"word formation|dictionary|logical sequence"},
        "Direction Sense": {"unit": "Verbal Reasoning", "match": r"direction"},
        "Seating / Ranking Puzzle": {"unit": "Verbal Reasoning", "match": r"seating|ranking"},
        "Mirror Image": {"unit": "Non-verbal Reasoning", "match": r"mirror", "generator": "mirror_image"},
        "Water Image": {"unit": "Non-verbal Reasoning", "match": r"water image", "generator": "water_image"},
        "Paper Folding and Punching": {"unit": "Non-verbal Reasoning", "match": r"paper fold|transparent",
                                       "generator": "paper_punch"},
        "Figure Series": {"unit": "Non-verbal Reasoning", "match": r"figure series|symbol series",
                          "generator": "rotation_series"},
        "Cube and Dice": {"unit": "Non-verbal Reasoning", "match": r"cube|dice", "generator": "cube_net"},
        "Number Puzzle in Figures": {"unit": "Non-verbal Reasoning", "match": r"number puzzle|number matrix",
                                     "generator": "number_grid"},
        "Odd Figure Out": {"unit": "Non-verbal Reasoning", "match": r"odd figure|figure completion|embedded|formation",
                           "generator": "odd_figure"},
        "Counting Figures": {"unit": "Non-verbal Reasoning", "match": r"counting", "generator": "count_triangles"},
    },
}

SECTIONS = ["Physics", "Chemistry", "English Proficiency", "Logical Reasoning", "Mathematics"]


def load_corpus() -> dict[str, Paper]:
    out = {}
    for d in sorted(CORPUS.iterdir()):
        f = d / "paper.json"
        if f.exists():
            out[d.name] = Paper(**json.loads(f.read_text()))
    return out


def topic_of(section: str, q) -> str | None:
    """Map a corpus question to its planner topic (chapter for PCM, question type for E/LR)."""
    if section in TYPED:
        sub = (q.subtopic or "").lower()
        for name, t in TYPED[section].items():
            if re.search(t["match"], sub):
                return name
        return None
    known = {c for chs in OFFICIAL[section].values() for c in chs}
    return q.chapter if q.chapter in known else None


def clean(q) -> bool:
    return q.exemplar_ok and not (q.notes and BAD_NOTE.search(q.notes))


def has_fig(q) -> bool:
    return bool(q.figure) or any(o.figure for o in q.options)


def build() -> tuple[dict, dict]:
    corpus = load_corpus()
    counts = defaultdict(Counter)          # section -> topic -> weighted count
    raw = defaultdict(Counter)             # section -> topic -> raw count
    figs = defaultdict(Counter)
    subtopics = defaultdict(lambda: defaultdict(Counter))
    archetypes = defaultdict(lambda: defaultdict(Counter))
    exemplars = defaultdict(lambda: defaultdict(list))
    diff = defaultdict(Counter)
    stem_len = defaultdict(list)
    none_opt = Counter()
    sec_total = Counter()
    for pid, paper in corpus.items():
        w = RECENCY.get(pid[:4], 1.0)
        for q in paper.questions:
            t = topic_of(q.section, q)
            if t is None:
                continue
            counts[q.section][t] += w
            raw[q.section][t] += 1
            figs[q.section][t] += has_fig(q)
            if q.subtopic:
                subtopics[q.section][t][q.subtopic] += 1
            if q.archetype:
                archetypes[q.section][t][q.archetype] += 1
            sec_total[q.section] += 1
            if clean(q):
                exemplars[q.section][t].append(f"{pid}:{q.qno}")
                if q.difficulty:
                    diff[q.section][q.difficulty] += w
                stem_len[q.section].append(len(q.stem))
                none_opt[q.section] += any(re.match(r"none of|all of|both", o.text.strip(), re.I)
                                           for o in q.options)

    syl: dict = {"_source": ("Official BITSAT units (BITS admissions brochure, NCERT 11-12) x chapters "
                             "seen in the extracted corpus. weight = recency-weighted corpus share "
                             "(+0.5 smoothing). Edit weights / enabled freely."),
                 "sections": {}}
    for sec in SECTIONS:
        topics = []
        if sec in TYPED:
            items = [(name, t["unit"], t.get("generator")) for name, t in TYPED[sec].items()]
        else:
            items = [(ch, unit, None) for unit, chs in OFFICIAL[sec].items() for ch in chs]
        tot = sum(counts[sec].get(n, 0) + 0.5 for n, _, _ in items)
        for name, unit, gen in items:
            n = raw[sec].get(name, 0)
            topic = {
                "name": name, "unit": unit,
                "weight": round((counts[sec].get(name, 0) + 0.5) / tot, 4),
                "corpus_count": n,
                "figure_rate": round(figs[sec][name] / n, 2) if n else 0.0,
                "enabled": True,
                "subtopics": [s for s, _ in subtopics[sec][name].most_common(12)],
            }
            if gen:
                topic["generator"] = gen
            topics.append(topic)
        syl["sections"][sec] = {"topics": topics}

    prof = {}
    for sec in SECTIONS:
        dt = sum(diff[sec].values()) or 1
        prof[sec] = {
            "questions_seen": sec_total[sec],
            "difficulty_dist": {str(k): round(v / dt, 3) for k, v in sorted(diff[sec].items())},
            "median_stem_chars": int(statistics.median(stem_len[sec])) if stem_len[sec] else 0,
            "none_of_these_rate": round(none_opt[sec] / max(1, len(stem_len[sec])), 3),
            "archetypes": {t: [a for a, _ in c.most_common(10)] for t, c in archetypes[sec].items()},
            "exemplars": {t: ids for t, ids in exemplars[sec].items()},
        }
    return syl, prof


def main() -> None:
    syl, prof = build()
    SYLLABUS.write_text(yaml.safe_dump(syl, sort_keys=False, allow_unicode=True, width=110))
    PROFILES.parent.mkdir(parents=True, exist_ok=True)
    PROFILES.write_text(json.dumps(prof, indent=1, ensure_ascii=False))
    for sec, s in syl["sections"].items():
        top = sorted(s["topics"], key=lambda t: -t["weight"])[:5]
        print(f"{sec:20s} {len(s['topics'])} topics; top: " + ", ".join(f"{t['name']} {t['weight']:.2f}" for t in top))
        print(f"{'':20s} difficulty {prof[sec]['difficulty_dist']}")


if __name__ == "__main__":
    main()
