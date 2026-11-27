"""Redraw RDKit figures of an existing job with the current style (sharp, fixed scale, cropped).

  uv run python -m figures.redraw_chem data/jobs/<job_id>
"""
import json
import sys
from pathlib import Path

from core.models import LETTERS
from figures import chem


def redraw(job: Path) -> int:
    paper_f = job / "paper.json"
    paper = json.loads(paper_f.read_text())
    items = {}
    for f in (job / "items").glob("*.json"):
        d = json.loads(f.read_text())
        items[d.get("qno")] = d
    n = 0
    for q in paper["questions"]:
        it = items.get(q["qno"]) or {}
        smiles = it.get("option_smiles") or (it.get("draft") or {}).get("option_smiles")
        figs = [o.get("figure") for o in q["options"]]
        if smiles and len(smiles) == 4 and all(f and f.get("kind") == "chem" for f in figs):
            for smi, f in zip(smiles, figs):
                chem.draw_smiles(smi, job / f["path"])
            w = max(chem.natural_width(job / f["path"], cap=90) for f in figs)
            for f in figs:
                f["width_pct"] = w
            n += 1
        fig = q.get("figure")
        smi = ((it.get("draft") or {}).get("figure") or {}).get("smiles")
        if fig and fig.get("kind") == "chem" and smi and chem.valid_smiles(smi):
            chem.draw_smiles(smi, job / fig["path"])
            fig["width_pct"] = chem.natural_width(job / fig["path"])
            n += 1
    paper_f.write_text(json.dumps(paper, ensure_ascii=False, indent=1))
    return n


if __name__ == "__main__":
    for j in sys.argv[1:]:
        print(j, redraw(Path(j)), "figures redrawn")
