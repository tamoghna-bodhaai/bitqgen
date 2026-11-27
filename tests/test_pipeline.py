"""Offline end-to-end run of the orchestrator with a fake LLM (no API calls, no cost)."""
import json
import random

import pytest

from agents.finish import balance_answers
from core.llm import CallResult
from core.models import CriticReport, DraftQuestion, FigureVerdict, SolutionText, SolverVerdict


class FakeLLM:
    profile_name = "fake"
    total_cost = 0.0
    stages = {"solver": {}, "tiebreaker": {}}

    def __init__(self):
        self.n = 0
        self.stats = {}
        self.batches = 0

    def stage(self, name):
        return self.stages.get(name, {})

    def record(self, stage, *a, **kw):
        pass

    def call(self, stage, messages, schema=None, **kw):
        self.n += 1
        name = getattr(schema, "__name__", "")
        if name == "DraftQuestion":
            k = self.n
            return CallResult(text="", data=DraftQuestion(
                stem=f"Find the value of $x$ if $2x = {2 * k}$ (item {k}).", options=[str(k), str(k + 1), str(k + 2), str(k + 3)],
                answer="A", working=f"x = {k}", distractor_notes="", figure=None, difficulty_estimate=2))
        if name == "DraftBatch":
            from core.models import DraftBatch
            self.batches += 1
            n = messages[-1]["content"].count("### Brief")
            qs = []
            for _ in range(n):
                self.n += 1
                k = self.n
                qs.append(DraftQuestion(stem=f"Find $x$ if $3x = {3 * k}$ (batch item {k}).",
                                        options=[str(k), str(k + 1), str(k + 2), str(k + 3)], answer="A",
                                        working=f"x = {k}", distractor_notes="", figure=None, difficulty_estimate=2))
            return CallResult(text="", data=DraftBatch(questions=qs))
        if name == "SolverVerdict":
            text = json.dumps(messages[-1]["content"]) if not isinstance(messages[-1]["content"], str) else messages[-1]["content"]
            return CallResult(text="", data=SolverVerdict(working="ok", answer="A", confidence=.9, multiple_correct=False,
                                                          issues=[], difficulty=2))
        if name == "RCSet":
            from agents.author import RCSet
            qs = [DraftQuestion(stem=f"RC q{i}", options=["a", "b", "c", "d"], answer="B", working="w",
                                distractor_notes="", figure=None, difficulty_estimate=2) for i in range(4)]
            return CallResult(text="", data=RCSet(passage="A short passage.", questions=qs))
        if name == "CriticReport":
            return CallResult(text="", data=CriticReport(items=[], summary="fine"))
        if name == "SolutionText":
            return CallResult(text="", data=SolutionText(solution="Because."))
        if name == "PlanSection":
            return CallResult(text="", error="skip")
        if name == "FigureVerdict":
            return CallResult(text="", data=FigureVerdict(ok=True, problems=[]))
        return CallResult(text="", error="unexpected " + name)


@pytest.fixture
def job(tmp_path, monkeypatch):
    from pipeline import job as jobmod
    monkeypatch.setattr(jobmod, "JOBS", tmp_path)
    from agents import bank
    monkeypatch.setattr(bank, "BANK", tmp_path / "bank")
    monkeypatch.setattr(bank, "FILE", tmp_path / "bank" / "questions.jsonl")
    cfg = jobmod.JobConfig(counts={"Physics": 3, "English Proficiency": 6, "Logical Reasoning": 8}, seed=3,
                           export=False, workers=4)
    j = jobmod.Job.create(cfg)
    j._llm = FakeLLM()
    return j


def test_offline_job(job):
    job.run()
    st = job.state()
    assert st["status"] == "done", st
    paper = job.paper()
    assert len(paper.questions) == 17
    assert [q.qno for q in paper.sorted()] == list(range(1, 18))
    for q in paper.questions:
        assert q.solution
        assert len(q.options) == 4
    from agents import bank
    rows = bank.load()
    ok = [i for i in job.load_items() if i["status"] == "ok"]
    assert rows and len(rows) <= len(ok)
    r = rows[0]
    assert r["status"] == "verified" and r["job_id"] == job.id and r["chapter"] and r["answer"] in "ABCD"
    assert bank.add_job(job.load_items(), job_id=job.id, job_dir=job.dir, pattern_id="x", profile="x")[0] == 0
    lr_fig = [q for q in paper.questions if q.section == "Logical Reasoning" and (q.figure or q.options[0].figure)]
    assert lr_fig, "expected at least one generator-built non-verbal LR item"
    # key balanced within Physics: fake author always says A
    phys = [q.answer for q in paper.questions if q.section == "Physics"]
    assert len(set(phys)) > 1


def test_balance_answers():
    rng = random.Random(1)
    items = [{"qno": i, "section": "S", "answer": "A", "options": [f"o{i}{k}" for k in range(4)],
              "option_figs": None, "locked": False} for i in range(1, 41)]
    items[5]["options"][3] = "None of these"
    keep = {i["qno"]: i["options"][0] for i in items}
    balance_answers(items, rng)
    counts = {L: sum(i["answer"] == L for i in items) for L in "ABCD"}
    assert max(counts.values()) - min(counts.values()) <= 2, counts
    for i in items:  # the correct text travels with the key
        assert i["options"]["ABCD".index(i["answer"])] == keep[i["qno"]]
    assert items[5]["answer"] == "A"  # positional option -> not moved
    seq = [i["answer"] for i in items]
    assert not any(seq[k] == seq[k + 1] == seq[k + 2] for k in range(len(seq) - 2))
