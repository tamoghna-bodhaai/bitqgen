"""Upload pipeline: layout -> (fake) vision transcription -> merge, offline."""
import json
import re
import time
from pathlib import Path

import pymupdf
import pytest

from core.llm import CallResult
from core.models import TranscribedQ, TranscriptionBatch

ROOT = Path(__file__).resolve().parent.parent
SRC = sorted((ROOT / "bitsat").glob("*2021*.pdf"))


class FakeVision:
    profile_name, total_cost, stats = "fake", 0.0, {}
    stages = {"transcriber": {}}

    def __init__(self):
        self.calls = 0

    def call(self, stage, messages, schema=None, **kw):
        assert stage == "transcriber" and schema is TranscriptionBatch
        self.calls += 1
        self.total_cost += 0.01
        text = messages[-1]["content"][0]["text"]
        assert messages[-1]["content"][1]["type"] == "image_url"
        nums = [int(n) for n in re.match(r"Transcribe questions ([\d, ]+)", text).group(1).split(",")]
        return CallResult(text="", data=TranscriptionBatch(questions=[
            TranscribedQ(qno=n, stem=f"Question {n}", options=["a", "b", "c", "d"], solution="s",
                         chapter="Kinematics", subtopic="x", archetype="y", difficulty=2) for n in nums]))


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    if not SRC:
        pytest.skip("no source PDF")
    from ingest import flag_doubtful, layout, merge
    for m in (layout, merge, flag_doubtful):
        monkeypatch.setattr(m, "CORPUS", tmp_path)
    doc = pymupdf.open(SRC[0])
    small = pymupdf.open()
    small.insert_pdf(doc, from_page=0, to_page=1)
    pdf = tmp_path / "bitsat pyq 2021.pdf"
    small.save(pdf)
    return tmp_path, pdf


def test_ingest_end_to_end(corpus):
    from ingest.pipeline import ingest_paper, read_status, stage_pdf
    root, pdf = corpus
    stage_pdf(pdf, "up1")
    llm = FakeVision()
    st = ingest_paper("up1", llm=llm, rebuild=False, log=lambda *a: None)
    assert st["status"] == "done", st.get("error")
    paper = json.loads((root / "up1" / "paper.json").read_text())
    skel = json.loads((root / "up1" / "skeleton.json").read_text())
    keyed = [q for q in skel["questions"] if q["answer"]]
    assert len(paper["questions"]) == len(keyed) == st["merged"] > 0
    assert [q["answer"] for q in paper["questions"]] == [q["answer"] for q in keyed]
    assert skel["source_pdf"] == pdf.name
    assert read_status("up1")["cost"] > 0
    # resume: every page already transcribed -> no new calls
    n = llm.calls
    assert ingest_paper("up1", llm=llm, rebuild=False, log=lambda *a: None)["status"] == "done"
    assert llm.calls == n


def test_ingest_rejects_non_esaral(corpus, tmp_path):
    from ingest.pipeline import ingest_paper, stage_pdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Hello, not a paper")
    p = tmp_path / "x.pdf"
    doc.save(p)
    stage_pdf(p, "bad")
    st = ingest_paper("bad", llm=FakeVision(), rebuild=False, log=lambda *a: None)
    assert st["status"] == "error" and "No questions" in st["error"]


def test_upload_api(corpus, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as m
    from ingest import pipeline
    root, pdf = corpus
    monkeypatch.setattr(m, "CORPUS", root)
    monkeypatch.setattr(m, "ingest_paper", lambda pid, pattern=None: pipeline.ingest_paper(
        pid, pattern=pattern, llm=FakeVision(), rebuild=False, log=lambda *a: None))
    c = TestClient(m.app)
    assert c.post("/api/corpus/upload", files={"file": ("a.txt", b"hello")}).status_code == 400
    r = c.post("/api/corpus/upload", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
               data={"id": "2021up"})
    assert r.status_code == 200, r.text
    for _ in range(100):
        st = c.get("/api/corpus/2021up/ingest").json()
        if st["status"] in ("done", "error") and not st["running"]:
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    assert c.post("/api/corpus/upload", files={"file": (pdf.name, pdf.read_bytes())},
                  data={"id": "2021up"}).status_code == 409
    row = next(p for p in c.get("/api/corpus").json() if p["id"] == "2021up")
    assert row["n"] > 0 and row["ingest"]["status"] == "done"
