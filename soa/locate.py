"""Locate the Schedule of Activities table(s) in a protocol PDF.

The locator may not be told where the table is, and the section heading is
unreliable -- of the five reference protocols only two carry a schedule-like
heading on the table page itself (see bench/GROUND_TRUTH.md). So the primary
signal is the *shape* of the page, not its words: an SoA is a wide grid of very
short cell tokens sharing a small number of column positions. Headings are a
bonus, not a gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import pymupdf

# "Schedule of Activities" is only one of the names this table goes by.
HEADING = re.compile(
    r"schedule of (activities|assessments|events|procedures|measures|study)"
    r"|study flow ?chart|flow ?chart|time and events|table of events"
    r"|overview of study assessments|schedule of evaluations",
    re.I,
)
# A generic table caption -- weaker than HEADING, but three of the five
# protocols title their SoA this way and nothing else.
CAPTION = re.compile(r"^\s*(table|appendix|attachment)\s+[\dIVXA-Z]+[.:]", re.I | re.M)
CONTINUED = re.compile(r"\b(cont(inued|'d)?\.?|concluded)\b", re.I)

# Cell tokens: X, 3X, Xa, (X), 6X, bullets, dashes, arrows. Deliberately loose --
# recall matters more than precision, and cell vocabulary varies by sponsor.
CELL = re.compile(r"^(\(?\d*[XxA-Za-z]?[Xx]\d*[a-z]?\)?|[•·▪◦]|[-–—]{1,2}|→|←|↔)$")

# A line that opens a footnote: a marker in the left margin. Markers vary by
# sponsor -- asterisk runs, superscript letters, daggers, parenthesised letters,
# and sponsor-specific forms like protocol5's "Xa -".
FN_LINE = re.compile(
    r"^\s{0,8}("
    r"[*†‡§¶]{1,4}\s*\S"          # * ** *** **** † ‡
    r"|X[a-z]\s*[-–—]"             # Xa - Xb -
    r"|\(?[a-z]\)\s"              # (a)  a)
    r"|[a-z]\.\s{1,3}\S"          # a. text
    r"|\d{1,2}\.\s{1,3}\S"       # 1. text  -- numbered note lists
    r"|note[s]?\b"
    r"|abbreviations?\b"
    r")", re.I | re.M)

# A new numbered section, appendix or attachment ends the footnote tail. This is
# the stop condition that keeps protocol12's notes (p49-50) while excluding the
# "13.1 Assessment Methods" section that follows on p51.
SECTION = re.compile(
    r"^[ \t]{0,6}(\d{1,2}(\.\d{1,2}){0,3}[ \t]+[A-Z][A-Za-z]"
    r"|APPENDIX|ATTACHMENT|SECTION\b|PROTOCOL ATTACHMENT)", re.M)


@dataclass
class PageFeatures:
    page: int
    n_words: int = 0
    n_cells: int = 0
    cell_ratio: float = 0.0
    n_columns: int = 0          # x-positions shared by many rows
    col_coverage: float = 0.0   # share of rows participating in those columns
    n_rules: int = 0            # ruling lines
    landscape: bool = False
    heading: bool = False
    caption: bool = False
    continued: bool = False
    grid: bool = False          # looks like a table in its own right
    footnoteish: bool = False   # carries marker-led lines
    new_section: bool = False   # opens a new numbered section / appendix
    first_line: str = ""
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _rows(words, tol: float = 3.0):
    """Group words into visual lines by their vertical midpoint."""
    out: list[list] = []
    for w in sorted(words, key=lambda w: (round(w[1] / tol), w[0])):
        mid = (w[1] + w[3]) / 2
        if out and abs(((out[-1][0][1] + out[-1][0][3]) / 2) - mid) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def _columns(rows, tol: float = 6.0, min_rows: int = 4):
    """Find x-positions that repeat down the page.

    A grid -- ruled or not -- puts its cells at the same handful of x
    positions on row after row. Borderless SoAs (three of our five) have no
    ruling lines at all, so this is the signal that actually carries.
    """
    starts: list[tuple[float, set[int]]] = []
    for i, row in enumerate(rows):
        for w in row:
            x = w[0]
            for cx, seen in starts:
                if abs(cx - x) <= tol:
                    seen.add(i)
                    break
            else:
                starts.append((x, {i}))
    cols = [(x, s) for x, s in starts if len(s) >= min_rows]
    covered = set()
    for _, s in cols:
        covered |= s
    return len(cols), (len(covered) / len(rows) if rows else 0.0)


def page_features(page: pymupdf.Page, index: int) -> PageFeatures:
    f = PageFeatures(page=index)
    words = page.get_text("words")
    text = page.get_text("text")
    f.n_words = len(words)
    f.first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")[:90]
    if not words:
        return f

    toks = [w[4] for w in words]
    f.n_cells = sum(1 for t in toks if CELL.match(t))
    f.cell_ratio = f.n_cells / len(toks)

    rows = _rows(words)
    f.n_columns, f.col_coverage = _columns(rows)

    drawings = page.get_drawings()
    f.n_rules = sum(
        1
        for d in drawings
        for item in d["items"]
        if item[0] == "l" or (item[0] == "re" and min(item[1].width, item[1].height) < 3)
    )

    r = page.rect
    f.landscape = r.width > r.height
    head_zone = "\n".join(text.splitlines()[:6])
    f.heading = bool(HEADING.search(head_zone))
    f.grid = f.n_cells >= 12 and f.n_columns >= 5 and f.cell_ratio >= 0.02
    f.footnoteish = len(FN_LINE.findall(text)) >= 2
    nonblank = [l for l in text.splitlines() if l.strip()]
    f.new_section = bool(SECTION.search("\n".join(nonblank[:12])))
    f.caption = bool(CAPTION.search(head_zone))
    f.continued = bool(CONTINUED.search(head_zone))

    # Scoring. Weights are deliberately blunt: the shape signals dominate and
    # the word signals only break ties. Tuned for recall -- a dropped SoA page
    # is the most heavily penalised failure in the brief.
    s = 0.0
    if f.n_cells >= 8:
        s += min(f.n_cells / 10.0, 6.0)
        f.reasons.append(f"{f.n_cells} cell-like tokens")
    if f.n_columns >= 5 and f.col_coverage > 0.30:
        s += min(f.n_columns / 3.0, 4.0)
        f.reasons.append(f"{f.n_columns} repeated column positions, {f.col_coverage:.0%} of rows")
    if f.n_rules >= 20:
        s += 1.5
        f.reasons.append(f"{f.n_rules} ruling lines")
    if f.heading:
        s += 2.5
        f.reasons.append("schedule-like heading")
    if f.caption:
        s += 1.0
        f.reasons.append("table caption")
    if f.landscape:
        s += 1.0
        f.reasons.append("landscape page")
    # A page with a heading and almost no words is a divider/title page, not a
    # table. protocol1 p52 and p89 are exactly this trap.
    if f.n_words < 60 and f.n_cells < 5:
        s *= 0.15
        f.reasons.append("sparse page, likely a divider")
    f.score = s
    return f


def _expand(feats: list[PageFeatures], seed: int, max_table: int = 6,
            max_tail: int = 3) -> list[int]:
    """Grow a seed page into the full span of one SoA.

    Two phases, because the pages that continue a table and the pages that
    carry its footnotes look nothing alike.

    *Table phase*: keep going while the next page still has grid shape.
    Continuation pages score lower than the seed -- narrower, often heading-less
    -- so shape, not score, is the test.

    *Footnote tail*: once the grid stops, keep taking pages while they read as
    marker-led notes and no new section has opened. protocol9's footnotes sit
    three pages after its table starts, and protocol12's spill from p49 onto
    p50 with no marker and no heading to say they belong. Truncating either is
    a graded failure; running on into the next section is merely noise.
    """
    by_page = {f.page: f for f in feats}
    n = len(feats)
    span = {seed}

    for step in (1, -1):
        page = seed + step
        while 0 < page <= n and len(span) < max_table:
            f = by_page[page]
            if f.new_section and not f.continued:
                break
            if not (f.grid or f.continued):
                break
            span.add(page)
            page += step

    # Footnote tail: forward only, from the last table page.
    page = max(span) + 1
    taken = 0
    while 0 < page <= n and taken < max_tail:
        f = by_page[page]
        if f.new_section or f.grid:
            break
        if not (f.footnoteish or f.continued):
            break
        span.add(page)
        taken += 1
        page += 1
    return sorted(span)


def locate(pdf_path: str, threshold: float = 5.0, seed_margin: float = 0.55) -> dict:
    """Return one entry per distinct SoA found, each a contiguous page span.

    A protocol may hold more than one schedule -- a main table plus a PK
    sub-schedule or an extension schedule -- so this returns a list, never a
    single answer.
    """
    doc = pymupdf.open(pdf_path)
    feats = [page_features(p, i + 1) for i, p in enumerate(doc)]
    top = max((f.score for f in feats), default=0.0)
    if top <= 0:
        return {"pdf": pdf_path, "n_pages": len(feats), "tables": [], "features": [asdict(f) for f in feats]}

    # Seeds must be close to the best page in the document. Absolute score is
    # not comparable across protocols -- a 2011 Word table and a modern ruled
    # one land in different ranges -- so the bar is relative.
    seed_bar = max(threshold, top * seed_margin)

    seeds = sorted((f for f in feats if f.score >= seed_bar), key=lambda f: -f.score)
    tables, claimed = [], set()
    for s in seeds:
        if s.page in claimed:
            continue
        span = _expand(feats, s.page)
        span = [p for p in span if p not in claimed] or [s.page]
        claimed.update(span)
        tables.append({
            "pages": span,
            "seed": s.page,
            "score": s.score,
            "heading": s.first_line,
            "reasons": s.reasons,
        })
    tables.sort(key=lambda t: t["pages"][0])
    return {
        "pdf": pdf_path,
        "n_pages": len(feats),
        "tables": tables,
        "features": [asdict(f) for f in feats],
    }


if __name__ == "__main__":
    import sys, json, pathlib

    for p in sys.argv[1:] or sorted(str(x) for x in pathlib.Path("protocols").glob("*.pdf")):
        r = locate(p)
        print(f"\n===== {pathlib.Path(p).name}  ({r['n_pages']} pages)")
        for t in r["tables"]:
            pages = ", ".join(str(x) for x in t["pages"])
            print(f"  pages [{pages}]  seed=p{t['seed']} score={t['score']:.1f}")
            print(f"        {'; '.join(t['reasons'])}")
