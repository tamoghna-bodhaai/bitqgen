"""Solver / Verifier: blind solves by a different model family than the author.

Policy (per question):
  solver agrees with the key, single answer, no blocking issue  -> pass
  otherwise -> tiebreaker (third family) solves blind
      tiebreaker agrees with key and sees no multiple-correct    -> pass (noted as a 2-of-3 vote)
      else                                                       -> fail with feedback for the author
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.common import prompt
from core.llm import LLM, call_with_tools, image_part
from core.models import LETTERS, SolverVerdict

BLOCKING = ("missing", "ambiguous", "contradict", "no option", "insufficient", "not given", "unreadable",
            "two options", "multiple", "incorrect key", "inconsistent")


@dataclass
class Verification:
    passed: bool
    verdicts: list[dict] = field(default_factory=list)
    feedback: str = ""
    difficulty: Optional[int] = None
    cost: float = 0.0
    working: str = ""


def _messages(stem: str, options: list[str], figure: Optional[Path], option_figs: Optional[list[Path]]) -> list[dict]:
    lines = [stem] + [f"({L}) {o or '[see figure ' + L + ']'}" for L, o in zip(LETTERS, options)]
    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    if figure and figure.exists():
        content.append({"type": "text", "text": "Figure for the question:"})
        content.append(image_part(figure))
    for L, p in zip(LETTERS, option_figs or []):
        if p and p.exists():
            content.append({"type": "text", "text": f"Option ({L}):"})
            content.append(image_part(p))
    return [{"role": "system", "content": prompt("solver")}, {"role": "user", "content": content}]


def _blocking(v: SolverVerdict) -> list[str]:
    return [i for i in v.issues if any(b in i.lower() for b in BLOCKING)]


def solve(llm: LLM, stage: str, stem: str, options: list[str], figure: Optional[Path] = None,
          option_figs: Optional[list[Path]] = None):
    # Text-only checkers (GLM-5.3) hand figure questions to a "<stage>_vision" stage when one is configured.
    has_img = bool((figure and figure.exists()) or any(p and p.exists() for p in option_figs or []))
    if has_img and f"{stage}_vision" in llm.stages:
        stage = f"{stage}_vision"
    return call_with_tools(llm, stage, _messages(stem, options, figure, option_figs), schema=SolverVerdict)


def verify(llm: LLM, stem: str, options: list[str], key: str, figure: Optional[Path] = None,
           option_figs: Optional[list[Path]] = None, stage: str = "solver") -> Verification:
    """stage: "solver" (Physics/Chemistry/Maths) or "solver_verbal" (English / Logical Reasoning)."""
    out = Verification(passed=False)
    r1 = solve(llm, stage, stem, options, figure, option_figs)
    out.cost += r1.cost
    v1: Optional[SolverVerdict] = r1.data
    if v1 is not None:
        out.verdicts.append({"stage": stage, "model": r1.model, **v1.model_dump()})
        out.difficulty = v1.difficulty
        out.working = v1.working
        if v1.answer == key and not v1.multiple_correct and not _blocking(v1):
            out.passed = True
            return out
    else:
        out.verdicts.append({"stage": stage, "model": r1.model, "error": r1.error})

    r2 = solve(llm, "tiebreaker", stem, options, figure, option_figs)
    out.cost += r2.cost
    v2: Optional[SolverVerdict] = r2.data
    if v2 is not None:
        out.verdicts.append({"stage": "tiebreaker", "model": r2.model, **v2.model_dump()})
        if out.difficulty is None:
            out.difficulty = v2.difficulty
        if v2.answer == key and not v2.multiple_correct and not _blocking(v2) and \
                (v1 is None or not v1.multiple_correct):
            out.passed = True
            out.working = v2.working
            return out
    else:
        out.verdicts.append({"stage": "tiebreaker", "model": r2.model, "error": r2.error})

    fb = []
    for v in (v1, v2):
        if v is None:
            continue
        s = f"- An independent solver chose {v.answer} (confidence {v.confidence:.2f})"
        if v.multiple_correct:
            s += " and found more than one defensible option"
        s += f". Its working: {v.working[:900]}"
        if v.issues:
            s += " Issues: " + "; ".join(v.issues)
        fb.append(s)
    out.feedback = "\n".join(fb) or "- Solvers failed to return an answer; make the question clearer."
    return out
