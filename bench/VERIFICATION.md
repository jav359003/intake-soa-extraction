# Manual verification

Every table below was compared against the printed page, cell by cell, by
rendering the source page beside the extracted grid (`bench/verify.py`).

This is the only check that says the extraction is *correct*. The conservation
checks prove nothing was lost between stages; they cannot tell whether the page
was read right in the first place.

**Coverage: 3 of 5 protocols.** Engine: Gemini `3.7-flash` with fallbacks, the
run committed in `outputs/gemini/`.

---

## protocol15 — NIDO-CTO-0007, Cabergoline for Cocaine Dependence, p25

Single-page table, 9 visits, 31 assessments, 3 category rows, 5 footnotes.

| check | result |
|---|---|
| assessments | **31 / 31** |
| category rows | **3 / 3** (Screening, Safety, Efficacy) |
| visits | 9 / 9, plus the RANDOMIZATION divider, plus 1 spurious (below) |
| cell values verbatim | **no discrepancies found** |
| footnotes captured | **5 / 5** (`*`, `a`, `b`, `c`, `d`), full text |
| footnote anchor counts | **exact** — `b`=53, `c`=12, `a`=3, `d`=1, `*`=1, each matching a hand count of the page |

### What is wrong

**One spurious column.** The row-label header cell, printed "Assessment", was
read as a tenth visit. It carries no cell values, so nothing is misattributed,
but a reviewer sees a visit that does not exist. This is a precision cost, and
under the brief's weighting it is the cheap direction to err in.

**The RANDOMIZATION divider is represented as a column.** The page prints the
word vertically down a narrow band between Baseline and Treatment. The extractor
returned it as a column and said so in its own words: *"a narrow divider column
containing the vertically-set word 'RANDOMIZATION' ... it is a single merged
cell, so no per-row cells were emitted for it."* Defensible either way; it is
structurally present on the page and it holds no data. Flagged rather than
silently dropped, which is the behaviour that was wanted.

### A correction to an earlier finding

Partway through building this I recorded that the extractor was inserting a
space, returning `3 X` where the page printed `3X`. That was wrong, and reading
the page properly settled it: the source prints `3X` on the Adverse events row
and `3 X` on the SUI, Urine BE and Treatment compliance rows. The extractor
reproduced both exactly. It was being faithful and I was not checking.

The lesson is the one this file exists for: a discrepancy found by reading
output alone is a hypothesis, not a defect.

---

## protocol1 — Eli Lilly H2Q-MC-LZZT, Xanomeline in Alzheimer's, p53–54

Two pages continuing across the **column** axis: every row label repeats on p54
and the page supplies visits 9 through RT.

| check | result |
|---|---|
| assessments | 28 printed rows → 30 emitted (see the split below) |
| visits | **14 / 15** |
| cell values verbatim | no discrepancies found on p53 |
| footnotes | 5 legend entries captured, one duplicated |

### The defect this pass caught, and it was the worst one yet

The merged table reported **10 visits**. Both pages had extracted correctly —
7 visits each — and the stitcher had collapsed four of them.

Column merging matched labels fuzzily at a 0.88 similarity bar. Visit labels are
systematically similar by construction:

```
"Visit 11 / Week 20"  vs  "Visit 1 / Week -2"   0.933
"Visit 12 / Week 24"  vs  "Visit 1 / Week -2"   0.933
"Visit 13 / Week 26"  vs  "Visit 1 / Week -2"   0.933
"Visit 9  / Week 12"  vs  "Visit 4 / Week 2"    0.897
```

Visits 9, 11, 12 and 13 were merged into visit 1. **Four patient visits deleted
from the study**, with no warning, on the protocol used as the public CDISC
reference dataset.

Fixed: column identity is now exact after normalisation. Row labels are prose
and still match fuzzily; column labels are identifiers and do not. A near-match
that is not exact now emits a warning naming both, in case they really are the
same visit. Visits: 10 → 14.

### Still wrong

**One column missing.** p53 prints eight visit columns; the sixth is unlabeled
(a gap between visits 5 and 7, with no week number and no cells). The extractor
returned seven and dropped it. It carries no data, but it is a column on the
page and the count should be 15, not 14.

**One footnote duplicated.** The legend "Xb = Performed at this visit and via
telephone interview 2 weeks following this visit" is printed at the foot of both
pages and captured twice, once with 1 anchor and once with 5. The running-footer
dedupe only fires on unmarked lines; a *marked* footnote repeated on both pages
is not caught.

### An open question, and I do not think it is mine to settle

The page prints, inside what appears to be a single bordered cell:

```
Study drug record
Medications dispensed
Medications returned
```

with one row of X marks beneath at visits 3, 4, 5, 7, 8.

I treated this as three rows merged into one label and split them, marking all
three ambiguous and leaving the cells on the first. Looking at the printed
borders, it may equally be **one row with a three-line label** — in which case
the split invents two assessments that do not exist.

The two readings differ in what gets built: three forms or one. Recall-first
argues for splitting, and the split is flagged rather than silent, so a reviewer
sees it. But this is a question for a clinical SME, not a heuristic, and it is
written down here rather than guessed at quietly.

---

## protocol12 — NIDA, Modafinil for Methamphetamine Dependence, p48–50

Table on p48, footnotes running p49 → p50.

| check | result |
|---|---|
| assessments | **37 / 37** |
| category rows | **3 / 3** (Screening, Safety, Efficacy) |
| visits | 8 / 8, plus 1 spurious (below) |
| cell values | correct, with one case defect (below) |
| footnotes | **21** captured across three pages, **72** anchors |
| multi-line cell values | correct — `X` printed over `wk 6` is kept as one cell |

Row by row against the page, all 37 assessments matched, including the awkward
ones: `Adverse events` as `3X/week^d` then `3X^d` six times, `ASI-Lite Follow-up`
appearing only at weeks 5-7 and 12/Term, `CBT compliance` as `2X/week^h`.

The footnote work is the strongest result here. The block starts on p49 under
"Notes on the Schedule of Assessments" and runs onto p50, with 21 notes bound to
72 anchors — `Xb` alone carries 34. Earlier in the build this protocol returned
**zero** footnotes, because the extraction prompt told the model to return
nothing for a page with no grid.

### Defect: cell values are lowercased

The page prints `Xa`, `Xb`, `Xc`. The extractor returns raw value `x` with the
marker carried separately. The marker survives and the meaning survives, but the
character case does not, and the brief asks for values reproduced exactly.

Small, but it is a genuine verbatim failure and it is systematic rather than
occasional — it affects every marked cell on this table. It is not present on
protocol15, where `X` came back as `X`, so it is model variance on a page-by-page
basis rather than a rule.

### Inconsistency: the RANDOMIZATION divider

protocol15's vertical RANDOMIZATION band was returned as a column and explained.
protocol12 prints the same device and it was not returned at all. Neither is
wrong, but the same structure should not be handled two ways by the same system,
and today it is.

### One spurious column

As on protocol15, the row-label header cell "Assessment" is read as a visit. It
holds no values. Same cause, same cheap direction of error.

### A tooling bug that nearly became a false finding

My first pass through this table recorded three spurious assessments called
"wk 6". They do not exist. A cell that prints `X` above `wk 6` is one cell with
a timing qualifier, and the grid printer in `bench/verify.py` was rendering the
newline inside that cell as a line break, which looked exactly like an extra
row.

This is the second time in this verification pass that reading the output
instead of the page produced a defect that was not there. Both are recorded
because the pattern matters more than either instance: **an anomaly in a
rendering of the data is a hypothesis about the data, and the page is the only
thing that settles it.**

The timing-qualifier folding written in response is still in `stitch.py`
(`_fold_timing_rows`). It did not fire on any of the five protocols. It is
defensive code for a failure that has not yet been observed, which is worth
saying plainly rather than presenting as a fix.
