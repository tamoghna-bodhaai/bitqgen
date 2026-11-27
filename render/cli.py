"""Export a Paper JSON from the command line.

  uv run python -m render.cli paper.json --out exports/                       # paper+solutions+key, PDF+DOCX
  uv run python -m render.cli paper.json --content solutions --formats docx --sections Physics,Chemistry
  uv run python -m render.cli paper.json --bundle                             # one ZIP with everything
"""
import argparse
import json
from pathlib import Path

from core.models import Paper
from render.export import ExportOptions, export, export_bundle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--out", default="data/exports")
    ap.add_argument("--assets", help="directory holding figure files (default: the paper's directory)")
    ap.add_argument("--content", default="paper,solutions,key", help="any of paper,solutions,key")
    ap.add_argument("--formats", default="pdf,docx", help="any of pdf,docx,html")
    ap.add_argument("--sections", help="comma-separated section names (default: all)")
    ap.add_argument("--no-instructions", action="store_true")
    ap.add_argument("--no-key", action="store_true", help="do not append the answer key to the question paper")
    ap.add_argument("--bundle", action="store_true", help="write a single ZIP with all PDFs/DOCX")
    a = ap.parse_args()

    src = Path(a.paper)
    paper = Paper(**json.loads(src.read_text()))
    assets = Path(a.assets) if a.assets else src.parent
    out = Path(a.out)
    if a.bundle:
        print(export_bundle(paper, out, assets, src))
        return
    for content in a.content.split(","):
        for fmt in a.formats.split(","):
            o = ExportOptions(content=content, fmt=fmt,
                              sections=a.sections.split(",") if a.sections else None,
                              instructions=not a.no_instructions, answer_key=False if a.no_key else None)
            print(export(paper, o, out, assets))


if __name__ == "__main__":
    main()
