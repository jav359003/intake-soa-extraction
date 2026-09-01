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
