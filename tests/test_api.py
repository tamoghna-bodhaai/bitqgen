from fastapi.testclient import TestClient

from app.main import app
from pipeline import job as jobs

c = TestClient(app)


def test_api_pages():
    for p in ("/api/home", "/api/corpus", "/api/syllabus", "/api/models"):
        assert c.get(p).status_code == 200, p


def test_api_job_shape():
    lst = jobs.list_jobs()
    if not lst:
        return
    d = c.get(f"/api/jobs/{lst[0]['id']}").json()
    assert {"job", "items", "sections", "has_paper"} <= d.keys()
    if d["items"]:
        assert "stem_html" in d["items"][0] and "options_html" in d["items"][0]
