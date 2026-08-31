"""Extract one SoA page into structured cells, from the rendered image.

Why the image and not the text layer: superscript footnote markers do not
survive PDF text extraction with their cell binding intact. protocol15 p25
renders as

    (marker row)                      b     b     b     b     b     b
    Urine tox screen     Weekly x 2   X     X     X     X     X     X

The marker and the cell it marks are on different lines with no relation left
between them. Recovering the link from the text layer means re-deriving column
geometry from whitespace and hoping. The rendered page still shows the marker
sitting on the cell, which is the whole point.

The model is asked for one page at a time. Stitching pages into a single table
is deliberately a separate, deterministic step (see stitch.py) -- a model asked
to merge four page images at once tends to silently drop the middle two.
"""

from __future__ import annotations

import hashlib, json, os, pathlib, re
from dataclasses import dataclass

from .render import RenderedPage, render
from .config import api_key

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

SYSTEM = """You transcribe Schedule of Activities tables from clinical trial protocols.

You are a transcriber, not an interpreter. Your output is checked cell by cell
against the source page. Two rules override everything else:

1. VERBATIM. Reproduce what is printed, exactly. Never normalise, expand,
   correct, or translate a value. "3X/2 weeks" is not "3". "(X)" is not "X".
   "Q2W" is not "every 2 weeks". An em dash is not an empty cell.

2. NEVER INVENT AND NEVER DROP. A missing row or column is the most costly
   error possible -- it silently deletes a patient visit or an assessment from
   a study database. If you are unsure whether something is a row, include it
   and mark it ambiguous. If a value is illegible, emit "?" and mark it
   ambiguous. Do not resolve ambiguity by picking the likelier reading.
"""

PROMPT = """This is page {page} of a clinical trial protocol{span_note}.

Transcribe the Schedule of Activities table on it. Return ONLY a JSON object,
no prose, no markdown fence, matching this shape:

{{
  "is_soa_page": true,
  "title": "the table's caption or heading, verbatim, or null",
  "continuation": {{
    "is_continuation": false,
    "axis": null,
    "evidence": "e.g. the words 'Table 4, Continued', or repeated row labels"
  }},
  "column_headers": [
    {{"level": 0, "role": "period",  "cells": [{{"text": "Screening", "span": 1, "markers": []}}]}},
    {{"level": 1, "role": "visit",   "cells": [{{"text": "Visit 1", "span": 1, "markers": []}}]}},
    {{"level": 2, "role": "day",     "cells": [{{"text": "Day -28", "span": 1, "markers": []}}]}},
    {{"level": 3, "role": "window",  "cells": [{{"text": "+/- 3 d", "span": 1, "markers": []}}]}}
  ],
  "columns": [
    {{"index": 0, "period": "Screening", "visit": "1", "day": "-28", "week": null,
      "window": "+/- 3 d", "markers": [], "label": "flattened label for display"}}
  ],
  "rows": [
    {{"index": 0, "kind": "category", "label": "Safety Assessments", "indent": 0,
      "markers": [], "cells": []}},
    {{"index": 1, "kind": "assessment", "label": "Vital signs", "indent": 1,
      "markers": ["c"],
      "cells": [
        {{"column": 0, "raw": "X", "markers": [], "shaded": false, "ambiguous": false}},
        {{"column": 1, "raw": "3X/2 weeks", "markers": ["b"], "shaded": false, "ambiguous": false}}
      ]}}
  ],
  "footnotes": [
    {{"marker": "b", "text": "full verbatim text", "appears_complete": true,
      "attaches_to": [{{"kind": "cell", "row": 1, "column": 1}}]}}
  ],
  "unresolved": ["anything you could not read or could not place"]
}}

Rules that matter on this specific kind of table:

- CELLS ARE NOT BOOLEANS. Capture "3X", "1X", "6X", "Xa", "(X)", "Q2W",
  "2X/day", "Prior to Day 4", "Weekly x 2 weeks", arrows, dashes, dots, doses
  and volumes exactly as printed, in "raw".
- AN EMPTY CELL AND A SHADED CELL ARE DIFFERENT. Many protocols grey out cells
  to mean "not applicable at this visit", which is not the same as leaving them
  blank. Emit shaded cells with "raw": "" and "shaded": true. Omit only cells
  that are genuinely blank and unshaded.
- CATEGORY ROWS ARE STRUCTURE, NOT ASSESSMENTS. A row like "Safety Assessments"
  or "Primary Outcome Measure:" that spans the table and has no cell values is
  kind "category". Everything under it is kind "assessment". Getting this wrong
  invents an assessment that nobody performs.
- HEADERS ARE STACKED. Study period, visit name, visit number, study day or
  week, and visit window are usually separate header rows describing the same
  column. Keep each level separately in "column_headers" AND give the flattened
  per-column view in "columns". Record "span" where a header cell covers
  several columns.
- MARKERS BIND TO THINGS. A superscript letter, number, dagger, asterisk or
  parenthesised letter attaches to the cell, row label, or column header it
  sits on. Record it there, in "markers". A single cell may carry more than one.
  Do not collect markers into a list detached from the grid.
- PARENTHESISED NUMBERS INSIDE A ROW LABEL, like "Medical History (03)", are
  usually CRF form identifiers, not footnote markers. Keep them in the label.
- FOOTNOTES THAT RUN OFF THE PAGE. If the last footnote is cut off by the page
  edge, still emit it, with "appears_complete": false. Do not guess the rest.
- REPEATED PAGE FURNITURE IS NOT A FOOTNOTE. A running header or footer that
  appears on every page (a document title, a version line, a page number) is
  not part of the table.

If this page holds no SoA table, return {{"is_soa_page": false}} and nothing else.
"""


CACHE = pathlib.Path(__file__).resolve().parents[1] / "cache" / "pages"


def _cache_key(pdf_path: str, page_no: int, model: str) -> pathlib.Path:
    """Cache on the inputs that can change the answer: the page bytes, the
    model, and the prompt. Editing the prompt invalidates every entry, which is
    what you want -- a cached answer from an older prompt is a silent lie."""
    h = hashlib.sha256()
    h.update(pathlib.Path(pdf_path).read_bytes()[:1_000_000])
    h.update(f"|{pathlib.Path(pdf_path).stat().st_size}|{page_no}|{model}|".encode())
    h.update((SYSTEM + PROMPT).encode())
    return CACHE / f"{pathlib.Path(pdf_path).stem}_p{page_no}_{h.hexdigest()[:16]}.json"


@dataclass
class PageExtraction:
    page: int
    data: dict
    raw: str
    usage: dict


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def build_messages(rp: RenderedPage, span: list[int] | None = None) -> list[dict]:
    span_note = ""
    if span and len(span) > 1:
        span_note = (f", one of pages {span} that together hold a single "
                     f"Schedule of Activities")
    return [{
        "role": "user",
        "content": [
            {"type": "image", "source": rp.to_source()},
            {"type": "text", "text": PROMPT.format(page=rp.page, span_note=span_note)},
        ],
    }]


def extract_page(pdf_path: str, page_no: int, span: list[int] | None = None,
                 client=None, model: str = MODEL, use_cache: bool = True) -> PageExtraction:
    """Extract one page, reusing a cached response when the inputs are unchanged.

    Every downstream fix -- stitching, footnote binding, the graph -- needs to be
    iterated against real extractions. Paying for a fresh vision call on each
    iteration makes that loop slow and expensive, and tempts you into debugging
    against synthetic data instead of the real thing.
    """
    key = _cache_key(pdf_path, page_no, model)
    if use_cache and key.exists():
        c = json.loads(key.read_text())
        return PageExtraction(page=page_no, data=c["data"], raw=c["raw"],
                              usage={**c["usage"], "cached": True})

    import anthropic
    client = client or anthropic.Anthropic(api_key=api_key())
    rp = render(pdf_path, page_no)
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=build_messages(rp, span),
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    body = _strip_fence(text)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        # Surface the failure rather than silently returning an empty table --
        # an empty result here would read downstream as "this page had no rows".
        data = {"is_soa_page": None, "parse_error": str(e)}
    ex = PageExtraction(
        page=page_no, data=data, raw=text,
        usage={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
    )
    if data.get("is_soa_page") is not None:
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps({"data": ex.data, "raw": ex.raw, "usage": ex.usage},
                                  ensure_ascii=False))
    return ex


def extract_span(pdf_path: str, pages: list[int], **kw) -> list[PageExtraction]:
    return [extract_page(pdf_path, p, span=pages, **kw) for p in pages]


if __name__ == "__main__":
    import sys, pathlib
    name, pg = sys.argv[1].rsplit(":", 1)
    ex = extract_page(f"protocols/{name}", int(pg))
    out = pathlib.Path("scratch") / f"{name.replace('.pdf','')}_p{pg}.json"
    out.write_text(json.dumps(ex.data, indent=2, ensure_ascii=False))
    d = ex.data
    print(f"{out}  tokens in/out {ex.usage['input']}/{ex.usage['output']}")
    if d.get("is_soa_page"):
        print(f"  title      {d.get('title')}")
        print(f"  columns    {len(d.get('columns', []))}")
        rows = d.get("rows", [])
        print(f"  rows       {len(rows)}  "
              f"({sum(1 for r in rows if r.get('kind')=='category')} category)")
        print(f"  cells      {sum(len(r.get('cells', [])) for r in rows)}")
        print(f"  footnotes  {len(d.get('footnotes', []))}")
        print(f"  unresolved {d.get('unresolved')}")
