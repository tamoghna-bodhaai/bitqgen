"""bitQgen studio — FastAPI web UI.

    uv run uvicorn app.main:app --reload        # http://127.0.0.1:8000
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from agents import bank as qbank
from agents.common import CORPUS, SYLLABUS
from core.models import LETTERS, Paper
from ingest.pipeline import ingest_paper, read_status as read_ingest, stage_pdf
from pipeline import job as jobs
from render.html import PATTERNS, load_pattern, render_html
from render.text import to_html

ROOT = Path(__file__).resolve().parent.parent
MODELS_YAML = ROOT / "config" / "models.yaml"

app = FastAPI(title="bitQgen studio")
app.mount("/static", StaticFiles(directory=ROOT / "render" / "static"), name="static")
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static"), name="ui")
tpl = Jinja2Templates(directory=Path(__file__).parent / "templates")
tpl.env.filters["md"] = to_html
tpl.env.globals["LETTERS"] = LETTERS


def _job(job_id: str) -> jobs.Job:
    try:
        return jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, "no such job")


def _safe_file(base: Path, rel: str) -> Path:
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())) or not p.is_file():
        raise HTTPException(404)
    return p


def _patterns() -> list[dict]:
    out = []
    for f in sorted(PATTERNS.glob("*.yaml")):
        p = load_pattern(f.stem)
        out.append({"id": p.id, "title": p.title, "sections": [(s.name, s.count) for s in p.sections],
                    "total": p.total})
    return out


def _profiles() -> tuple[list[str], str, dict]:
    cfg = yaml.safe_load(MODELS_YAML.read_text())
    from core.llm import _resolve_profile
    resolved = {name: _resolve_profile(cfg, name) for name in cfg["profiles"]}
    return list(cfg["profiles"]), cfg["active_profile"], resolved


def _corpus_summary() -> list[dict]:
    out = []
    for d in sorted(CORPUS.iterdir(), reverse=True):
        f = d / "paper.json"
        if f.exists():
            p = Paper(**json.loads(f.read_text()))
            out.append({"id": d.name, "n": len(p.questions), "title": p.title,
                        "figs": sum(bool(q.figure) or any(o.figure for o in q.options) for q in p.questions),
                        "flagged": sum(bool(q.notes) for q in p.questions)})
        else:
            cols = d / "cols"
            out.append({"id": d.name, "n": 0, "pending": True,
                        "pages": len(list(cols.glob("*.png"))) if cols.exists() else 0})
        st = read_ingest(d.name)
        if st:
            out[-1]["ingest"] = {**st, "running": d.name in _ingesting}
    return out


# ----------------------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    profiles, active, _ = _profiles()
    return tpl.TemplateResponse(request, "home.html", {
        "patterns": _patterns(), "profiles": profiles, "active": active, "jobs": jobs.list_jobs()[:30],
        "corpus": _corpus_summary()})


@app.post("/jobs")
def create_job(title: str = Form("BITSAT Practice Paper"), subtitle: str = Form(""),
               pattern_id: str = Form("bitsat_130"), profile: str = Form(""), difficulty: str = Form("match"),
               seed: str = Form(""), run_critic: str = Form(""), check_figures: str = Form(""),
               custom_counts: str = Form("")):
    counts = None
    if custom_counts.strip():
        try:
            counts = {k.strip(): int(v) for k, v in (x.split("=") for x in custom_counts.split(",") if x.strip())}
        except ValueError:
            raise HTTPException(400, "custom counts must look like Physics=3,Chemistry=3")
    cfg = jobs.JobConfig(title=title, subtitle=subtitle, pattern_id=pattern_id, profile=profile or None,
                         difficulty=difficulty, run_critic=bool(run_critic), check_figures=bool(check_figures),
                         counts=counts, **({"seed": int(seed)} if seed.strip().isdigit() else {}))
    j = jobs.start(cfg)
    return RedirectResponse(f"/jobs/{j.id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    j = _job(job_id)
    st = j.state()
    items = j.load_items()
    return tpl.TemplateResponse(request, "job.html", {
        "job": st, "items": items, "sections": list(dict.fromkeys(i["section"] for i in items)), "running": jobs.is_running(job_id),
        "has_paper": (j.dir / "paper.json").exists()})


@app.get("/jobs/{job_id}/state")
def job_state(job_id: str):
    j = _job(job_id)
    st = j.state()
    st["running"] = jobs.is_running(job_id)
    return st


@app.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str, since: int = 0):
    j = _job(job_id)
    ev_file = j.dir / "events.jsonl"

    async def gen():
        seen = since
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            lines = ev_file.read_text().splitlines() if ev_file.exists() else []
            for ln in lines[seen:]:
                yield {"event": "log", "data": ln}
            if len(lines) > seen:
                idle = 0
            seen = len(lines)
            st = j.state()
            st["running"] = jobs.is_running(job_id)
            yield {"event": "state", "data": json.dumps({k: st.get(k) for k in
                                                         ("status", "stage", "progress", "cost", "running")})}
            if not st["running"] and st.get("status") in ("done", "failed", "cancelled"):
                idle += 1
                if idle > 3:
                    break
            await asyncio.sleep(1.5)

    return EventSourceResponse(gen())


@app.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    j = _job(job_id)
    j.cancelled.set()
    j.log("cancel requested", stage="done", level="warn")
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/resume")
def job_resume(job_id: str):
    if jobs.is_running(job_id):
        raise HTTPException(409, "job is already running")
    jobs.resume(job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}/review", response_class=HTMLResponse)
def review(request: Request, job_id: str, section: str = "", status: str = ""):
    j = _job(job_id)
    items = j.load_items()
    sections = list(dict.fromkeys(i["section"] for i in items))
    shown = [i for i in items if (not section or i["section"] == section) and
             (not status or (status == "flagged" and i["status"] != "ok") or i["status"] == status)]
    return tpl.TemplateResponse(request, "review.html", {
        "job": j.state(), "items": shown, "sections": sections, "section": section, "status": status,
        "all_items": items})


@app.get("/jobs/{job_id}/q/{qno}/card", response_class=HTMLResponse)
def q_card(request: Request, job_id: str, qno: int):
    j = _job(job_id)
    return tpl.TemplateResponse(request, "_card.html", {"job": j.state(), "it": j.load_item(qno)})


@app.post("/jobs/{job_id}/q/{qno}/regenerate")
def q_regenerate(job_id: str, qno: int, instruction: str = Form("")):
    j = _job(job_id)
    it = j.load_item(qno)
    it["status"] = "regenerating"
    j.save_item(it)

    def work():
        try:
            j.regenerate(qno, instruction)
        except Exception as e:  # noqa: BLE001
            j.log(f"regenerate failed: {e!r}", stage="edit", qno=qno, level="error")
            it2 = j.load_item(qno)
            it2["status"] = "flagged"
            j.save_item(it2)
    threading.Thread(target=work, daemon=True).start()
    return JSONResponse({"ok": True})


@app.post("/jobs/{job_id}/q/{qno}/edit")
async def q_edit(request: Request, job_id: str, qno: int):
    j = _job(job_id)
    data = await request.json()
    if data.get("answer") not in (None, *LETTERS):
        raise HTTPException(400, "answer must be A-D")
    j.edit_question(qno, data)
    return JSONResponse({"ok": True})


# -------------------------------------------------------------- paper views & exports

@app.get("/jobs/{job_id}/view/{mode}.html", response_class=HTMLResponse)
def job_view(job_id: str, mode: str):
    j = _job(job_id)
    paper = j.paper() or j.assemble()
    if mode not in ("paper", "solutions", "key"):
        raise HTTPException(404)
    return render_html(paper, mode, static="/static")


@app.get("/jobs/{job_id}/view/figs/{name}")
@app.get("/jobs/{job_id}/files/figs/{name}")
def job_fig(job_id: str, name: str):
    j = _job(job_id)
    return FileResponse(_safe_file(j.dir / "figs", name))


def _do_export(paper: Paper, assets: Path, out: Path, content: str, fmt: str, sections: str,
               instructions: str, answer_key: str):
    from render.export import ExportOptions, export
    if content not in ("paper", "solutions", "key") or fmt not in ("pdf", "docx", "html"):
        raise HTTPException(400, "content must be paper|solutions|key and fmt pdf|docx|html")
    opts = ExportOptions(content=content, fmt=fmt,
                         sections=[x for x in sections.split("|") if x] or None,
                         instructions=instructions != "0",
                         answer_key=None if answer_key == "" else answer_key == "1")
    try:
        path = export(paper, opts, out, assets)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return FileResponse(path, filename=path.name)


@app.get("/jobs/{job_id}/export")
def job_export(job_id: str, content: str = "paper", fmt: str = "pdf", sections: str = "",
               instructions: str = "1", answer_key: str = ""):
    """e.g. /jobs/<id>/export?content=solutions&fmt=docx&sections=Physics|Chemistry&answer_key=0"""
    j = _job(job_id)
    paper = j.paper() or j.assemble()
    return _do_export(paper, j.dir, j.dir / "exports", content, fmt, sections, instructions, answer_key)


@app.get("/jobs/{job_id}/export/all.zip")
def job_export_all(job_id: str):
    from render.export import export_bundle
    j = _job(job_id)
    paper = j.paper() or j.assemble()
    path = export_bundle(paper, j.dir / "exports", j.dir, j.dir / "paper.json")
    return FileResponse(path, filename=path.name)


@app.get("/jobs/{job_id}/export/paper.json")
def job_export_json(job_id: str):
    j = _job(job_id)
    if not (j.dir / "paper.json").exists():
        j.assemble()
    return FileResponse(j.dir / "paper.json", filename=f"{job_id}.json")


@app.get("/jobs/{job_id}/export/{mode}.{fmt}")
def job_export_short(job_id: str, mode: str, fmt: str):
    """Short links: /export/paper.pdf, /export/solutions.docx, /export/key.pdf ..."""
    return job_export(job_id, content=mode, fmt=fmt)


# ------------------------------------------------------------------------- corpus

@app.get("/corpus", response_class=HTMLResponse)
def corpus(request: Request):
    return tpl.TemplateResponse(request, "corpus.html", {"corpus": _corpus_summary()})


@app.get("/corpus/{pid}/view/{mode}.html", response_class=HTMLResponse)
def corpus_view(pid: str, mode: str):
    f = CORPUS / pid / "paper.json"
    if not f.exists() or mode not in ("paper", "solutions"):
        raise HTTPException(404)
    return render_html(Paper(**json.loads(f.read_text())), mode, static="/static")


@app.get("/corpus/{pid}/export")
def corpus_export(pid: str, content: str = "solutions", fmt: str = "pdf", sections: str = "",
                  instructions: str = "1", answer_key: str = ""):
    f = CORPUS / pid / "paper.json"
    if not f.exists():
        raise HTTPException(404)
    paper = Paper(**json.loads(f.read_text()))
    out = ROOT / "data" / "exports" / f"corpus_{pid}"
    return _do_export(paper, CORPUS / pid, out, content, fmt, sections, instructions, answer_key)


@app.get("/corpus/{pid}/view/figs/{name}")
def corpus_fig(pid: str, name: str):
    return FileResponse(_safe_file(CORPUS / pid / "figs", name))


# ------------------------------------------------------------------- syllabus/models

@app.get("/syllabus", response_class=HTMLResponse)
def syllabus(request: Request, msg: str = ""):
    text = SYLLABUS.read_text()
    data = yaml.safe_load(text)
    return tpl.TemplateResponse(request, "syllabus.html", {"text": text, "data": data, "msg": msg})


@app.post("/syllabus")
def syllabus_save(text: str = Form(...)):
    try:
        data = yaml.safe_load(text)
        assert isinstance(data, dict) and "sections" in data
        for sec in data["sections"].values():
            for t in sec["topics"]:
                float(t["weight"])
                t["name"]
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"/syllabus?msg=Not saved: invalid syllabus ({str(e)[:120]})", status_code=303)
    SYLLABUS.write_text(text)
    return RedirectResponse("/syllabus?msg=Saved", status_code=303)


@app.post("/syllabus/rebuild")
def syllabus_rebuild():
    from ingest.syllabus import main as rebuild
    rebuild()
    from agents import common
    common.corpus_papers.cache_clear()
    return RedirectResponse("/syllabus?msg=Rebuilt from corpus", status_code=303)


@app.get("/models", response_class=HTMLResponse)
def models(request: Request):
    names, active, resolved = _profiles()
    return tpl.TemplateResponse(request, "models.html", {"profiles": resolved, "active": active})


# ----------------------------------------------------------------- JSON API (Next.js UI)

from fastapi import APIRouter, Body  # noqa: E402

api = APIRouter(prefix="/api")


def _with_html(it: dict) -> dict:
    it = dict(it)
    it["stem_html"] = to_html(it.get("stem") or "")
    it["options_html"] = [to_html(o or "") for o in (it.get("options") or [])]
    it["solution_html"] = to_html(it.get("solution") or "")
    return it


def _job_summary(st: dict, j: jobs.Job | None = None) -> dict:
    st = dict(st)
    st["running"] = jobs.is_running(st["id"])
    if j is not None:
        st["marks"] = [{"qno": i["qno"], "status": i["status"], "section": i["section"]} for i in j.load_items()]
    return st


@api.get("/jobs")
def api_jobs():
    out = []
    for st in jobs.list_jobs():
        try:
            out.append(_job_summary(st, jobs.get(st["id"])))
        except KeyError:
            out.append(_job_summary(st))
    return {"jobs": out}


@api.get("/home")
def api_home():
    profiles, active, _ = _profiles()
    lst = []
    for st in jobs.list_jobs()[:30]:
        try:
            lst.append(_job_summary(st, jobs.get(st["id"])))
        except KeyError:
            lst.append(_job_summary(st))
    return {"patterns": _patterns(), "profiles": profiles, "active": active, "jobs": lst,
            "corpus": _corpus_summary(), "bank": qbank.stats()["by_section"]}


@api.get("/bank/stats")
def api_bank_stats():
    return qbank.stats()


@api.get("/bank/list")
def api_bank_list(section: str = "", chapter: str = "", subtopic: str = "", difficulty: str = "", q: str = "",
                  offset: int = 0, limit: int = 30):
    rows = list(reversed(qbank.load()))   # newest first
    used = qbank.usage()
    if section:
        rows = [r for r in rows if r.get("section") == section]
    if chapter:
        rows = [r for r in rows if (r.get("chapter") or "?") == chapter]
    if subtopic:
        rows = [r for r in rows if (r.get("subtopic") or "?") == subtopic]
    if difficulty:
        rows = [r for r in rows if str(r.get("difficulty")) == difficulty]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r.get("stem") or "").lower() or ql in (r.get("subtopic") or "").lower()
                or ql == r.get("id")]
    page = []
    for r in rows[offset:offset + limit]:
        page.append({k: r.get(k) for k in ("id", "source", "created", "job_id", "job_qno", "section", "chapter",
                     "subtopic", "difficulty", "stem", "options", "answer", "solution", "passage", "figure",
                     "option_figs", "verification", "author_model")} | {"used_in": used.get(r["id"], [])})
    return {"total": len(rows), "items": page, "stats": qbank.stats(), "tree": _bank_tree()}


def _bank_tree() -> dict:
    """section -> chapter -> subtopic -> count, for the bank browser's sidebar."""
    tree: dict = {}
    for r in qbank.load():
        ch = tree.setdefault(r["section"], {}).setdefault(r.get("chapter") or "?", {})
        st = r.get("subtopic") or "?"
        ch[st] = ch.get(st, 0) + 1
    return tree


@api.get("/bank/figs/{name}")
def api_bank_fig(name: str):
    f = (qbank.BANK / "figs" / name).resolve()
    if f.parent != (qbank.BANK / "figs").resolve() or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


@api.post("/jobs")
def api_create_job(data: dict = Body(...)):
    counts = data.get("counts") or None
    if isinstance(counts, str):
        try:
            counts = {k.strip(): int(v) for k, v in (x.split("=") for x in counts.split(",") if x.strip())} or None
        except ValueError:
            raise HTTPException(400, "Section counts must look like Physics=3,Chemistry=3")
    seed = str(data.get("seed") or "").strip()
    source = data.get("source") or "new"
    if source not in ("new", "direct", "variant", "mixed"):
        raise HTTPException(400, f"unknown question source {source!r}")
    mix = None
    if source == "mixed":
        try:
            mix = {k: int((data.get("mix") or {}).get(k, 0)) for k in ("direct", "variant", "new")}
        except (TypeError, ValueError):
            raise HTTPException(400, "mix must be whole-number percentages")
        if sum(mix.values()) != 100 or min(mix.values()) < 0:
            raise HTTPException(400, "Mixed percentages must add up to 100")
    cfg = jobs.JobConfig(title=data.get("title") or "BITSAT Practice Paper", subtitle=data.get("subtitle") or "",
                         pattern_id=data.get("pattern_id") or "bitsat_130", profile=data.get("profile") or None,
                         difficulty=data.get("difficulty") or "match", run_critic=bool(data.get("run_critic", True)),
                         check_figures=bool(data.get("check_figures", True)), counts=counts,
                         add_to_bank=bool(data.get("add_to_bank", True)), source=source, mix=mix,
                         **({"seed": int(seed)} if seed.isdigit() else {}))
    return {"id": jobs.start(cfg).id}


@api.get("/jobs/{job_id}")
def api_job(job_id: str):
    j = _job(job_id)
    items = j.load_items()
    return {"job": _job_summary(j.state()), "items": [_with_html(i) for i in items],
            "sections": list(dict.fromkeys(i["section"] for i in items)),
            "has_paper": (j.dir / "paper.json").exists()}


@api.get("/jobs/{job_id}/events")
async def api_job_events(request: Request, job_id: str, since: int = 0):
    return await job_events(request, job_id, since)


@api.post("/jobs/{job_id}/cancel")
def api_cancel(job_id: str):
    job_cancel(job_id)
    return {"ok": True}


@api.post("/jobs/{job_id}/resume")
def api_resume(job_id: str):
    job_resume(job_id)
    return {"ok": True}


@api.get("/jobs/{job_id}/q/{qno}")
def api_q(job_id: str, qno: int):
    return _with_html(_job(job_id).load_item(qno))


@api.post("/jobs/{job_id}/q/{qno}/regenerate")
def api_q_regen(job_id: str, qno: int, data: dict = Body(default={})):
    return q_regenerate(job_id, qno, instruction=data.get("instruction", ""))


@api.post("/jobs/{job_id}/q/{qno}/edit")
async def api_q_edit(request: Request, job_id: str, qno: int):
    await q_edit(request, job_id, qno)
    return _with_html(_job(job_id).load_item(qno))


@api.get("/corpus")
def api_corpus():
    return _corpus_summary()


_ingesting: set[str] = set()
_ingest_lock = threading.Lock()


def _start_ingest(pid: str, pattern: str | None) -> None:
    with _ingest_lock:
        if pid in _ingesting:
            raise HTTPException(409, f"{pid} is already being processed")
        _ingesting.add(pid)

    def work():
        try:
            ingest_paper(pid, pattern=pattern)
        finally:
            _ingesting.discard(pid)
    threading.Thread(target=work, daemon=True).start()


@api.post("/corpus/upload")
async def api_corpus_upload(file: UploadFile = File(...), id: str = Form(""), pattern: str = Form(""),
                            overwrite: bool = Form(False)):
    import re

    from ingest.layout import paper_id_from
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF file.")
    pid = (id.strip() or paper_id_from(file.filename or "upload.pdf")).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", pid):
        raise HTTPException(400, "The paper id may only use letters, digits, '-' and '_' (e.g. 2027s1).")
    if (CORPUS / pid).exists() and not overwrite:
        raise HTTPException(409, f"A paper with id '{pid}' already exists. Pick another id or tick overwrite.")
    if pid in _ingesting:
        raise HTTPException(409, f"{pid} is already being processed")
    if overwrite and (CORPUS / pid).exists():
        import shutil
        shutil.rmtree(CORPUS / pid)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / (Path(file.filename or "upload.pdf").name or "upload.pdf")
        tmp.write_bytes(data)
        stage_pdf(tmp, pid)
    _start_ingest(pid, pattern or None)
    return {"id": pid, "ingest": read_ingest(pid)}


@api.get("/corpus/{pid}/ingest")
def api_corpus_ingest(pid: str):
    st = read_ingest(pid)
    if not st:
        raise HTTPException(404, "no upload for this paper")
    return {**st, "running": pid in _ingesting}


@api.post("/corpus/{pid}/ingest/retry")
def api_corpus_ingest_retry(pid: str):
    st = read_ingest(pid)
    if not st or not (CORPUS / pid / "source.pdf").exists():
        raise HTTPException(404, "no uploaded PDF for this paper")
    if pid in _ingesting:
        raise HTTPException(409, f"{pid} is already being processed")
    _start_ingest(pid, st.get("pattern_id"))
    return read_ingest(pid)


@api.get("/syllabus")
def api_syllabus():
    text = SYLLABUS.read_text()
    return {"text": text, "data": yaml.safe_load(text)}


@api.post("/syllabus")
def api_syllabus_save(data: dict = Body(...)):
    text = data.get("text", "")
    try:
        d = yaml.safe_load(text)
        assert isinstance(d, dict) and "sections" in d
        for sec in d["sections"].values():
            for t in sec["topics"]:
                float(t["weight"])
                t["name"]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Not saved: the syllabus is invalid ({str(e)[:160]})")
    SYLLABUS.write_text(text)
    return api_syllabus()


@api.post("/syllabus/rebuild")
def api_syllabus_rebuild():
    syllabus_rebuild()
    return api_syllabus()


@api.get("/models")
def api_models():
    _, active, resolved = _profiles()
    return {"profiles": resolved, "active": active}


app.include_router(api)
