"""Stitcher tests on clean synthetic pages.

These exist to separate two failures that look identical from the outside: the
stitching logic being wrong, and the stitching logic being fed a bad extraction.
The inputs here are hand-written and correct, so anything that fails is the
stitcher's fault.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soa.stitch import merge_pages, to_graph, decide_axis


def page(cols, rows, footnotes=(), title="T", axis=None, is_soa=True):
    return {
        "is_soa_page": is_soa, "title": title,
        "continuation": {"is_continuation": axis is not None, "axis": axis,
                         "evidence": "test"},
        "column_headers": [], "columns": cols, "rows": rows,
        "footnotes": list(footnotes), "unresolved": [],
    }


def col(i, label, period=None):
    return {"index": i, "period": period, "visit": label, "day": None,
            "week": None, "window": None, "markers": [], "label": label}


def row(i, label, cells, kind="assessment", markers=()):
    return {"index": i, "kind": kind, "label": label, "indent": 0,
            "markers": list(markers),
            "cells": [{"column": c, "raw": v, "markers": list(m),
                       "shaded": False, "ambiguous": False}
                      for c, v, m in cells]}


def test_row_continuation():
    """Same columns, new assessments -- concatenate rows, keep one column set."""
    p1 = page([col(0, "Day 1"), col(1, "Day 2")],
              [row(0, "Consent", [(0, "X", ())]),
               row(1, "Vitals",  [(0, "1X", ()), (1, "1X", ())])])
    p2 = page([col(0, "Day 1"), col(1, "Day 2")],
              [row(0, "ECG",     [(1, "1X", ())]),
               row(1, "Weight",  [(0, "1X", ()), (1, "1X", ())])])
    t = merge_pages([p1, p2], [10, 11])
    assert t["axes"][1]["axis"] == "rows", t["axes"]
    assert len(t["columns"]) == 2, t["columns"]
    assert [r["label"] for r in t["rows"]] == ["Consent", "Vitals", "ECG", "Weight"]


def test_column_continuation():
    """Same rows restated, new visits -- merge columns, do not duplicate rows."""
    rows_a = [row(0, "Consent", [(0, "X", ())]),
              row(1, "Vitals",  [(0, "X", ())]),
              row(2, "ECG",     [(0, "X", ())])]
    rows_b = [row(0, "Consent", []),
              row(1, "Vitals",  [(0, "X", ())]),
              row(2, "ECG",     [(0, "X", ())])]
    p1 = page([col(0, "Week 0")], rows_a)
    p2 = page([col(0, "Week 4")], rows_b)
    t = merge_pages([p1, p2], [53, 54])
    assert t["axes"][1]["axis"] == "columns", t["axes"]
    assert len(t["rows"]) == 3, [r["label"] for r in t["rows"]]
    assert len(t["columns"]) == 2, t["columns"]
    vitals = next(r for r in t["rows"] if r["label"] == "Vitals")
    assert sorted(c["column"] for c in vitals["cells"]) == [0, 1]


def test_column_continuation_keeps_new_row():
    """A row appearing only on the continuation page is kept, with a warning.
    Recall over precision: dropping it would delete an assessment."""
    p1 = page([col(0, "Week 0")], [row(0, "Consent", [(0, "X", ())]),
                                   row(1, "Vitals", [(0, "X", ())]),
                                   row(2, "ECG", [(0, "X", ())])])
    p2 = page([col(0, "Week 4")], [row(0, "Consent", []),
                                   row(1, "Vitals", [(0, "X", ())]),
                                   row(2, "ECG", [(0, "X", ())]),
                                   row(3, "Exit interview", [(0, "X", ())])])
    t = merge_pages([p1, p2], [53, 54])
    assert "Exit interview" in [r["label"] for r in t["rows"]]
    assert any("not present on the previous page" in w for w in t["warnings"])


def test_axis_disagreement_is_warned_not_hidden():
    """Extractor says rows, geometry says columns -- geometry wins, loudly."""
    rows_same = [row(0, "Consent", []), row(1, "Vitals", []), row(2, "ECG", [])]
    p1 = page([col(0, "Week 0")], rows_same)
    p2 = page([col(0, "Week 4")], rows_same, axis="rows")
    axis, evidence, confident = decide_axis(p1, p2)
    assert axis == "columns" and confident is False
    assert "extractor said 'rows'" in evidence


def test_footnote_continuation_across_pages():
    """A truncated footnote rejoins the unmarked fragment on the next page."""
    p1 = page([col(0, "Wk 1")], [row(0, "ECG", [(0, "X", ())])],
              footnotes=[{"marker": "c", "text": "ECG performed in triplicate at",
                          "appears_complete": False, "attaches_to": []}])
    p2 = page([], [], is_soa=False,
              footnotes=[{"marker": "", "text": "screening and Week 4 only.",
                          "appears_complete": True, "attaches_to": []}])
    t = merge_pages([p1, p2], [48, 49])
    assert len(t["footnotes"]) == 1, t["footnotes"]
    fn = t["footnotes"][0]
    assert fn["text"] == "ECG performed in triplicate at screening and Week 4 only."
    assert fn["appears_complete"] is True and 49 in fn["continued_on"]


def test_truncated_footnote_with_no_continuation_warns():
    p1 = page([col(0, "Wk 1")], [row(0, "ECG", [(0, "X", ())])],
              footnotes=[{"marker": "c", "text": "cut off here",
                          "appears_complete": False, "attaches_to": []}])
    t = merge_pages([p1], [48])
    assert any("looks truncated" in w for w in t["warnings"])


def test_marker_binds_to_cell_in_graph():
    """A marker on a cell becomes a footnote_annotates edge onto that cell."""
    p1 = page([col(0, "Wk 1")],
              [row(0, "Urine tox", [(0, "X", ("b",))])],
              footnotes=[{"marker": "b", "text": "Once during the week.",
                          "appears_complete": True, "attaches_to": []}])
    g = to_graph(merge_pages([p1], [25]), "p15", "t1", [25])
    links = [e for e in g.edges if e.type == "footnote_annotates"]
    assert len(links) == 1
    cell = next(n for n in g.nodes if n.type == "cell")
    assert links[0].dst == cell.id and links[0].attrs.get("inferred_from") == "marker"


def test_orphan_marker_warns():
    p1 = page([col(0, "Wk 1")], [row(0, "Urine tox", [(0, "X", ("z",))])])
    g = to_graph(merge_pages([p1], [25]), "p15", "t1", [25])
    assert any("matches no footnote" in w for w in g.warnings)


def test_category_rows_are_not_assessments():
    p1 = page([col(0, "Wk 1")],
              [row(0, "Safety Assessments", [], kind="category"),
               row(1, "ECG", [(0, "X", ())])])
    g = to_graph(merge_pages([p1], [25]), "p15", "t1", [25])
    assert len(g.by_type("category")) == 1 and len(g.by_type("assessment")) == 1
    assert any(e.type == "assessment_in_category" for e in g.edges)


def test_footnote_only_page_contributes_no_rows():
    p1 = page([col(0, "Wk 1")], [row(0, "ECG", [(0, "X", ())])])
    p2 = page([], [], is_soa=False,
              footnotes=[{"marker": "a", "text": "note", "appears_complete": True,
                          "attaches_to": []}])
    t = merge_pages([p1, p2], [26, 29])
    assert len(t["rows"]) == 1 and len(t["footnotes"]) == 1


def test_failed_page_is_reported_not_swallowed():
    """A page the extractor could not read must be shouted about.

    This is the protocol1 p53 case: the model returned nothing, the page
    became is_soa_page=None, and half the table vanished with no warning."""
    good = page([col(0, "Wk 1")], [row(0, "ECG", [(0, "X", ())])])
    bad = {"is_soa_page": None, "parse_error": "Expecting value: line 1 column 1"}
    t = merge_pages([good, bad], [53, 54])
    assert any("EXTRACTION FAILED" in w for w in t["warnings"]), t["warnings"]
    assert any("p54" in w for w in t["warnings"])


def test_axis_singular_form_is_understood():
    """Models write axis as "column" as readily as "columns"."""
    rows_same = [row(0, "Consent", []), row(1, "Vitals", []), row(2, "ECG", [])]
    p1 = page([col(0, "Week 0")], rows_same)
    p2 = page([col(0, "Week 4")], rows_same, axis="column")
    axis, evidence, confident = decide_axis(p1, p2)
    assert axis == "columns" and confident is True, (axis, evidence, confident)


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for name, fn in fns:
        try:
            fn(); print(f"  pass  {name}")
        except AssertionError as e:
            bad += 1; print(f"  FAIL  {name}: {e}")
    print(f"\n{len(fns)-bad}/{len(fns)} passing")
