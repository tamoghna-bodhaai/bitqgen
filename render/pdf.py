"""HTML -> PDF with headless Chromium (same engine that produced the source papers)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from core.models import Paper
from render.html import Mode, ROOT, render_html

_FOOTER = ('<div style="width:100%;font-size:8px;color:#555;text-align:center;'
           'font-family:serif"><span class="pageNumber"></span> / <span class="totalPages"></span></div>')


def export_pdf(paper: Paper, out: Path, mode: Mode = "paper", assets_dir: Path | None = None,
               **render_kw) -> Path:
    """Render `paper` to `out`. `assets_dir` holds figure files referenced by relative path."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        shutil.copytree(ROOT / "static", work / "static")
        if assets_dir and Path(assets_dir).exists():
            shutil.copytree(assets_dir, work, dirs_exist_ok=True)
        page_html = work / "paper.html"
        page_html.write_text(render_html(paper, mode, static="static", **render_kw), encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(page_html.as_uri())
            page.wait_for_function("window.__mathDone === true", timeout=60_000)
            page.emulate_media(media="print")
            page.pdf(path=str(out), format="A4", print_background=True,
                     prefer_css_page_size=True, display_header_footer=True,
                     header_template="<div></div>", footer_template=_FOOTER)
            browser.close()
    return out
