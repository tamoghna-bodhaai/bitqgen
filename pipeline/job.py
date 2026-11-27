"""Orchestrator: runs a generation job end to end and persists every step under data/jobs/<id>/.

    data/jobs/<id>/
      job.json        config + status + progress + cost
      events.jsonl    progress log (streamed to the UI over SSE)
      blueprint.json  planner output
      items/<qno>.json per-question state (drafts, verdicts, figures, flags)
      figs/           rendered figures (the paper's asset dir is the job dir)
      paper.json      final Paper (single source of truth for the renderer)
      exports/        PDF / DOCX / HTML

CLI:  uv run python -m pipeline.job --counts Physics=2,Chemistry=2 --profile balanced
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field

from agents import author, bank, figure as figure_agent, finish, planner, verify
from agents.common import PCM
from core.llm import LLM, FatalLLMError
from core.models import (LETTERS, Blueprint, DraftQuestion, Figure, Option, Paper, Pattern, Question,
                         SectionSpec, Slot)
from figures import chem
from figures.lr.generators import GENERATORS
from render.html import load_pattern

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "jobs"
RC_INTRO = "Read the following passage carefully and answer the questions that follow."


class JobConfig(BaseModel):
    title: str = "BITSAT Practice Paper"
    subtitle: str = ""
    pattern_id: str = "bitsat_130"
    counts: Optional[dict[str, int]] = None   # override section counts (mini papers / testing)
    profile: Optional[str] = None             # models.yaml profile (default: active_profile)
    difficulty: str = "match"                 # easier | match | harder | much_harder
    seed: int = Field(default_factory=lambda: random.randint(1, 10 ** 6))
    workers: int = 24
    batch_size: int = 4                       # questions per author call (same section + difficulty band); 1 = off
    max_revisions: int = 2
    run_critic: bool = True
    check_figures: bool = True
    export: bool = True
    add_to_bank: bool = True                  # append verified questions to data/bank (annotated)
    source: str = "new"                       # new | direct | variant | mixed  (where questions come from)
    mix: Optional[dict[str, int]] = None      # mixed: {"direct": %, "variant": %, "new": %} per section


class Job:
    """One generation run. Thread-safe progress logging; state on disk so the UI can read it."""

    def __init__(self, job_id: str):
        self.id = job_id
        self.dir = JOBS / job_id
        self.items_dir = self.dir / "items"
        self._lock = threading.Lock()
        self.cancelled = threading.Event()
        self._llm: Optional[LLM] = None
        self._critic_notes: dict[int, str] = {}

    # ------------------------------------------------------------------ persistence
    @classmethod
    def create(cls, cfg: JobConfig) -> "Job":
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        job = cls(jid)
        job.items_dir.mkdir(parents=True, exist_ok=True)
        (job.dir / "figs").mkdir(exist_ok=True)
        job.write_state({"id": jid, "config": cfg.model_dump(), "status": "queued", "stage": "queued",
                         "created": time.time(), "progress": {"total": 0, "done": 0, "ok": 0, "flagged": 0},
                         "cost": 0.0})
        return job

    @property
    def cfg(self) -> JobConfig:
        return JobConfig(**self.state()["config"])

    def state(self) -> dict:
        return json.loads((self.dir / "job.json").read_text())

    def write_state(self, st: dict) -> None:
        tmp = self.dir / "job.json.tmp"
        tmp.write_text(json.dumps(st, indent=1))
        tmp.replace(self.dir / "job.json")

    def update(self, **kw) -> None:
        with self._lock:
            st = self.state()
            for k, v in kw.items():
                if k == "progress":
                    st["progress"].update(v)
                else:
                    st[k] = v
            if self._llm is not None:
                st["cost"] = round(self._llm.total_cost, 4)
                st["cost_by_stage"] = json.loads(json.dumps(getattr(self._llm, "stats", {})))
            self.write_state(st)

    def log(self, msg: str, *, stage: str = "", qno: Optional[int] = None, level: str = "info") -> None:
        ev = {"t": round(time.time(), 2), "stage": stage, "msg": msg, "level": level}
        if qno is not None:
            ev["qno"] = qno
        with self._lock:
            with open(self.dir / "events.jsonl", "a") as f:
                f.write(json.dumps(ev) + "\n")

    def save_item(self, it: dict) -> None:
        (self.items_dir / f"{it['qno']:03d}.json").write_text(json.dumps(it, indent=1, ensure_ascii=False))

    def load_items(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.items_dir.glob("*.json"))]

    def load_item(self, qno: int) -> dict:
        return json.loads((self.items_dir / f"{qno:03d}.json").read_text())

    def paper(self) -> Optional[Paper]:
        p = self.dir / "paper.json"
        return Paper(**json.loads(p.read_text())) if p.exists() else None

    def save_paper(self, paper: Paper) -> None:
        (self.dir / "paper.json").write_text(paper.model_dump_json(indent=1, exclude_none=True))

    @property
    def llm(self) -> LLM:
        if self._llm is None:
            llm = LLM(self.cfg.profile)
            # carry over spend from earlier runs of this job (resume / regenerate in a new process or Job
            # object), otherwise the first update() overwrites the saved total with this run's cost only
            st = self.state()
            llm.total_cost = float(st.get("cost") or 0.0)
            llm.stats = json.loads(json.dumps(st.get("cost_by_stage") or {}))
            self._llm = llm
        return self._llm

    # ------------------------------------------------------------------ pattern
    def pattern(self) -> Pattern:
        cfg = self.cfg
        base = load_pattern(cfg.pattern_id)
        if cfg.counts:
            order = [s.name for s in base.sections] if base else list(cfg.counts)
            secs = [SectionSpec(name=n, count=cfg.counts[n]) for n in order if cfg.counts.get(n)]
            return Pattern(id=cfg.pattern_id, title=(base.title if base else cfg.pattern_id) + " (custom)",
                           sections=secs)
        return base

    # ------------------------------------------------------------------ main run
    def run(self) -> None:
        try:
            self._run()
        except FatalLLMError as e:
            self.cancelled.set()
            self.log(str(e) + " — job stopped. Fix the key/credit limit, then use Resume.", stage="error",
                     level="error")
            self.update(status="failed", stage="failed", error=str(e))
        except Exception as e:  # noqa: BLE001 — surface any crash in the UI
            self.log(f"job crashed: {e!r}\n{traceback.format_exc()[-2000:]}", stage="error", level="error")
            self.update(status="failed", stage="failed", error=repr(e))

    def _run(self) -> None:
        cfg = self.cfg
        self.update(status="running", stage="planning", started=time.time())
        pat = self.pattern()
        self.log(f"pattern {pat.title}: {pat.total} questions; profile {self.llm.profile_name}; "
                 f"difficulty {cfg.difficulty}; seed {cfg.seed}", stage="plan")
        bp_file = self.dir / "blueprint.json"
        if bp_file.exists():  # resume: keep the plan and every verified question
            bp = Blueprint(**json.loads(bp_file.read_text()))
            done = {i["qno"] for i in self.load_items() if i.get("status") == "ok"}
            todo = [s for s in bp.slots if s.qno not in done]
            self.log(f"resuming: {len(done)} verified question(s) kept, {len(todo)} to generate", stage="plan")
        else:
            bp = planner.plan(pat, seed=cfg.seed, difficulty=cfg.difficulty, llm=self.llm,
                              log=lambda m: self.log(m, stage="plan"))
            if cfg.source != "new":
                self._assign_sources(bp)
            bp_file.write_text(bp.model_dump_json(indent=1))
            todo = bp.slots
        self.update(progress={"total": len(bp.slots)}, stage="generating")

        # ---- generate (RC passage groups as a unit)
        groups: list[list[Slot]] = []
        rc: dict[str, list[Slot]] = {}
        rc_ids = {s.passage_id for s in todo if s.passage_id}
        todo = [s for s in bp.slots if s in todo or (s.passage_id and s.passage_id in rc_ids)]
        batchable: dict[tuple, list[Slot]] = {}
        for s in todo:
            if s.passage_id:
                rc.setdefault(s.passage_id, []).append(s)
            elif s.lr_generator or cfg.batch_size <= 1 or s.origin != "new":
                groups.append([s])
            else:  # same section + difficulty band -> one author call writes several (shared style guide)
                batchable.setdefault((s.section, s.difficulty <= 2), []).append(s)
        for slots in batchable.values():
            for k in range(0, len(slots), cfg.batch_size):
                groups.append(slots[k:k + cfg.batch_size])
        groups += list(rc.values())
        with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
            futs = [ex.submit(self._run_group, g) for g in groups]
            for f in as_completed(futs):
                f.result()
        if self.cancelled.is_set():
            return self._cancel()
        refs = [s.bank_ref for s in bp.slots if s.bank_ref and s.origin in ("direct", "variant")]
        if refs:
            bank.mark_used(refs, self.id)

        # ---- critic + duplicate check -> one regeneration round
        items = self.load_items()
        redo: dict[int, str] = {}
        flags = finish.duplicate_flags([{"qno": i["qno"], "stem": i["stem"]} for i in items if i.get("stem")])
        redo.update(flags)
        for i in items:  # also keep away from questions already used in earlier generated papers
            if i.get("stem") and not i["slot"].get("lr_generator") and i["qno"] not in redo \
                    and i.get("origin") != "bank":
                bid, sc = bank.nearest(i["stem"])
                if sc >= 0.6:
                    redo[i["qno"]] = f"too close to an earlier generated question ({bid}, similarity {sc:.2f})"
        if cfg.run_critic:
            self.update(stage="critic")
            sections = list(dict.fromkeys(i["section"] for i in items))

            def crit(sec):
                qs = [{"qno": i["qno"], "stem": i["stem"], "options": i["options"], "answer": i["answer"],
                       "chapter": i["slot"]["chapter"], "has_figure": bool(i.get("figure"))}
                      for i in items if i["section"] == sec and i.get("stem")]
                return sec, finish.critic(self.llm, sec, qs)

            with ThreadPoolExecutor(max_workers=5) as ex:
                for sec, rep in ex.map(crit, sections):
                    if rep is None:
                        self.log(f"critic failed for {sec}", stage="critic", level="warn")
                        continue
                    self.log(f"{sec}: {rep.summary}", stage="critic")
                    for it in rep.items:
                        self.log(f"[{it.severity}] {it.problem}", stage="critic", qno=it.qno)
                        if it.severity != "major":  # major ones are regenerated, so the note would be stale
                            self._critic_notes[it.qno] = f"[{it.severity}] {it.problem}"
                        if it.severity == "major":
                            redo[it.qno] = (redo.get(it.qno, "") + " " + it.problem).strip()
        by_q = {i["qno"]: i for i in items}
        redo = {q: r for q, r in redo.items() if q in by_q and not by_q[q]["slot"].get("lr_generator")
                and not by_q[q]["slot"].get("passage_id") and by_q[q].get("origin") != "bank"}
        if redo:
            self.update(stage="revising")
            self.log(f"regenerating {len(redo)} question(s) flagged by critic/duplicate check", stage="revise")
            with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
                list(ex.map(lambda kv: self._run_slot(Slot(**by_q[kv[0]]["slot"]),
                                                      critic_feedback=kv[1], prev_item=by_q[kv[0]]), redo.items()))
        if self.cancelled.is_set():
            return self._cancel()

        # ---- balance key, write solutions, assemble
        self.update(stage="solutions")
        items = self.load_items()
        movable = [{"qno": i["qno"], "section": i["section"], "answer": i["answer"], "options": i["options"],
                    "option_figs": i.get("option_figs"), "locked": bool(i.get("locked") or i.get("solution"))}
                   for i in items if i.get("stem")]
        n = finish.balance_answers(movable, random.Random(cfg.seed))
        mv = {m["qno"]: m for m in movable}
        for i in items:
            if i["qno"] in mv:
                i["answer"], i["options"], i["option_figs"] = mv[i["qno"]]["answer"], mv[i["qno"]]["options"], \
                    mv[i["qno"]]["option_figs"]
                self.save_item(i)
        self.log(f"answer key balanced ({n} questions re-ordered)", stage="assemble")

        def sol(i):
            if not i.get("solution") and i.get("stem"):
                i["solution"] = finish.write_solution(self.llm, i["section"], i["stem"], i["options"],
                                                      i["answer"], i.get("working", ""))
                self.save_item(i)
                self.update()
        with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
            list(ex.map(sol, items))
        self.assemble()
        if cfg.add_to_bank:
            a, sk = bank.add_job(self.load_items(), job_id=self.id, job_dir=self.dir, pattern_id=cfg.pattern_id,
                                 profile=self.llm.profile_name, critic=self._critic_notes)
            self.log(f"question bank: +{a} verified question(s)" + (f", {sk} near-duplicate(s) skipped" if sk else ""),
                     stage="assemble")
        if cfg.export:
            self.update(stage="exporting")
            self.export()
        st = self.state()
        self.update(status="done", stage="done", finished=time.time())
        self.log(f"done: {st['progress'].get('ok', 0)} verified, {st['progress'].get('flagged', 0)} flagged; "
                 f"cost ${self.llm.total_cost:.2f}", stage="done")
        self.log("cost by stage: " + ", ".join(f"{k} ${v['cost']:.2f} ({v['calls']} calls"
                                                + (f", {v['truncated']} cut off" if v.get('truncated') else "") + ")"
                                                for k, v in sorted(self.llm.stats.items(),
                                                                   key=lambda kv: -kv[1]['cost'])), stage="done")

    def _cancel(self) -> None:
        self.update(status="cancelled", stage="cancelled")
        self.log("cancelled", stage="done", level="warn")

    # ------------------------------------------------------------------ per question
    def _run_group(self, group: list[Slot]) -> None:
        if self.cancelled.is_set():
            return
        try:
            if group[0].origin == "direct":
                self._run_direct(group[0])
            elif group[0].passage_id:
                self._run_rc(group)
            elif len(group) > 1:
                self._run_batch(group)
            else:
                self._run_slot(group[0])
        except FatalLLMError:
            self.cancelled.set()
            raise
        except Exception as e:  # noqa: BLE001
            s = group[0]
            self.log(f"error: {e!r}", stage="error", qno=s.qno, level="error")
            self.save_item({"qno": s.qno, "section": s.section, "slot": s.model_dump(), "status": "failed",
                            "notes": [f"pipeline error: {e!r}"], "stem": "", "options": ["", "", "", ""],
                            "answer": "A"})
        self._bump()

    def _run_batch(self, slots: list[Slot]) -> None:
        drafts, res = author.write_batch(self.llm, slots)
        got = sum(d is not None for d in drafts)
        self.log(f"batch of {len(slots)} {slots[0].section} by {res.model}: {got} usable (${res.cost:.3f})"
                 + (f"; {res.error[:120]}" if got < len(slots) and res.error else ""),
                 stage="author", qno=slots[0].qno, level="info" if got == len(slots) else "warn")

        def one(sd):
            s, d = sd
            try:
                self._run_slot(s, prefetched=d, prefetched_model=res.model)
            except FatalLLMError:
                self.cancelled.set()
                raise
            except Exception as e:  # noqa: BLE001
                self.log(f"error: {e!r}", stage="error", qno=s.qno, level="error")
                self.save_item({"qno": s.qno, "section": s.section, "slot": s.model_dump(), "status": "failed",
                                "notes": [f"pipeline error: {e!r}"], "stem": "", "options": ["", "", "", ""],
                                "answer": "A"})
        # figures + verification of the batch's questions run concurrently
        with ThreadPoolExecutor(max_workers=len(slots)) as ex:
            list(ex.map(one, zip(slots, drafts)))

    def _bump(self) -> None:
        items = self.load_items()
        self.update(progress={"done": len(items), "ok": sum(i["status"] == "ok" for i in items),
                              "flagged": sum(i["status"] != "ok" for i in items)})

    # ------------------------------------------------------------------ question bank as a source
    def _assign_sources(self, bp: Blueprint) -> None:
        """Tag each slot direct / variant / new from cfg.source (or the per-section cfg.mix) and pick
        the bank question it uses. Slots with no fitting bank question stay new."""
        cfg = self.cfg
        rng = random.Random(f"{cfg.seed}-source")
        if cfg.source == "mixed":
            mix = {k: max(0, int((cfg.mix or {}).get(k, 0))) for k in ("direct", "variant", "new")}
        else:
            mix = {"direct": 0, "variant": 0, "new": 0, cfg.source: 100}
        tot = sum(mix.values()) or 1
        taken: set[str] = set()
        counts = {"direct": 0, "variant": 0, "new": 0, "fallback": 0}
        by_sec: dict[str, list[Slot]] = {}
        for s in bp.slots:
            if not s.passage_id and not s.lr_generator:
                by_sec.setdefault(s.section, []).append(s)
        for sec, slots in by_sec.items():
            n = len(slots)
            nd = round(n * mix["direct"] / tot)
            nv = min(n - nd, round(n * mix["variant"] / tot))
            tags = ["direct"] * nd + ["variant"] * nv + ["new"] * (n - nd - nv)
            rng.shuffle(tags)
            for s, tag in zip(slots, tags):
                if tag == "new":
                    counts["new"] += 1
                    continue
                cands = bank.match(s, exclude=taken, need_figure_ok=(tag == "variant"))
                if not cands:
                    counts["fallback"] += 1
                    continue
                pick = cands[0] if tag == "direct" else rng.choice(cands[:5])
                s.origin, s.bank_ref = tag, pick["id"]
                taken.add(pick["id"])
                counts[tag] += 1
        self.log(f"question source {cfg.source}: {counts['direct']} from bank, {counts['variant']} bank variants, "
                 f"{counts['new']} new" + (f", {counts['fallback']} new because the bank had no match"
                                           if counts["fallback"] else ""), stage="plan")

    def _run_direct(self, s: Slot) -> dict:
        r = bank.get(s.bank_ref or "")
        if r is None:
            self.log(f"bank question {s.bank_ref} missing; writing a new one", stage="bank", qno=s.qno, level="warn")
            s.origin, s.bank_ref = "new", None
            return self._run_slot(s)

        def fig(rel: Optional[str], tag: str) -> Optional[str]:
            if not rel:
                return None
            src = bank.BANK / rel
            dst = self.dir / "figs" / f"q{s.qno:03d}_bank_{tag}{src.suffix}"
            if src.exists():
                shutil.copy2(src, dst)
            return str(dst.relative_to(self.dir))

        it = self._base_item(s)
        f = r.get("figure")
        it.update(stem=r["stem"], options=list(r["options"]), answer=r["answer"], solution=r.get("solution", ""),
                  working=r.get("working", ""), difficulty=r.get("difficulty") or s.difficulty, status="ok",
                  attempts=0, origin="bank", bank_id=r["id"], author_model=r.get("author_model"),
                  verdicts=[dict(v, stage=(v.get("stage") or "") + " (bank)")
                            for v in (r.get("verification") or {}).get("solvers", [])],
                  figure=({"path": fig(f.get("path"), "stem"), "kind": f.get("kind"), "width_pct": f.get("width_pct")}
                          if f else None),
                  option_figs=([fig(p, f"opt{'ABCD'[k]}") for k, p in enumerate(r["option_figs"])]
                               if r.get("option_figs") else None))
        for k in ("chapter", "subtopic", "archetype"):
            if r.get(k):
                it["slot"][k] = r[k]
        it["notes"].append(f"from question bank {r['id']} (verified in job {r.get('job_id')})")
        self.log(f"from bank {r['id']} ({r.get('chapter')})", stage="bank", qno=s.qno)
        self.save_item(it)
        return it

    def _base_item(self, s: Slot) -> dict:
        return {"qno": s.qno, "section": s.section, "slot": s.model_dump(), "status": "pending", "stem": "",
                "options": ["", "", "", ""], "answer": "A", "figure": None, "option_figs": None,
                "option_width": None, "verdicts": [], "attempts": 0, "notes": [], "working": "",
                "solution": "", "locked": False, "difficulty": s.difficulty, "draft": None}

    def _run_lr(self, s: Slot, seed: Optional[str] = None) -> dict:
        it = self._base_item(s)
        seed = seed or f"{self.cfg.seed}-{s.qno}"
        lr = GENERATORS[s.lr_generator](random.Random(seed), self.dir, f"q{s.qno:03d}_{abs(hash(seed)) % 10**6}")
        it.update(stem=lr.stem, options=lr.options, answer=lr.answer, solution=lr.solution, working=lr.solution,
                  status="ok", locked=True, attempts=1,
                  figure={"path": lr.stem_figure, "width_pct": lr.stem_width, "kind": "lr"} if lr.stem_figure else None,
                  option_figs=lr.option_figures, option_width=lr.option_width)
        it["slot"]["subtopic"] = lr.subtopic
        it["notes"].append(f"generated by figures.lr.{s.lr_generator} (answer correct by construction)")
        self.log(f"LR generator {s.lr_generator} → key {lr.answer}", stage="author", qno=s.qno)
        return it

    def _draft_figures(self, s: Slot, d: DraftQuestion, it: dict, attempt: int) -> list[str]:
        """Render the draft's figure(s) into `it`; returns problems that should go back to the author."""
        problems = []
        it["figure"], it["option_figs"] = None, None
        if d.figure is not None:
            fr = figure_agent.make_figure(self.llm, d.figure, d.stem, self.dir, f"q{s.qno:03d}_stem_v{attempt}",
                                          check=self.cfg.check_figures)
            if fr.path:
                it["figure"] = {"path": fr.path, "width_pct": fr.width_pct, "kind": d.figure.kind}
                if fr.problems:
                    it["notes"].append("figure check: " + "; ".join(fr.problems))
                self.log(f"figure {d.figure.kind} {'ok' if fr.ok else 'with problems'} (${fr.cost:.3f})",
                         stage="figure", qno=s.qno)
            else:
                problems.append("The figure could not be drawn from your description: " +
                                "; ".join(fr.problems or ["code failed"]) + ". Make the description simpler and exact.")
        if d.option_smiles and s.section != "Chemistry":
            d.option_smiles = None          # placeholder SMILES on a non-chemistry question: ignore
        if d.option_smiles:
            if len(d.option_smiles) == 4 and all(chem.valid_smiles(x) for x in d.option_smiles):
                paths = []
                for L, smi in zip(LETTERS, d.option_smiles):
                    rel = f"figs/q{s.qno:03d}_opt{L}_v{attempt}.png"
                    chem.draw_smiles(smi, self.dir / rel)
                    paths.append(rel)
                # one shared width (the widest structure) keeps all four options at the same scale
                it["option_figs"] = paths
                it["option_width"] = max(chem.natural_width(self.dir / r, cap=90) for r in paths)
            else:
                problems.append("option_smiles must be 4 valid SMILES strings: " + ", ".join(d.option_smiles))
        return problems

    def _run_slot(self, s: Slot, *, critic_feedback: str = "", prev_item: Optional[dict] = None,
                  extra: str = "", prefetched: Optional[DraftQuestion] = None, prefetched_model: str = "") -> dict:
        if s.lr_generator:
            it = self._run_lr(s)
            self.save_item(it)
            return it
        cfg = self.cfg
        it = self._base_item(s)
        previous = DraftQuestion(**prev_item["draft"]) if prev_item and prev_item.get("draft") else None
        feedback = f"- Chief examiner: {critic_feedback}" if critic_feedback else None
        seed_q = bank.get(s.bank_ref) if s.origin == "variant" and s.bank_ref else None
        if seed_q:
            it["variant_of"] = seed_q["id"]
        best = None
        for attempt in range(cfg.max_revisions + 1):
            if self.cancelled.is_set():
                break
            it["attempts"] = attempt + 1
            if attempt == 0 and prefetched is not None:
                d = prefetched
                it["author_model"] = prefetched_model
                self.log("draft 1 from batch", stage="author", qno=s.qno)
            else:
                res = author.write(self.llm, s, feedback=feedback, previous=previous, extra=extra,
                                   seed_question=seed_q)
                if res.data is None:
                    self.log(f"author returned no valid JSON (finish={res.finish_reason or '?'}; "
                             f"{(res.error or '')[:160]})", stage="author", qno=s.qno, level="warn")
                    feedback, previous = None, None
                    continue
                d = res.data
                it["author_model"] = res.model
                note = f"; {res.error[:60]}" if res.error else ""
                self.log(f"draft {attempt + 1} by {res.model} (${res.cost:.3f}{note})", stage="author", qno=s.qno)
            errs = author.lint(d)
            if seed_q:
                bid, sc = bank.nearest(d.stem)
                if sc >= 0.6:
                    errs.append(f"too close to bank question {bid} (similarity {sc:.2f}) — change the setup, "
                                "wording and numbers")
            if errs:
                feedback, previous = "- " + "\n- ".join(errs), d
                self.log("lint: " + "; ".join(errs), stage="author", qno=s.qno, level="warn")
                continue
            it.update(draft=d.model_dump(), stem=d.stem, options=list(d.options), answer=d.answer,
                      working=d.working, difficulty=d.difficulty_estimate)
            problems = self._draft_figures(s, d, it, attempt)
            if problems:
                feedback, previous = "- " + "\n- ".join(problems), d
                continue
            fig_path = self.dir / it["figure"]["path"] if it.get("figure") else None
            opt_paths = [self.dir / p for p in it["option_figs"]] if it.get("option_figs") else None
            v = verify.verify(self.llm, d.stem, list(d.options), d.answer, fig_path, opt_paths,
                              stage=author.solver_stage(s))
            it["verdicts"] = v.verdicts
            if v.difficulty:
                it["difficulty"] = round((v.difficulty + d.difficulty_estimate) / 2)
            best = dict(it)
            if v.passed:
                it["status"] = "ok"
                if v.working:
                    it["working"] = d.working + "\n\nIndependent check: " + v.working
                self.log(f"verified ✓ key {d.answer} ({len(v.verdicts)} solver call(s))", stage="verify", qno=s.qno)
                self.save_item(it)
                return it
            self.log(f"verification failed (key {d.answer}; " +
                     ", ".join(f"{x['stage']}→{x.get('answer', 'err')}" for x in v.verdicts) + ")",
                     stage="verify", qno=s.qno, level="warn")
            feedback, previous = v.feedback, d
        if best is not None:
            it = best
            it["status"] = "flagged"
            it["notes"].append("unverified: solvers disagreed with the key after all revisions — review manually")
        elif prev_item is not None:
            it = prev_item  # keep the old version rather than losing the question
            it["notes"].append("revision failed; kept previous version")
        else:
            it["status"] = "failed"
            it["notes"].append("no usable draft produced")
        self.log(f"gave up after {it['attempts']} attempt(s): {it['status']}", stage="verify", qno=s.qno,
                 level="warn")
        self.save_item(it)
        return it

    def _run_rc(self, slots: list[Slot], extra: str = "") -> None:
        res = author.write_rc(self.llm, slots, extra=extra)
        if res.data is None or len(res.data.questions) < len(slots):
            self.log(f"RC set failed ({res.error}); writing as standalone vocabulary items", stage="author",
                     level="warn")
            for s in slots:
                s.passage_id, s.chapter = None, "Sentence Completion (vocabulary)"
                self._run_slot(s)
            return
        passage = res.data.passage.strip()
        self.log(f"RC passage ({len(passage.split())} words) + {len(slots)} questions (${res.cost:.3f})",
                 stage="author", qno=slots[0].qno)
        for k, (s, d) in enumerate(zip(slots, res.data.questions)):
            it = self._base_item(s)
            stem = f"{RC_INTRO}\n\n{passage}\n\n{d.stem}" if k == 0 else d.stem
            it.update(draft=d.model_dump(), stem=stem, options=list(d.options), answer=d.answer,
                      working=d.working, attempts=1, difficulty=d.difficulty_estimate)
            v = verify.verify(self.llm, f"Passage:\n{passage}\n\nQuestion: {d.stem}", list(d.options), d.answer,
                              stage="solver_verbal")
            it["verdicts"] = v.verdicts
            it["status"] = "ok" if v.passed else "flagged"
            if not v.passed:
                it["notes"].append("unverified RC item: " + v.feedback[:400])
            self.log(f"RC item {'verified ✓' if v.passed else 'flagged'}", stage="verify", qno=s.qno)
            self.save_item(it)
        it0 = self.load_item(slots[0].qno)
        it0["passage"] = passage
        self.save_item(it0)

    # ------------------------------------------------------------------ assemble / export
    def assemble(self) -> Paper:
        cfg = self.cfg
        qs = []
        for i in self.load_items():
            if not i.get("stem"):
                continue
            s = i["slot"]
            fig = Figure(kind=i["figure"].get("kind", "image"), path=i["figure"]["path"],
                         width_pct=i["figure"]["width_pct"]) if i.get("figure") else None
            opts = []
            for k, text in enumerate(i["options"]):
                of = None
                if i.get("option_figs"):
                    of = Figure(kind="lr" if s.get("lr_generator") else "chem", path=i["option_figs"][k],
                                width_pct=i.get("option_width") or 20)
                opts.append(Option(text=text or "", figure=of))
            notes = "; ".join(i.get("notes") or []) or None
            qs.append(Question(qno=i["qno"], section=i["section"], stem=i["stem"], figure=fig, options=opts,
                               answer=i["answer"], solution=i.get("solution", ""), chapter=s.get("chapter"),
                               subtopic=s.get("subtopic"), archetype=s.get("archetype"),
                               difficulty=max(1, min(5, int(i.get("difficulty") or s.get("difficulty") or 2))),
                               figure_kind=s.get("figure_kind"), passage_id=s.get("passage_id"), notes=notes))
        paper = Paper(title=cfg.title, subtitle=cfg.subtitle or None, pattern_id=cfg.pattern_id, questions=qs)
        self.save_paper(paper)
        return paper

    def export(self) -> list[Path]:
        """Default deliverables: paper / solutions / answer key as PDF + DOCX, and an all-in-one ZIP."""
        from render.export import export_bundle
        paper = self.paper() or self.assemble()
        z = export_bundle(paper, self.dir / "exports", self.dir, self.dir / "paper.json")
        files = sorted(p for p in (self.dir / "exports").iterdir() if p.is_file())
        self.log("exported " + ", ".join(f.name for f in files if f.suffix in (".pdf", ".docx")) + f" + {z.name}",
                 stage="export")
        return files

    # ------------------------------------------------------------------ editor actions
    def regenerate(self, qno: int, instruction: str = "") -> dict:
        """Rewrite one question (optionally with an editor instruction), re-verify, re-solve, re-assemble."""
        old = self.load_item(qno)
        s = Slot(**old["slot"])
        self.log(f"regenerating{': ' + instruction if instruction else ''}", stage="edit", qno=qno)
        if s.passage_id:
            s.passage_id, s.chapter = None, s.chapter if s.chapter != "Reading Comprehension" else "Synonyms"
        if s.lr_generator:  # a fresh random puzzle of the same type
            it = self._run_lr(s, seed=f"{time.time()}")
        else:
            it = self._run_slot(s, extra=instruction)
        if not it.get("solution") and it.get("stem"):
            it["solution"] = finish.write_solution(self.llm, it["section"], it["stem"], it["options"], it["answer"],
                                                   it.get("working", ""))
        self.save_item(it)
        self.assemble()
        self._bump()
        self.update()
        self.log(f"regenerated: {it['status']}", stage="edit", qno=qno)
        return it

    def edit_question(self, qno: int, fields: dict) -> None:
        """Manual edit from the review UI (stem / options / answer / solution)."""
        it = self.load_item(qno)
        for k in ("stem", "answer", "solution"):
            if k in fields and fields[k] is not None:
                it[k] = fields[k]
        if fields.get("options") and len(fields["options"]) == 4:
            it["options"] = fields["options"]
        it["status"] = "ok" if fields.get("mark_ok") else it["status"]
        it.setdefault("notes", []).append("edited manually")
        self.save_item(it)
        self.assemble()
        self._bump()
        self.log("edited manually", stage="edit", qno=qno)


# ---------------------------------------------------------------------- registry for the web app
_RUNNING: dict[str, Job] = {}


def start(cfg: JobConfig) -> Job:
    job = Job.create(cfg)
    _RUNNING[job.id] = job
    threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}").start()
    return job


def resume(job_id: str) -> Job:
    job = Job(job_id)
    _RUNNING[job.id] = job
    job.update(status="queued", stage="queued", error=None)
    threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}").start()
    return job


def is_running(job_id: str) -> bool:
    return any(t.name == f"job-{job_id}" and t.is_alive() for t in threading.enumerate())


def get(job_id: str) -> Job:
    if job_id in _RUNNING:
        return _RUNNING[job_id]
    j = Job(job_id)
    if not (j.dir / "job.json").exists():
        raise KeyError(job_id)
    return j


def list_jobs() -> list[dict]:
    out = []
    if JOBS.exists():
        for d in sorted(JOBS.iterdir(), reverse=True):
            if (d / "job.json").exists():
                try:
                    out.append(json.loads((d / "job.json").read_text()))
                except json.JSONDecodeError:
                    pass
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="bitsat_130")
    ap.add_argument("--counts", help="e.g. Physics=2,Chemistry=2,Mathematics=2")
    ap.add_argument("--profile")
    ap.add_argument("--difficulty", default="match")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--title", default="BITSAT Practice Paper")
    ap.add_argument("--no-critic", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()
    cfg = JobConfig(pattern_id=a.pattern, profile=a.profile, difficulty=a.difficulty, title=a.title,
                    run_critic=not a.no_critic, export=not a.no_export, workers=a.workers,
                    counts={k: int(v) for k, v in (x.split("=") for x in a.counts.split(","))} if a.counts else None,
                    **({"seed": a.seed} if a.seed else {}))
    job = Job.create(cfg)
    print("job", job.id, job.dir)
    t = threading.Thread(target=job.run)
    t.start()
    seen = 0
    ev = job.dir / "events.jsonl"
    while True:
        alive = t.is_alive()
        lines = ev.read_text().splitlines() if ev.exists() else []
        for ln in lines[seen:]:
            e = json.loads(ln)
            print(f"[{e['stage']:>8}] {('Q' + str(e['qno'])) if 'qno' in e else '':>5} {e['msg']}", flush=True)
        seen = len(lines)
        if not alive:
            break
        time.sleep(1)
    print(json.dumps(job.state()["progress"]), "cost", job.state()["cost"])


if __name__ == "__main__":
    main()
