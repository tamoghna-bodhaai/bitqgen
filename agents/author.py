"""Section Authors: write an original question for a Slot (or an RC set for a passage group)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from agents.common import PCM, exemplar_block, load_profiles, prompt, q_text
from pydantic import ValidationError

from core.llm import LLM, CallResult, close_truncated_json, repair_latex
from core.models import DraftBatch, DraftQuestion, Slot


class RCSet(BaseModel):
    passage: str
    questions: list[DraftQuestion]


def stage_for(slot: Slot) -> str:
    return "author_pcm" if slot.section in PCM else "author_verbal"


def solver_stage(slot: Slot) -> str:
    """Physics/Chemistry/Maths -> "solver"; English / Logical Reasoning -> "solver_verbal"."""
    return "solver" if slot.section in PCM else "solver_verbal"


LOWER = {"xhigh": "high", "high": "medium", "medium": "low", "low": "low"}


def reasoning_for(llm: LLM, slots: list[Slot]) -> Optional[str]:
    """Stage effort, or the cheaper `reasoning_easy` when every slot is difficulty <= 2."""
    st = llm.stage(stage_for(slots[0]))
    if st.get("reasoning_easy") and all(s.difficulty <= 2 for s in slots):
        return st["reasoning_easy"]
    return st.get("reasoning")


def salvage(obj, slot: Slot) -> Optional[DraftQuestion]:
    """A draft from a (possibly truncated) JSON object, if everything except the long tail is complete.

    Requires stem/options/answer/figure/difficulty_estimate and the start of `working` (fields are
    ordered so that these come first). A cut-off `working`/`distractor_notes` is acceptable: the
    solver's independent working is appended later and the solution writer works from both."""
    if not isinstance(obj, dict) or "working" not in obj:
        return None
    if slot.needs_figure and slot.section in PCM and not obj.get("figure"):
        return None
    d = dict(obj)
    d.setdefault("distractor_notes", "")
    d.setdefault("option_smiles", None)
    try:
        q = DraftQuestion.model_validate(repair_latex(d))
    except ValidationError:
        return None
    return q if len(q.options) == 4 and q.stem.strip() else None


def _finish(res: CallResult, slot: Slot) -> CallResult:
    """If the structured parse failed, try to recover the draft from a cut-off output."""
    if res.data is None and res.text:
        q = salvage(close_truncated_json(res.text), slot)
        if q is not None:
            res.data, res.error = q, f"salvaged truncated output ({res.error or res.finish_reason})"
    return res


def _slot_brief(slot: Slot) -> str:
    prof = load_profiles().get(slot.section, {})
    lines = [
        f"Section: {slot.section}",
        f"Chapter / topic: {slot.chapter}",
        f"Subtopic: {slot.subtopic or '(your choice within the chapter)'}",
    ]
    if slot.archetype:
        lines.append(f"Archetype: {slot.archetype}")
    if slot.brief:
        lines.append(f"Angle: {slot.brief}")
    lines.append(f"Target difficulty: {slot.difficulty}/5")
    if slot.section in PCM:
        lines.append(f"Figure: {'REQUIRED (kind: ' + str(slot.figure_kind) + ')' if slot.needs_figure else 'not needed — set figure to null unless unavoidable'}")
    lines.append(f"Typical stem length in past papers: ~{prof.get('median_stem_chars', 200)} characters.")
    return "\n".join(lines)


VARIANT_RULE = ("Write a NEW question that tests the same concept/skill at the target difficulty, but with a "
                "different physical setup or context, different numbers, and a different unknown asked. Do not "
                "reuse its sentences, its numbers or its option values.")


def seed_block(rec: dict) -> str:
    return ("Source question from our question bank (concept reference — the new question must be clearly "
            "different):\n" + q_text(rec["stem"], rec["options"]) + f"\nKey: {rec.get('answer')}\n\n" + VARIANT_RULE)


def write(llm: LLM, slot: Slot, *, feedback: Optional[str] = None,
          previous: Optional[DraftQuestion] = None, extra: str = "",
          seed_question: Optional[dict] = None) -> CallResult:
    stage = stage_for(slot)
    system = prompt("author_pcm" if stage == "author_pcm" else "author_verbal").replace("{section}", slot.section)
    user = [_slot_brief(slot)]
    ex = exemplar_block(slot.exemplar_ids)
    if ex:
        user.append("Past BITSAT questions on this topic (style/level reference only — do NOT copy):\n\n" + ex)
    if seed_question:
        user.append(seed_block(seed_question))
    if previous is not None and feedback:
        user.append("Your previous draft:\n" + q_text(previous.stem, previous.options) +
                    f"\nIntended key: {previous.answer}\nYour working: {previous.working}")
        user.append("Independent reviewers found these problems — fix them (rewrite the question if needed "
                    "so that exactly one option is unambiguously correct):\n" + feedback)
    if extra:
        user.append("Additional instruction from the editor: " + extra)
    user.append("Write the question now.")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(user)}]
    eff = reasoning_for(llm, [slot])
    res = _finish(llm.call(stage, msgs, schema=DraftQuestion, reasoning=eff), slot)
    if res.data is None and res.finish_reason == "length":
        # Cut off before the question was complete: the reasoning ate the budget. One retry with
        # less reasoning and more room, instead of a blind full rewrite by the job loop.
        mt = int(llm.stage(stage).get("max_tokens", 8000) * 1.5)
        llm.record(stage, length_retries=1)
        r2 = _finish(llm.call(stage, msgs, schema=DraftQuestion, reasoning=LOWER.get(eff or "", "low"),
                              max_tokens=mt), slot)
        r2.cost += res.cost
        res = r2
    return res


def write_batch(llm: LLM, slots: list[Slot]) -> tuple[list[Optional[DraftQuestion]], CallResult]:
    """Several questions for slots of the same section/chapter in ONE call: the style guide and the
    exemplars are sent once. Returns drafts aligned with `slots` (None where a question is missing
    or incomplete; the caller writes those one by one)."""
    stage = stage_for(slots[0])
    st = llm.stage(stage)
    system = prompt("author_pcm" if stage == "author_pcm" else "author_verbal").replace("{section}", slots[0].section)
    user = [f"Write {len(slots)} separate questions, one per brief below, in the same order. Each is "
            "independent: follow its own chapter, difficulty and figure instruction. The examples under a "
            "brief show style/level only — do NOT copy them."]
    for k, s in enumerate(slots, 1):
        ex = exemplar_block((s.exemplar_ids or [])[:2])
        user.append(f"### Brief {k}\n" + _slot_brief(s) + (f"\n\nPast BITSAT questions for brief {k}:\n\n{ex}" if ex else ""))
    user.append(f'Return a JSON object {{"questions": [...]}} with exactly {len(slots)} question objects.')
    msgs = [{"role": "system", "content": system.replace("Return only the JSON object.",
                                                         "Return only the JSON object described below.")},
            {"role": "user", "content": "\n\n".join(user)}]
    mt = st.get("batch_max_tokens") or int(st.get("max_tokens", 8000) * 2)
    res = llm.call(stage, msgs, schema=DraftBatch, reasoning=reasoning_for(llm, slots), max_tokens=mt)
    if res.data is not None:
        raw = [q.model_dump() for q in res.data.questions]
    else:
        obj = close_truncated_json(res.text) if res.text else None
        raw = obj.get("questions", []) if isinstance(obj, dict) else []
    out: list[Optional[DraftQuestion]] = []
    for k, s in enumerate(slots):
        out.append(salvage(raw[k], s) if k < len(raw) else None)
    llm.record(stage, batch_questions=sum(q is not None for q in out), batch_missing=sum(q is None for q in out))
    return out, res


def write_rc(llm: LLM, slots: list[Slot], extra: str = "") -> CallResult:
    ex = exemplar_block(slots[0].exemplar_ids)
    user = [f"Write a passage and exactly {len(slots)} questions. Target difficulty "
            f"{', '.join(str(s.difficulty) for s in slots)} (1–5)."]
    if ex:
        user.append("Past BITSAT RC questions (style only):\n\n" + ex)
    if extra:
        user.append("Additional instruction from the editor: " + extra)
    msgs = [{"role": "system", "content": prompt("author_rc")}, {"role": "user", "content": "\n\n".join(user)}]
    return llm.call("author_verbal", msgs, schema=RCSet)


def lint(d: DraftQuestion) -> list[str]:
    """Cheap structural checks before spending a solver call."""
    errs = []
    if len(d.options) != 4:
        errs.append(f"must have exactly 4 options (got {len(d.options)})")
    elif len({o.strip().lower() for o in d.options}) < 4 and not d.option_smiles:
        errs.append("options are not distinct")
    if d.option_smiles is not None and len(d.option_smiles) != 4:
        errs.append("option_smiles must have exactly 4 entries")
    if d.stem.count("$") % 2:
        errs.append("unbalanced $ in stem")
    for i, o in enumerate(d.options):
        if o.count("$") % 2:
            errs.append(f"unbalanced $ in option {'ABCD'[i]}")
    if len(d.stem.strip()) < 15:
        errs.append("stem too short")
    return errs
