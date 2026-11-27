# bitQgen — BITSAT question-paper studio

bitQgen generates original BITSAT papers with the same pattern, section order, difficulty and 2-column look as the past papers in `bitsat/`. Each paper comes with solutions, and you can export it as PDF, DOCX or HTML.

```bash
uv sync && uv run playwright install chromium
echo "OPENROUTER_API_KEY=sk-or-..." > .env
uv run uvicorn app.main:app --port 8000      # API (+ legacy UI at http://127.0.0.1:8000)
cd web && npm install && npm run build && npm start   # studio UI at http://localhost:3100 (or `npm run dev`)
```

The UI is a Next.js app in `web/`. It talks to FastAPI's JSON endpoints under `/api/*` and proxies previews, figures and exports to port 8000 (set `BITQGEN_API` to point elsewhere).

## Pipeline

```
corpus (data/corpus/*/paper.json) ─► syllabus + style profiles (ingest/syllabus.py)
   Planner ─► Author ─► Figure agent ─► Solver ─(disagree)─► Tiebreaker ─(fail)─► Author revises (×2)
      └─► Critic per section ─► regenerate "major" items ─► balance answer key ─► Solution writer
      └─► paper.json ─► render (HTML/KaTeX ─► PDF via Chromium · DOCX via pandoc, native equations)
```

| Stage | Code | Default model (`config/models.yaml`, profile `balanced`) |
|---|---|---|
| Planner | `agents/planner.py` | GLM-5.3. Code fixes quotas, difficulty mix and figures; the LLM picks subtopics |
| Authors | `agents/author.py` | Opus 5.5 (Physics/Chemistry/Maths), Sonnet 5.5 (English, verbal LR, RC sets) |
| Non-verbal LR | `figures/lr/generators.py` | No LLM. 8 generators whose answer is correct by construction |
| Figures | `agents/figure.py` | RDKit for chemistry; Sonnet writes matplotlib/schemdraw code; Gemini 3.8 Flash checks it visually |
| Solver / tiebreaker | `agents/verify.py` | Gemini 3.8 Flash with a `python_exec` tool, then Qwen4 Max (different model families from the authors) |
| Critic | `agents/finish.py` | Qwen4 Max, plus a check for near-duplicates of corpus questions |
| Solutions | `agents/finish.py` | Sonnet 5.5, in eSaral style |

A full paper on the `balanced` profile is estimated at about $5–8. A 15-question test run cost $0.63.

## Export

The job page has an **Export** panel. You choose:
- **Content:** question paper, paper with solutions, or answer key only.
- **Format:** PDF, DOCX, or an offline HTML ZIP.
- **Sections** to include, and whether to add the instructions box and the answer key.
- **Download everything:** a ZIP with every PDF and DOCX plus `paper.json`.

You can also export from the URL or the command line:

```
/jobs/<id>/export?content=solutions&fmt=docx&sections=Physics|Chemistry&answer_key=0
/jobs/<id>/export/paper.pdf   /jobs/<id>/export/key.docx   /jobs/<id>/export/all.zip
uv run python -m render.cli data/jobs/<id>/paper.json --content paper,solutions,key --formats pdf,docx
```

Corpus papers can be exported the same way (`/corpus/<id>/export?...`).

## Other entry points

- `uv run python -m pipeline.job --counts "Physics=3,Mathematics=3"` runs a generation job from the CLI. Leave out `--counts` for a full paper.
- **Resume:** a job that stops (for example on an OpenRouter credit limit) can be resumed from the UI. Verified questions are kept.
- **Review page:** regenerate one question with an instruction, edit its text, or mark it OK.
- `uv run python -m ingest.syllabus` rebuilds `config/syllabus.yaml` and `data/style/profiles.json` after more papers are extracted. Weights can also be edited in the UI.
- `uv run pytest -q` runs the tests offline (a fake LLM drives the full orchestrator).

Job state lives in `data/jobs/<id>/`: `job.json`, `events.jsonl`, `blueprint.json`, `items/`, `figs/`, `paper.json` and `exports/`.
