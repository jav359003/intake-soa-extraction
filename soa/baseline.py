"""Text-layer SoA extraction. The baseline the vision extractor is measured against.

This exists for two reasons. It is the honest comparison the brief asks for --
"benchmarked three and can tell us precisely where each of them broke" -- and it
is the fallback when no vision model is available.

It produces the SAME per-page dict shape as extract.py, so stitch.py and the
scorer consume either without knowing which produced it. One contract, two
producers.

Its known ceiling, stated up front: a superscript marker and the cell it marks
are separate words in the text layer, on separate lines, with no relation
between them. This recovers markers by geometry -- a small token sitting above
and horizontally inside a cell -- which works when the layout is clean and
fails silently when it is not. That failure is the point of the comparison.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

import pymupdf

from .locate import CELL, FN_LINE

# A marker token: one or two superscript-ish characters sitting alone.
MARKER = re.compile(r"^[a-z]{1,2}$|^[*†‡§¶]{1,4}$|^\(?[a-z]\)$|^\d{1,2}$")


@dataclass
class Word:
    x0: float; y0: float; x1: float; y1: float; text: str
    @property
    def cx(self) -> float: return (self.x0 + self.x1) / 2
    @property
    def cy(self) -> float: return (self.y0 + self.y1) / 2
    @property
    def h(self) -> float: return self.y1 - self.y0


def _words(page: pymupdf.Page) -> list[Word]:
    return [Word(*w[:4], w[4]) for w in page.get_text("words") if w[4].strip()]


def _lines(words: list[Word], tol: float = 3.0) -> list[list[Word]]:
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if out and abs(out[-1][0].cy - w.cy) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    for ln in out:
        ln.sort(key=lambda w: w.x0)
    return out


def _column_centres(lines: list[list[Word]], min_support: int | None = None,
                    tol: float = 9.0) -> list[float]:
    """Infer column x-centres from cell-like tokens only.

    Row labels are prose and land anywhere; cell values are short and stack
    vertically. Clustering only the cell tokens gives a much cleaner column
    signal than clustering every word on the page.
    """
    # Support scales with page density. A fixed threshold cannot fit all five
    # reference protocols: 3 leaks label text into the grid on the dense pages,
    # 5 drops real visit columns on the sparse ones. Requiring a cluster to
    # appear on roughly a twelfth of the page's lines tracks both.
    if min_support is None:
        min_support = max(3, len(lines) // 12)
    xs = sorted(w.cx for ln in lines for w in ln if CELL.match(w.text))
    if not xs:
        return []
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [statistics.mean(c) for c in clusters if len(c) >= min_support]


def _label_boundary(lines: list[list[Word]], centres: list[float]) -> float:
    """x below which text is a row label rather than a cell value.

    Taking the leftmost cell cluster is not enough: a long row label puts words
    at repeatable x positions too, so a weak cluster inside the label block
    reads as a data column and splits "Informed consent" into a label and a
    cell. Anchor on the leftmost *strongly supported* cluster instead, and only
    treat weaker clusters to its right as columns.
    """
    return (min(centres) - 12.0) if centres else 1e9


def _assign(w: Word, centres: list[float], tol: float = 22.0) -> int | None:
    if not centres:
        return None
    best = min(range(len(centres)), key=lambda i: abs(centres[i] - w.cx))
    return best if abs(centres[best] - w.cx) <= tol else None


def _markers_for(cell: Word, words: list[Word], body_h: float) -> list[str]:
    """Find superscript tokens riding on a cell.

    A marker is small relative to body text and sits above the cell's baseline
    while overlapping it horizontally. This is the geometric reconstruction the
    vision path does not need to do.
    """
    out = []
    for w in words:
        if w is cell or not MARKER.match(w.text):
            continue
        if w.h > body_h * 0.85:          # full-size text is not a superscript
            continue
        above = cell.y0 - 1.5 <= w.cy <= cell.y1
        near_x = cell.x0 - 6 <= w.cx <= cell.x1 + 10
        if above and near_x:
            out.append(w.text)
    return out


def extract_page(pdf_path: str, page_no: int, span: list[int] | None = None) -> dict:
    """Return the same shape extract.py returns, from the text layer alone."""
    doc = pymupdf.open(pdf_path)
    page = doc[page_no - 1]
    words = _words(page)
    if not words:
        return {"is_soa_page": False, "_engine": "text-layer"}

    lines = _lines(words)
    centres = _column_centres(lines)
    body_h = statistics.median([w.h for w in words]) or 8.0
    unresolved: list[str] = []

    if len(centres) < 2:
        return {"is_soa_page": False, "_engine": "text-layer",
                "unresolved": ["no column structure found in text layer"]}

    lab_x = _label_boundary(lines, centres)

    # Header lines are those above the first line carrying a cell token.
    first_cell_line = next(
        (i for i, ln in enumerate(lines) if any(CELL.match(w.text) for w in ln)), 0)
    header_lines = lines[:first_cell_line]
    body_lines = lines[first_cell_line:]

    column_headers = []
    for lvl, ln in enumerate(header_lines[-5:]):     # last 5 header rows at most
        cells = []
        for w in ln:
            if w.cx < lab_x:
                continue
            cells.append({"text": w.text, "span": 1, "markers": []})
        if cells:
            column_headers.append({"level": lvl, "role": None, "cells": cells})

    columns = [{"index": i, "period": None, "visit": None, "day": None,
                "week": None, "window": None, "markers": [],
                "label": f"col{i}"} for i in range(len(centres))]
    # Best-effort header text per column, by x proximity.
    for ln in header_lines:
        for w in ln:
            ci = _assign(w, centres)
            if ci is not None:
                lbl = columns[ci]["label"]
                columns[ci]["label"] = w.text if lbl.startswith("col") else f"{lbl} {w.text}"

    rows, ri = [], 0
    for ln in body_lines:
        label_words = [w for w in ln if w.cx < lab_x]
        cell_words = [w for w in ln if w.cx >= lab_x and CELL.match(w.text)]
        other = [w for w in ln if w.cx >= lab_x and not CELL.match(w.text)]
        label = " ".join(w.text for w in label_words).strip()

        if not label and not cell_words:
            continue
        # A line with a label and no values, where the label is not indented,
        # reads as a category header. Genuinely ambiguous against a row whose
        # values are all blank -- flagged rather than decided.
        kind = "category" if label and not cell_words and not other else "assessment"
        if kind == "category":
            unresolved.append(
                f"row {ri} '{label[:40]}' has no values; read as a category header, "
                f"but it may be an assessment performed at no visit on this page")

        cells = []
        for w in cell_words:
            ci = _assign(w, centres)
            if ci is None:
                unresolved.append(f"row {ri}: value '{w.text}' matched no column")
                continue
            cells.append({"column": ci, "raw": w.text,
                          "markers": _markers_for(w, words, body_h),
                          "shaded": False,          # text layer carries no fill
                          "ambiguous": False})
        # Free text sitting in the grid, e.g. "Prior to Day 4" spanning columns.
        for w in other:
            ci = _assign(w, centres, tol=40.0)
            if ci is not None:
                cells.append({"column": ci, "raw": w.text, "markers": [],
                              "shaded": False, "ambiguous": True})

        rows.append({"index": ri, "kind": kind, "label": label, "indent": 0,
                     "markers": [], "cells": cells})
        ri += 1

    text = page.get_text("text")
    footnotes = []
    for m in FN_LINE.finditer(text):
        line = text[m.start():text.find("\n", m.start()) if text.find("\n", m.start()) > 0 else len(text)]
        mk = re.match(r"^\s*([*†‡§¶]{1,4}|X[a-z]|\(?[a-z]\)|[a-z]\.|\d{1,2}\.)", line)
        footnotes.append({"marker": (mk.group(1).strip(". ()") if mk else ""),
                          "text": line.strip(), "appears_complete": True,
                          "attaches_to": []})     # linkage unavailable from text alone
    if footnotes:
        unresolved.append("footnote linkage not recoverable from the text layer; "
                          "markers extracted but not bound to cells")

    return {
        "is_soa_page": True,
        "_engine": "text-layer",
        "title": next((l.strip() for l in text.splitlines() if l.strip()), None),
        "continuation": {"is_continuation": None, "axis": None, "evidence": ""},
        "column_headers": column_headers,
        "columns": columns,
        "rows": rows,
        "footnotes": footnotes,
        "unresolved": unresolved,
    }


def extract_span(pdf_path: str, pages: list[int]) -> list[dict]:
    return [extract_page(pdf_path, p, span=pages) for p in pages]


if __name__ == "__main__":
    import sys, json
    for spec in sys.argv[1:]:
        name, pg = spec.rsplit(":", 1)
        d = extract_page(f"protocols/{name}", int(pg))
        rows = d.get("rows", [])
        print(f"{spec:<22} soa={d['is_soa_page']} cols={len(d.get('columns',[]))} "
              f"rows={len(rows)} cells={sum(len(r['cells']) for r in rows)} "
              f"fn={len(d.get('footnotes',[]))} "
              f"markers={sum(len(c['markers']) for r in rows for c in r['cells'])} "
              f"unresolved={len(d.get('unresolved',[]))}")
