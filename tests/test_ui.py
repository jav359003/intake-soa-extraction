"""UI smoke tests.

The brief's grading event is someone dropping an unfamiliar PDF into this UI,
so the paths that matter are: it accepts a PDF, it runs the real pipeline
rather than serving precomputed results, it can hand back the source page for
checking, and it refuses bad input with a message rather than a traceback.
"""
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from ui.server import app

client = TestClient(app)
PDF = pathlib.Path("protocols/protocol5.pdf")


def test_index_serves():
    r = client.get("/")
    assert r.status_code == 200 and "Schedule of Activities" in r.text


def test_extract_runs_the_real_pipeline():
    r = client.post("/extract",
                    files={"file": ("protocol5.pdf", PDF.read_bytes(), "application/pdf")},
                    data={"engine": "text-layer"})
    assert r.status_code == 200
    j = r.json()
    assert j["tables"], "no table found in a protocol that has one"
    t = j["tables"][0]
    assert t["pages"], "table reports no source pages"
    assert any(n["type"] == "cell" for n in t["nodes"])
    # Provenance must name the engine that actually ran, not a default.
    cell = next(n for n in t["nodes"] if n["type"] == "cell")
    assert cell["provenance"][0]["source"] == "text-layer"


def test_source_page_image_is_served():
    j = client.post("/extract",
                    files={"file": ("protocol5.pdf", PDF.read_bytes(), "application/pdf")},
                    data={"engine": "text-layer"}).json()
    page = j["tables"][0]["pages"][0]
    r = client.get("/page", params={"pdf": j["_pdf"], "page": page})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png" and len(r.content) > 10_000


def test_non_pdf_is_refused_with_a_message():
    r = client.post("/extract", files={"file": ("x.txt", b"nope", "text/plain")},
                    data={"engine": "text-layer"})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]


def test_unknown_engine_is_refused():
    r = client.post("/extract",
                    files={"file": ("p.pdf", PDF.read_bytes(), "application/pdf")},
                    data={"engine": "nonsense"})
    assert r.status_code == 400


def test_missing_upload_is_a_message_not_a_traceback():
    r = client.get("/page", params={"pdf": "no-such-upload.pdf", "page": 1})
    assert r.status_code == 404 and "re-upload" in r.json()["detail"]


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for name, fn in fns:
        try:
            fn(); print(f"  pass  {name}")
        except AssertionError as e:
            bad += 1; print(f"  FAIL  {name}: {e}")
    print(f"\n{len(fns)-bad}/{len(fns)} passing")
