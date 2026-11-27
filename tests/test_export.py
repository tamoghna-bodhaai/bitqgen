import json
import zipfile
from pathlib import Path

import pytest

from core.models import Paper
from render.export import ExportOptions, export, export_bundle

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_paper.json"


@pytest.fixture(scope="module")
def paper():
    return Paper(**json.loads(SAMPLE.read_text()))


@pytest.mark.parametrize("content", ["paper", "solutions", "key"])
@pytest.mark.parametrize("fmt", ["pdf", "docx", "html"])
def test_export_matrix(paper, content, fmt, tmp_path):
    p = export(paper, ExportOptions(content=content, fmt=fmt), tmp_path, SAMPLE.parent / "assets")
    assert p.exists() and p.stat().st_size > 1000
    if fmt == "html":
        names = zipfile.ZipFile(p).namelist()
        assert "index.html" in names and any(n.startswith("static/katex") for n in names)


def test_section_filter(paper, tmp_path):
    sec = paper.questions[0].section
    p = export(paper, ExportOptions(content="paper", fmt="docx", sections=[sec]), tmp_path, SAMPLE.parent / "assets")
    assert sec.split()[0] in p.name
    with pytest.raises(ValueError):
        export(paper, ExportOptions(sections=["Nope"]), tmp_path, None)


def test_docx_baseless_units():
    from render.docx import _fix_baseless
    assert _fix_baseless("$5$ m s$^{-1}$") == "$5$ m $\\text{s}^{-1}$"


def test_bundle(paper, tmp_path):
    z = export_bundle(paper, tmp_path, SAMPLE.parent / "assets")
    assert len(zipfile.ZipFile(z).namelist()) == 6
