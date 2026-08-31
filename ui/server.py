"""Upload a protocol PDF, see the extracted SoA beside the page it came from.

The point of this UI is checkability, not looks. Every extracted cell is one
click from the page image it was read off, because the only way anyone trusts
an extraction is by comparing it against the source. That is also how the
manual verification pass in the README was actually done.

Runs the same pipeline as the CLI -- no precomputed results.
"""

from __future__ import annotations

import base64, io, json, pathlib, tempfile, traceback

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soa.pipeline import run, ENGINES
from soa.render import render

app = FastAPI(title="SoA Extractor")
UPLOADS = pathlib.Path(tempfile.gettempdir()) / "soa-uploads"
UPLOADS.mkdir(exist_ok=True)

INDEX = (pathlib.Path(__file__).parent / "index.html")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX.read_text()


@app.post("/extract")
async def extract(file: UploadFile = File(...), engine: str = Form("text-layer"),
                  model: str = Form("")):
    if engine not in ENGINES:
        raise HTTPException(400, f"engine must be one of {ENGINES}")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a PDF")

    dest = UPLOADS / f"{abs(hash(file.filename))}_{file.filename}"
    dest.write_bytes(await file.read())
    try:
        result = run(str(dest), engine=engine, model=model or None)
    except KeyError as e:
        if "ANTHROPIC_API_KEY" in str(e):
            raise HTTPException(
                400, "ANTHROPIC_API_KEY is not set, so the vision engine cannot "
                     "run. Use the text-layer engine, or export the key and restart.")
        raise
    except Exception:
        raise HTTPException(500, traceback.format_exc(limit=3))
    result["_pdf"] = dest.name
    return JSONResponse(result)


@app.get("/page")
def page_image(pdf: str, page: int):
    """The source page, so an extracted cell can be checked against the paper."""
    path = UPLOADS / pdf
    if not path.exists():
        raise HTTPException(404, "upload not found; re-upload the PDF")
    return Response(render(str(path), page).png, media_type="image/png")
