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
import copy
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
    if claimed in ("column", "col", "columns"):
        claimed = "columns"
    elif claimed in ("row", "rows"):
        claimed = "rows"
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


def _merge_columns(base: list[dict], new: list[dict], positional: bool = False,
                   warnings: list[str] | None = None
                   ) -> tuple[list[dict], dict[int, int]]:
    """Append genuinely new columns; map this page's indices onto the merged set.

    Two mapping strategies, because labels are not stable across pages.

    Positional, used when a page continues the *rows* of a table and carries
    the same number of columns: the Nth column on this page is the Nth column
    of the table. protocol9 restates its eleven study days three different ways
    -- "Opiate Agonist Phase (all Morphine)", then bare "1".."11", then
    "Day 1".."Day 11" -- so label matching finds nothing, appends twenty-two
    phantom columns, and every cell then references a column that does not
    exist. That single bug cost 190 of that table's cells.

    Label matching, used when a page adds new columns: a continuation page
    often repeats the first column or two before carrying on, and matching by
    label is what stops a repeated visit being counted twice.
    """
    out = list(base)
    mapping: dict[int, int] = {}

    if positional and base and len(new) == len(base):
        return out, {c["index"]: i for i, c in enumerate(new)}

    if positional and base and len(new) != len(base):
        n = min(len(new), len(base))
        mapping = {c["index"]: i for i, c in enumerate(new[:n])}
        for c in new[n:]:
            mapping[c["index"]] = len(out)
            out.append({**c, "index": len(out)})
        if warnings is not None:
            warnings.append(
                f"row-continuation page has {len(new)} columns against the table's "
                f"{len(base)}; the first {n} were aligned by position and "
                f"{len(new) - n} extra column(s) appended. Check whether the page "
                f"really adds visits or the extractor miscounted.")
        return out, mapping

    # Column identity must be exact, never fuzzy. Visit labels are
    # systematically similar by construction: "Visit 1 / Week -2" and
    # "Visit 11 / Week 20" are 0.93-similar strings and completely different
    # visits. Fuzzy matching merged protocol1's visits 9, 11, 12 and 13 into
    # visit 1 and deleted four patient visits from the study. Row labels are
    # prose and still match fuzzily; column labels are identifiers.
    for c in new:
        key = _norm(c.get("label", ""))
        hit = next((i for i, b in enumerate(out)
                    if key and _norm(b.get("label", "")) == key), None)
        if hit is None and key:
            near = [b.get("label", "") for b in out
                    if _similar(b.get("label", ""), c.get("label", ""), bar=0.85)]
            if near and warnings is not None:
                warnings.append(
                    f"column '{c.get('label','')}' closely resembles "
                    f"{near[:2]} but is not identical; kept as a separate visit. "
                    f"If these are the same visit the table now has a duplicate "
                    f"column.")
        if hit is None:
            mapping[c["index"]] = len(out)
            out.append({**c, "index": len(out)})
        else:
            mapping[c["index"]] = hit
    return out, mapping


def split_spans(per_page: list[dict], page_numbers: list[int]
                ) -> list[tuple[list[dict], list[int]]]:
    """Partition a located span into the distinct tables it actually holds.

    The locator grows a span by page shape, which correctly picks up
    continuation pages and footnote blocks -- but a protocol may print a second,
    unrelated schedule right after the first. protocol5 p51 is
    "APPENDIX II: Schedule of Blood Collections", a sixteen-column PK table
    immediately after the twelve-column main schedule. Merging the two produces
    one table that is neither.

    A split needs two independent signals agreeing, because splitting a genuine
    continuation is as damaging as merging two tables:
      - the page says outright it is not a continuation, and
      - it carries a title that is not the title of the table so far.

    When they disagree, the pages stay together: a merged table keeps every
    cell and warns, which is the recoverable direction.
    """
    groups: list[tuple[list[dict], list[int]]] = []
    cur: list[dict] = []
    cur_pages: list[int] = []
    cur_title = ""

    for pno, page in zip(page_numbers, per_page):
        title = (page.get("title") or "").strip()
        if page.get("is_soa_page") and cur:
            declared_new = (page.get("continuation") or {}).get("is_continuation") is False
            different_title = bool(title) and bool(cur_title) and not _similar(
                title, cur_title, bar=0.75)
            if declared_new and different_title:
                groups.append((cur, cur_pages))
                cur, cur_pages, cur_title = [], [], title
        if not cur_title and title:
            cur_title = title
        cur.append(page)
        cur_pages.append(pno)

    if cur:
        groups.append((cur, cur_pages))
    return groups


# A cell that says "X" on one line and "wk 6" beneath it is one cell with a
# timing qualifier. Extractors routinely return that second line as its own
# row, which invents an assessment called "wk 6". Purely temporal labels are
# never assessment names in an SoA -- an activity is a thing done, not a time.
TIMING_ONLY = re.compile(
    r"^\(?\s*(wk|week|wks|weeks|day|days|d|month|months|mo|hr|hrs|h|q\dw)\b"
    r"[\s.\-–—0-9,and/]*\)?$", re.I)


def _fold_timing_rows(page: dict, pno: int, warnings: list[str]) -> None:
    """Fold rows that are only a timing qualifier back into the row above.

    Their cells belong to the assessment above them, so they are merged there
    rather than discarded: the value is real, only the row is not.
    """
    out: list[dict] = []
    for r in page.get("rows", []):
        label = (r.get("label") or "").strip()
        if out and label and TIMING_ONLY.match(label) and out[-1].get("kind") == "assessment":
            prev = out[-1]
            for c in r.get("cells", []):
                prev.setdefault("cells", []).append({**c, "qualifier": label})
            warnings.append(
                f"p{pno}: '{label}' was returned as its own assessment; it is a "
                f"timing qualifier printed under a cell, so its "
                f"{len(r.get('cells', []))} value(s) were folded into "
                f"'{prev.get('label','')[:40]}' and the row dropped.")
            continue
        out.append(r)
    if len(out) != len(page.get("rows", [])):
        for i, r in enumerate(out):
            r["index"] = i
        page["rows"] = out


def _split_merged_rows(page: dict, pno: int, warnings: list[str]) -> None:
    """Recover rows an extractor collapsed into a single label.

    A label carrying an embedded newline means several printed rows were read
    as one. protocol1 came back with "Study drug record / Medications dispensed
    / Medications returned" as a single assessment on both of its pages, which
    deletes two assessments from the study.

    The rows are restored so nothing is missing, but the cells are NOT split:
    which value belonged to which row is not recoverable from a merged label,
    and inventing an attribution would be worse than admitting the gap. The
    cells stay on the first row and every recovered row is marked ambiguous
    with a warning naming the page, so a reviewer knows exactly what to check.
    """
    out, changed = [], False
    for r in page.get("rows", []):
        raw_parts = [x.strip() for x in re.split(r"[\r\n]+", r.get("label", "")) if x.strip()]
        # A newline in a label means one of two very different things: several
        # printed rows read as one, or a single label wrapped across lines. Two
        # rows would each start like a label; a wrapped continuation reads as a
        # fragment -- it opens with a bracket, a lowercase word, or a unit or
        # timing qualifier. protocol9 wraps constantly ("•Objective Opiate
        # Withdrawal Scale (15)" / "(OOWS Handlesman) (1000h)") and splitting
        # those invents assessments that do not exist.
        parts: list[str] = []
        for x in raw_parts:
            looks_like_continuation = (
                x[0] in "([{" or x[0].islower()
                or re.match(r"^\d{3,4}\s*h\b", x)          # a clock time
                or re.match(r"^(and|or|with|per|for|in|at|to)\b", x, re.I))
            # A line ending in a dash, comma or colon is mid-phrase; whatever
            # follows completes it. protocol9 wraps "Modified Clinical Global
            # Impressions Scale -" onto "Patient (17) (NIMH MCGI)".
            if parts and re.search(r"[-\u2013\u2014,:;/]\s*$", parts[-1]):
                looks_like_continuation = True
            if parts and looks_like_continuation:
                parts[-1] = f"{parts[-1]} {x}"
            else:
                parts.append(x)
        if len(parts) < 2:
            if len(raw_parts) > 1:
                r = {**r, "label": parts[0] if parts else r.get("label", "")}
            out.append(r)
            continue
        changed = True
        first = {**r, "label": parts[0], "ambiguous": True}
        out.append(first)
        for extra in parts[1:]:
            out.append({**r, "label": extra, "cells": [], "ambiguous": True,
                        "recovered_from_merge": True})
        warnings.append(
            f"p{pno}: '{parts[0][:40]}' was extracted with {len(parts) - 1} other "
            f"row label(s) merged into it ({'; '.join(x[:30] for x in parts[1:])}). "
            f"The rows were separated so none is missing, but all {len(r.get('cells', []))} "
            f"cell values stayed on the first row -- their true attribution is not "
            f"recoverable from the merged label and needs a human eye.")
    if changed:
        for i, r in enumerate(out):
            r["index"] = i
        page["rows"] = out


def merge_pages(pages: list[dict], page_numbers: list[int]) -> dict:
    """Fold a list of per-page extractions into one table dict."""
    table = {"title": None, "columns": [], "rows": [], "footnotes": [],
             "warnings": [], "unresolved": [], "page_of_row": {}, "axes": []}
    prev_grid: dict | None = None

    for pno, page in zip(page_numbers, pages):
        if page.get("is_soa_page") is None:
            # Extraction failed on this page. Silence here is the worst
            # outcome in the brief -- a dropped page is a dropped set of
            # visits or assessments that nobody notices.
            table["warnings"].append(
                f"p{pno}: EXTRACTION FAILED ({page.get('parse_error', 'no reason given')}). "
                f"Every row and column on this page is missing from the output.")
            continue

        if not page.get("is_soa_page"):
            # A page with no grid is still in the span for a reason: it carries
            # the footnote block. Fold its notes in and move on.
            for fn in page.get("footnotes", []):
                table["footnotes"].append({**fn, "page": pno})
            table["unresolved"] += [f"p{pno}: {u}" for u in page.get("unresolved", [])]
            continue

        _fold_timing_rows(page, pno, table["warnings"])
        _split_merged_rows(page, pno, table["warnings"])
        table["title"] = table["title"] or page.get("title")
        table["unresolved"] += [f"p{pno}: {u}" for u in page.get("unresolved", [])]

        if prev_grid is None:
            table["columns"] = [dict(c) for c in page.get("columns", [])]
            for r in page.get("rows", []):
                r = copy.deepcopy(r); r["page"] = pno
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
                    table["columns"], page.get("columns", []),
                    warnings=table["warnings"])
                for r in page.get("rows", []):
                    tgt = next((t for t in table["rows"]
                                if t.get("kind") == r.get("kind")
                                and _similar(t.get("label", ""), r.get("label", ""))), None)
                    if tgt is None:
                        # A row that appears only on the continuation page is
                        # still a real assessment. Add it rather than drop it.
                        r = copy.deepcopy(r); r["page"] = pno
                        r["index"] = len(table["rows"])
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
                # Row continuation: the column set is the same table, restated,
                # so trust position over the page's own labels for it.
                # Keep the returned column list: a row-continuation page can
                # still carry a column the first page did not show, and
                # discarding it here leaves its cells pointing at a column that
                # was mapped but never added.
                table["columns"], cmap = _merge_columns(
                    table["columns"], page.get("columns", []),
                    positional=True, warnings=table["warnings"])
                for r in page.get("rows", []):
                    r = copy.deepcopy(r); r["page"] = pno
                    r["index"] = len(table["rows"])
                    r["cells"] = [{**c, "column": cmap.get(c["column"], c["column"])}
                                  for c in r.get("cells", [])]
                    table["rows"].append(r)

        for fn in page.get("footnotes", []):
            table["footnotes"].append({**fn, "page": pno})
        prev_grid = page

    furniture = [0]
    table["footnotes"] = _join_footnotes(table["footnotes"], table["warnings"], furniture)
    table["furniture_dropped"] = furniture[0]
    return table


def _join_footnotes(footnotes: list[dict], warnings: list[str],
                    dropped: list[int] | None = None) -> list[dict]:
    """Rejoin a footnote whose text ran onto the following page.

    A footnote block routinely spills past a page break, and the continuation
    carries no marker, no header and nothing saying it belongs to a table two
    pages back. The signal available is: the previous footnote was reported
    incomplete, and the next fragment arrived without a marker.
    """
    dropped = dropped if dropped is not None else [0]
    out: list[dict] = []
    seen_unmarked: dict[str, dict] = {}
    for fn in footnotes:
        marker = (fn.get("marker") or "").strip()
        body = (fn.get("text") or "").strip()
        if not marker and body and body in seen_unmarked:
            seen_unmarked[body].setdefault("also_on", []).append(fn.get("page"))
            warnings.append(
                f"'{body[:50]}' appears verbatim on more than one page with no "
                f"marker; treated as a running footer rather than a second footnote")
            dropped[0] += 1
            continue
        if out and not marker and out[-1].get("appears_complete") is False:
            prev = out[-1]
            prev["text"] = f"{prev['text'].rstrip()} {fn.get('text','').lstrip()}".strip()
            prev["appears_complete"] = fn.get("appears_complete", True)
            prev.setdefault("continued_on", []).append(fn.get("page"))
            continue
        rec = dict(fn)
        out.append(rec)
        if not marker and body:
            seen_unmarked[body] = rec
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
            banding = [c for c in r.get("cells", []) if not (c.get("raw") or "").strip()]
            real = [c for c in r.get("cells", []) if (c.get("raw") or "").strip()]
            g.discarded += len(banding)
            if real:
                g.warnings.append(
                    f"category row '{r.get('label','')[:40]}' carries "
                    f"{len(real)} non-empty cell(s) "
                    f"({', '.join(repr(c.get('raw')) for c in real[:3])}). Either it "
                    f"is an assessment misread as a heading, or those values belong "
                    f"to another row; they are not in the output.")
            cat_id = g.add(Node(id=f"{table_id}:cat:{r['index']}", type="category",
                                label=r.get("label", ""), provenance=pv,
                                attrs={"markers": r.get("markers", []) or []}))
            continue
        aid = g.add(Node(id=f"{table_id}:asmt:{r['index']}", type="assessment",
                         label=r.get("label", ""), provenance=pv,
                         ambiguous=bool(r.get("ambiguous")),
                         note=("recovered from a row label that had several rows "
                               "merged into it" if r.get("recovered_from_merge") else ""),
                         attrs={"indent": r.get("indent", 0),
                                "markers": r.get("markers", []) or []}))
        row_ids[r["index"]] = aid
        if cat_id:
            g.link(aid, cat_id, "assessment_in_category")
        for j, c in enumerate(r.get("cells", [])):
            vid = col_ids.get(c.get("column"))
            if vid is None:
                key = c.get("column")
                if key not in col_ids:
                    col_ids[key] = g.add(Node(
                        id=f"{table_id}:visit:unresolved:{key}", type="visit",
                        label=f"(unresolved column {key})", ambiguous=True,
                        note="cells referenced this column but no header was "
                             "matched to it; kept so the values are not lost",
                        provenance=[Provenance(page=pages[0], source=source)]))
                    g.warnings.append(
                        f"column {key} has cells but no matching header; kept as an "
                        f"unresolved visit so its values stay in the output")
                vid = col_ids[key]
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


# ---------------------------------------------------------------------------
# Conservation checks
#
# Every heuristic in this file is fitted to a handful of documents and will be
# wrong on some protocol nobody has seen. That is tolerable. What is not
# tolerable is being wrong *quietly*: the two worst bugs found so far -- a page
# that failed extraction and read as "no table", and a column mapping that
# orphaned 190 cells -- both produced correct-looking output with no signal.
#
# These checks do not make the heuristics smarter. They make arithmetic out of
# the merge, so that on ANY document, whatever the layout, a loss shows up as a
# number that does not add up rather than as a table that merely looks short.
# ---------------------------------------------------------------------------

def conservation_report(per_page: list[dict], page_numbers: list[int],
                        table: dict, graph: "SoAGraph") -> list[str]:
    """Compare what the pages offered against what survived the merge."""
    problems: list[str] = []

    in_cells = sum(len(r.get("cells", []))
                   for p in per_page if p.get("is_soa_page")
                   for r in p.get("rows", []))
    in_rows = sum(1 for p in per_page if p.get("is_soa_page")
                  for r in p.get("rows", []) if r.get("kind") == "assessment")
    in_fns = sum(len(p.get("footnotes", [])) for p in per_page)

    out_cells = len(graph.by_type("cell"))
    out_rows = len(graph.by_type("assessment"))
    out_fns = len(graph.by_type("footnote"))

    # Cells: a column continuation legitimately merges cells onto existing
    # rows, so the total should be preserved, never reduced.
    if out_cells + graph.discarded < in_cells:
        problems.append(
            f"CONSERVATION: pages produced {in_cells} cells, the merged table has "
            f"{out_cells} and {graph.discarded} were discarded for a stated reason. "
            f"{in_cells - out_cells - graph.discarded} are unaccounted for.")

    # Rows: a column continuation restates rows, so the merged count is
    # legitimately lower. It can never exceed the input.
    if out_rows > in_rows:
        problems.append(
            f"CONSERVATION: merged table has {out_rows} assessments from {in_rows} "
            f"on the pages; rows were duplicated rather than merged.")

    # Footnotes only ever combine (a spill rejoins its parent), never vanish.
    joined = sum(len(n.attrs.get("continued_on") or []) for n in graph.by_type("footnote"))
    furniture = table.get("furniture_dropped", 0)
    if out_fns + joined + furniture < in_fns:
        problems.append(
            f"CONSERVATION: pages produced {in_fns} footnotes; {out_fns} survived, "
            f"{joined} joined to a previous one, {furniture} were repeated page "
            f"furniture. {in_fns - out_fns - joined - furniture} unaccounted for.")

    # Every page in the span was included for a reason. One that contributed
    # nothing at all is either a locator false positive or a silent failure,
    # and the two are worth telling apart.
    for pno, p in zip(page_numbers, per_page):
        if p.get("is_soa_page") is None:
            continue                                  # already reported loudly
        gave = (len(p.get("rows", [])) or 0) + (len(p.get("footnotes", [])) or 0)
        if gave == 0:
            problems.append(
                f"CONSERVATION: p{pno} is inside the located span but produced no "
                f"rows and no footnotes -- either a locator false positive or an "
                f"extraction that returned an empty table.")

    # A cell must sit at a real visit and on a real assessment, or it is
    # unreachable in the graph and invisible in every view built from it.
    have_of = {e.src for e in graph.edges if e.type == "cell_of_assessment"}
    have_at = {e.src for e in graph.edges if e.type == "cell_at_visit"}
    orphans = [n.id for n in graph.by_type("cell")
               if n.id not in have_of or n.id not in have_at]
    if orphans:
        problems.append(
            f"CONSERVATION: {len(orphans)} cells are not attached to both an "
            f"assessment and a visit, so they cannot be read back out of the graph.")

    # Markers are the footnote linkage. An unbound one is a lost qualifier,
    # which in this domain is the difference between "every visit" and "every
    # visit for Cohort B only".
    marked = sum(len(n.attrs.get("markers") or []) for n in graph.nodes)
    linked = sum(1 for e in graph.edges if e.type == "footnote_annotates")
    if marked and linked == 0:
        problems.append(
            f"CONSERVATION: {marked} markers were read off the page but none bound "
            f"to a footnote. Every footnote qualifier on this table is lost.")
    return problems


def reconcile_across_tables(graphs: list["SoAGraph"]) -> None:
    """Bind markers to footnotes that ended up on a sibling table's page.

    When a span splits, a page can carry both the tail of one table and the
    start of the next. protocol5 p51 opens with the footnotes for the main
    schedule ("*Days -15 through -9 are allotted for washout...") and then
    prints APPENDIX II as a separate table. Splitting by title sends those
    footnotes to the wrong table and leaves the main one with orphan markers.

    Rather than guess at page geometry, this matches on the evidence that
    survives: a marker with no footnote here, and exactly one footnote with
    that marker somewhere else in the same document. The footnote is copied in
    and the borrow is recorded, so a reader can see it was inferred.
    """
    by_marker: dict[str, list[tuple["SoAGraph", Node]]] = {}
    for g in graphs:
        for n in g.by_type("footnote"):
            mk = norm_marker(n.attrs.get("marker", ""))
            if mk:
                by_marker.setdefault(mk, []).append((g, n))

    for g in graphs:
        linked = {e.dst for e in g.edges if e.type == "footnote_annotates"}
        for node in list(g.nodes):
            if node.type == "footnote" or node.id in linked:
                continue
            for mk in (node.attrs.get("markers") or []):
                key = norm_marker(str(mk))
                here = any(norm_marker(n.attrs.get("marker", "")) == key
                           for n in g.by_type("footnote"))
                if here or key not in by_marker:
                    continue
                owners = [(og, n) for og, n in by_marker[key] if og is not g]
                if len(owners) != 1:
                    continue                       # ambiguous, leave it flagged
                og, src = owners[0]
                fid = f"{g.table_id}:fn:borrowed:{key}"
                if not any(n.id == fid for n in g.nodes):
                    g.add(Node(id=fid, type="footnote", label=src.label,
                               attrs={**src.attrs, "borrowed_from": og.table_id},
                               provenance=list(src.provenance), ambiguous=True,
                               note=f"printed on {og.pages}, which this document "
                                    f"splits into a separate table"))
                    g.warnings.append(
                        f"footnote '{mk}' was printed with {og.table_id} but is the "
                        f"only match for markers on this table; linked across and "
                        f"marked inferred")
                g.link(fid, node.id, "footnote_annotates", inferred_from="sibling-table")
