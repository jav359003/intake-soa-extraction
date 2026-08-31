"""Merge per-page extractions into one table, then into the output graph.

An SoA runs across up to four pages and continues along one of two axes, which
look nothing alike and fail in opposite directions:

  ROW continuation (protocol9 p26-28) -- the column header repeats, each page
  brings new assessments. Concatenate rows, keep one column set.

  COLUMN continuation (protocol1 p53-54) -- every row label repeats, each page
  brings new visits. Merge columns onto the existing rows. Concatenating here
  would duplicate all 32 assessments.

Guessing the axis wrong corrupts the table silently in one direction or the
other, so the axis is decided by evidence and disagreement is recorded rather
than resolved: the extractor's own read is accepted only when row-label overlap
agrees with it.

Footnote pages carry no grid and are folded in as annotation, not as rows.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .schema import SoAGraph, Node, Edge, Provenance

# How much row-label overlap between consecutive pages means "the same rows
# again", i.e. a column continuation rather than new assessments.
COLUMN_CONT_OVERLAP = 0.60
ROW_CONT_OVERLAP = 0.25          # below this, the rows are genuinely new


def norm_marker(m: str) -> str:
    """Reduce a footnote marker to a comparable key.

    Sponsors write the same marker two ways in the same document: protocol15
    prints a bare superscript "c" on the cell and labels the footnote "Xc -".
    protocol5 does the same with "Xa"/"Xb". Comparing raw strings leaves every
    one of those links unmade -- 64 of them on protocol15 alone -- so both
    sides are stripped to the marker itself before matching.
    """
    m = (m or "").strip().strip("().:-\u2013\u2014 ")
    if len(m) == 2 and m[0] in "Xx" and m[1].isalpha():
        m = m[1]                       # Xa -> a
    return m.lower()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _similar(a: str, b: str, bar: float = 0.88) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b).ratio() >= bar


def _label_overlap(prev_rows: list[dict], rows: list[dict]) -> float:
    """Fraction of this page's assessment labels already seen on the last one."""
    prev = [_norm(r["label"]) for r in prev_rows if r.get("kind") == "assessment" and r.get("label")]
    cur = [_norm(r["label"]) for r in rows if r.get("kind") == "assessment" and r.get("label")]
    if not prev or not cur:
        return 0.0
    hits = sum(1 for c in cur if any(_similar(c, p) for p in prev))
    return hits / len(cur)


def decide_axis(prev_page: dict, page: dict) -> tuple[str, str, bool]:
    """Return (axis, evidence, confident).

    The extractor is asked to read the continuation off the page -- "Table 4,
    Continued", repeated row labels -- and geometry is used to check it. When
    the two disagree, geometry wins and the disagreement becomes a warning:
    a model that misreads the axis would otherwise duplicate or delete every
    row on the page with nothing to show for it.
    """
    claimed = ((page.get("continuation") or {}).get("axis") or "").lower() or None
    evidence = (page.get("continuation") or {}).get("evidence", "")
    overlap = _label_overlap(prev_page.get("rows", []), page.get("rows", []))

    if overlap >= COLUMN_CONT_OVERLAP:
        measured = "columns"
    elif overlap <= ROW_CONT_OVERLAP:
        measured = "rows"
    else:
        measured = None

    if measured is None:
        return (claimed or "rows",
                f"{evidence} (row-label overlap {overlap:.0%}, inconclusive)", False)
    if claimed and claimed != measured:
        return (measured,
                f"extractor said '{claimed}', row-label overlap is {overlap:.0%} "
                f"so treated as '{measured}'", False)
    return measured, f"row-label overlap {overlap:.0%}", True


def _merge_columns(base: list[dict], new: list[dict]) -> tuple[list[dict], dict[int, int]]:
    """Append genuinely new columns; map this page's indices onto the merged set.

    Continuation pages often repeat the first column or two (a row-label column,
    sometimes the screening visit) before carrying on, so matching by label is
    what keeps a repeated visit from being counted twice.
    """
    out = list(base)
    mapping: dict[int, int] = {}
    for c in new:
        hit = next((i for i, b in enumerate(out)
                    if _similar(b.get("label", ""), c.get("label", ""))
                    and _norm(b.get("label", ""))), None)
        if hit is None:
            mapping[c["index"]] = len(out)
            out.append({**c, "index": len(out)})
        else:
            mapping[c["index"]] = hit
    return out, mapping


def merge_pages(pages: list[dict], page_numbers: list[int]) -> dict:
    """Fold a list of per-page extractions into one table dict."""
    table = {"title": None, "columns": [], "rows": [], "footnotes": [],
             "warnings": [], "unresolved": [], "page_of_row": {}, "axes": []}
    prev_grid: dict | None = None

    for pno, page in zip(page_numbers, pages):
        if not page.get("is_soa_page"):
            # A page with no grid is still in the span for a reason: it carries
            # the footnote block. Fold its notes in and move on.
            for fn in page.get("footnotes", []):
                table["footnotes"].append({**fn, "page": pno})
            table["unresolved"] += [f"p{pno}: {u}" for u in page.get("unresolved", [])]
            continue

        table["title"] = table["title"] or page.get("title")
        table["unresolved"] += [f"p{pno}: {u}" for u in page.get("unresolved", [])]

        if prev_grid is None:
            table["columns"] = [dict(c) for c in page.get("columns", [])]
            for r in page.get("rows", []):
                r = dict(r); r["page"] = pno
                r["index"] = len(table["rows"])
                table["rows"].append(r)
            table["axes"].append({"page": pno, "axis": "first", "evidence": "seed page"})
        else:
            axis, evidence, confident = decide_axis(prev_grid, page)
            table["axes"].append({"page": pno, "axis": axis, "evidence": evidence,
                                  "confident": confident})
            if not confident:
                table["warnings"].append(
                    f"p{pno}: continuation axis uncertain -- {evidence}")

            if axis == "columns":
                table["columns"], cmap = _merge_columns(
                    table["columns"], page.get("columns", []))
                for r in page.get("rows", []):
                    tgt = next((t for t in table["rows"]
                                if t.get("kind") == r.get("kind")
                                and _similar(t.get("label", ""), r.get("label", ""))), None)
                    if tgt is None:
                        # A row that appears only on the continuation page is
                        # still a real assessment. Add it rather than drop it.
                        r = dict(r); r["page"] = pno; r["index"] = len(table["rows"])
                        r["cells"] = [{**c, "column": cmap.get(c["column"], c["column"])}
                                      for c in r.get("cells", [])]
                        table["rows"].append(r)
                        table["warnings"].append(
                            f"p{pno}: row '{r.get('label','')[:40]}' not present on the "
                            f"previous page; appended rather than merged")
                        continue
                    for c in r.get("cells", []):
                        tgt.setdefault("cells", []).append(
                            {**c, "column": cmap.get(c["column"], c["column"])})
            else:
                # Row continuation: the column set is the same table, restated.
                _, cmap = _merge_columns(table["columns"], page.get("columns", []))
                for r in page.get("rows", []):
                    r = dict(r); r["page"] = pno; r["index"] = len(table["rows"])
                    r["cells"] = [{**c, "column": cmap.get(c["column"], c["column"])}
                                  for c in r.get("cells", [])]
                    table["rows"].append(r)

        for fn in page.get("footnotes", []):
            table["footnotes"].append({**fn, "page": pno})
        prev_grid = page

    table["footnotes"] = _join_footnotes(table["footnotes"], table["warnings"])
    return table


def _join_footnotes(footnotes: list[dict], warnings: list[str]) -> list[dict]:
    """Rejoin a footnote whose text ran onto the following page.

    A footnote block routinely spills past a page break, and the continuation
    carries no marker, no header and nothing saying it belongs to a table two
    pages back. The signal available is: the previous footnote was reported
    incomplete, and the next fragment arrived without a marker.
    """
    out: list[dict] = []
    for fn in footnotes:
        marker = (fn.get("marker") or "").strip()
        if out and not marker and out[-1].get("appears_complete") is False:
            prev = out[-1]
            prev["text"] = f"{prev['text'].rstrip()} {fn.get('text','').lstrip()}".strip()
            prev["appears_complete"] = fn.get("appears_complete", True)
            prev.setdefault("continued_on", []).append(fn.get("page"))
            continue
        out.append(dict(fn))
    for fn in out:
        if fn.get("appears_complete") is False:
            warnings.append(
                f"footnote '{fn.get('marker')}' on p{fn.get('page')} looks truncated "
                f"and no continuation was found on the following page")
    return out


def to_graph(table: dict, protocol: str, table_id: str, pages: list[int],
             source: str = "vlm") -> SoAGraph:
    """Lower the merged table into the node/edge output."""
    g = SoAGraph(protocol=protocol, table_id=table_id, pages=pages,
                 title=table.get("title") or "")
    g.warnings = list(table.get("warnings", [])) + list(table.get("unresolved", []))

    period_ids: dict[str, str] = {}
    col_ids: dict[int, str] = {}
    for c in table.get("columns", []):
        per = (c.get("period") or "").strip()
        if per and per not in period_ids:
            period_ids[per] = g.add(Node(id=f"{table_id}:period:{len(period_ids)}",
                                         type="period", label=per))
        vid = g.add(Node(
            id=f"{table_id}:visit:{c['index']}", type="visit",
            label=c.get("label") or f"col{c['index']}",
            attrs={k: c.get(k) for k in ("visit", "day", "week", "window")},
            provenance=[Provenance(page=pages[0], source=source)]))
        col_ids[c["index"]] = vid
        if per:
            g.link(vid, period_ids[per], "visit_in_period")

    cat_id: str | None = None
    row_ids: dict[int, str] = {}
    for r in table.get("rows", []):
        pv = [Provenance(page=r.get("page", pages[0]), source=source)]
        if r.get("kind") == "category":
            cat_id = g.add(Node(id=f"{table_id}:cat:{r['index']}", type="category",
                                label=r.get("label", ""), provenance=pv))
            continue
        aid = g.add(Node(id=f"{table_id}:asmt:{r['index']}", type="assessment",
                         label=r.get("label", ""), provenance=pv,
                         attrs={"indent": r.get("indent", 0)}))
        row_ids[r["index"]] = aid
        if cat_id:
            g.link(aid, cat_id, "assessment_in_category")
        for j, c in enumerate(r.get("cells", [])):
            vid = col_ids.get(c.get("column"))
            if vid is None:
                g.warnings.append(
                    f"cell '{c.get('raw')}' on row '{r.get('label','')[:30]}' "
                    f"references column {c.get('column')} which does not exist")
                continue
            cid = g.add(Node(
                id=f"{table_id}:cell:{r['index']}:{c['column']}", type="cell",
                label=c.get("raw", ""), provenance=pv,
                attrs={"shaded": c.get("shaded", False),
                       "markers": c.get("markers", [])},
                ambiguous=bool(c.get("ambiguous"))))
            g.link(cid, aid, "cell_of_assessment")
            g.link(cid, vid, "cell_at_visit")

    # Footnotes last, so every anchor they might point at already exists.
    by_marker: dict[str, str] = {}
    for i, fn in enumerate(table.get("footnotes", [])):
        fid = g.add(Node(
            id=f"{table_id}:fn:{i}", type="footnote", label=fn.get("text", ""),
            attrs={"marker": fn.get("marker", ""),
                   "complete": fn.get("appears_complete", True),
                   "continued_on": fn.get("continued_on", [])},
            provenance=[Provenance(page=fn.get("page", pages[-1]), source=source)]))
        if fn.get("marker"):
            by_marker[norm_marker(fn["marker"])] = fid
        for a in fn.get("attaches_to", []):
            tgt = None
            if a.get("kind") == "cell":
                tgt = f"{table_id}:cell:{a.get('row')}:{a.get('column')}"
            elif a.get("kind") in ("row", "assessment"):
                tgt = row_ids.get(a.get("row"))
            elif a.get("kind") in ("column", "visit"):
                tgt = col_ids.get(a.get("column"))
            if tgt and any(n.id == tgt for n in g.nodes):
                g.link(fid, tgt, "footnote_annotates")

    # Second pass: markers recorded on cells and rows, bound to their footnote.
    # Recall-first -- a marker that matches a footnote is linked even when the
    # footnote did not name the cell itself, and conflicts are reported.
    for n in g.nodes:
        for mk in (n.attrs.get("markers") or []):
            fid = by_marker.get(norm_marker(str(mk)))
            if fid and not any(e.src == fid and e.dst == n.id
                               and e.type == "footnote_annotates" for e in g.edges):
                g.link(fid, n.id, "footnote_annotates", inferred_from="marker")
            elif not fid:
                g.warnings.append(
                    f"marker '{mk}' on {n.type} '{n.label[:30]}' matches no footnote")
    return g
