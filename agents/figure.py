"""Figure Agent: FigureRequest -> PNG.

chem  -> RDKit from SMILES (deterministic)
other -> figure_coder writes matplotlib/schemdraw code -> run -> figure_checker (vision) -> retry
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from agents.common import prompt
from core.llm import LLM, image_part
from core.models import FigureRequest, FigureVerdict
from figures import chem
from figures.runner import run_python


class FigureCode(BaseModel):
    code: str
    width_pct: int


@dataclass
class FigureResult:
    ok: bool
    path: Optional[str] = None  # relative to assets
    width_pct: int = 50
    problems: list[str] = field(default_factory=list)
    cost: float = 0.0
    code: str = ""


DEFAULT_W = {"circuit": 60, "plot": 50, "diagram": 55, "chem": 45}


def make_figure(llm: LLM, req: FigureRequest, stem: str, assets: Path, name: str,
                max_tries: int = 3, check: bool = True) -> FigureResult:
    rel = f"figs/{name}.png"
    out = assets / rel
    res = FigureResult(ok=False)
    if req.kind == "chem" and req.smiles and chem.valid_smiles(req.smiles):
        chem.draw_smiles(req.smiles, out)
        return FigureResult(ok=True, path=rel, width_pct=chem.natural_width(out))

    feedback = ""
    prev_code = ""
    for attempt in range(max_tries):
        user = (f"Question text:\n{stem}\n\nFigure kind: {req.kind}\nDrawing brief:\n{req.description}"
                + (f"\n\nSMILES hint: {req.smiles}" if req.smiles else ""))
        if feedback:
            user += f"\n\nYour previous code:\n```python\n{prev_code}\n```\nProblems to fix:\n{feedback}"
        r = llm.call("figure_coder", [{"role": "system", "content": prompt("figure_coder")},
                                      {"role": "user", "content": user}], schema=FigureCode)
        res.cost += r.cost
        if r.data is None:
            feedback = f"Reply was not valid JSON ({r.error})."
            continue
        prev_code = r.data.code
        run = run_python(r.data.code, want=("fig.png",), keep_dir=out.parent / f".{name}_try{attempt}")
        if not run.ok:
            feedback = "The script failed:\n" + run.stderr[-2500:]
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        run.files["fig.png"].replace(out)
        try:
            run.files["fig.png"].parent.rmdir()
        except OSError:
            pass
        res.path, res.width_pct, res.code = rel, max(20, min(95, r.data.width_pct or DEFAULT_W.get(req.kind, 50))), r.data.code
        if not check:
            res.ok = True
            return res
        v = llm.call("figure_checker", [
            {"role": "system", "content": prompt("figure_checker")},
            {"role": "user", "content": [
                {"type": "text", "text": f"Question:\n{stem}\n\nDrawing brief:\n{req.description}"},
                image_part(out)]}], schema=FigureVerdict)
        res.cost += v.cost
        if v.data is None or v.data.ok:
            res.ok = True
            res.problems = []
            return res
        res.problems = v.data.problems
        feedback = "A reviewer looked at the rendered image and found:\n- " + "\n- ".join(v.data.problems)
    return res  # best effort: path may be set (last render) with problems listed
