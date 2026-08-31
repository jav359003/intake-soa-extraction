"""End to end: PDF in, SoA graph out.

    locate  -> which pages hold a schedule
    render  -> those pages as images (vision engine only)
    extract -> per page cells, verbatim
    stitch  -> pages merged into one table, footnotes rejoined
    graph   -> nodes and edges, provenance on every node

The extraction engine is swappable and every engine returns the same per-page
dict, so the benchmark runs the identical pipeline with only that one piece
changed. Nothing downstream knows which engine produced its input.
"""

from __future__ import annotations

import json, pathlib, time
from dataclasses import asdict

from .locate import locate
from .stitch import merge_pages, to_graph
from .schema import SoAGraph

ENGINES = ("vision", "text-layer")


def _extract_span(engine: str, pdf: str, pages: list[int], model: str | None):
    if engine == "text-layer":
        from .baseline import extract_span
        return extract_span(pdf, pages)
    from .extract import extract_span, MODEL
    exs = extract_span(pdf, pages, model=model or MODEL)
    return [e.data for e in exs]


def run(pdf_path: str, engine: str = "vision", model: str | None = None,
        out_dir: str | None = None) -> dict:
    assert engine in ENGINES, f"engine must be one of {ENGINES}"
    t0 = time.time()
    pdf = pathlib.Path(pdf_path)
    loc = locate(str(pdf))

    graphs: list[SoAGraph] = []
    for i, tbl in enumerate(loc["tables"]):
        pages = tbl["pages"]
        per_page = _extract_span(engine, str(pdf), pages, model)
        merged = merge_pages(per_page, pages)
        g = to_graph(merged, protocol=pdf.stem, table_id=f"{pdf.stem}:soa{i}",
                     pages=pages)
        g.warnings.insert(0, f"located by: {'; '.join(tbl['reasons'])}")
        graphs.append(g)

    result = {
        "protocol": pdf.stem,
        "engine": engine,
        "model": model,
        "n_pages": loc["n_pages"],
        "tables": [json.loads(g.to_json()) for g in graphs],
        "stats": [g.stats() for g in graphs],
        "seconds": round(time.time() - t0, 1),
    }
    if out_dir:
        d = pathlib.Path(out_dir); d.mkdir(parents=True, exist_ok=True)
        (d / f"{pdf.stem}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False))
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Extract the Schedule of Activities from a protocol PDF.")
    ap.add_argument("pdfs", nargs="*", help="paths to protocol PDFs")
    ap.add_argument("--engine", default="text-layer", choices=ENGINES)
    ap.add_argument("--model", default=None, help="override the vision model id")
    ap.add_argument("--out", default=None, help="directory to write JSON into")
    a = ap.parse_args()

    paths = a.pdfs or sorted(str(p) for p in pathlib.Path("protocols").glob("*.pdf"))
    for p in paths:
        r = run(p, engine=a.engine, model=a.model, out_dir=a.out)
        for tbl, st in zip(r["tables"], r["stats"]):
            print(f"{r['protocol']:<12} pages {tbl['pages']}  {a.engine:<10} "
                  f"visits={st['visits']:<3} assessments={st['assessments']:<4} "
                  f"cells={st['cells']:<5} fn={st['footnotes']:<3} "
                  f"fn_links={st['footnote_links']:<4} warn={st['warnings']:<4} "
                  f"{r['seconds']}s")
