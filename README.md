# Schedule of Activities extractor

Give it a clinical trial protocol PDF. It finds the Schedule of Activities,
extracts it faithfully, and renders it beside the page it came from so you can
check it.

```bash
pip install -r requirements.txt
echo 'GEMINI_API_KEY=...' > .env          # aistudio.google.com, free tier
python3 -m uvicorn ui.server:app --port 8077
# open http://127.0.0.1:8077 and drop in a PDF
```

Works on a protocol it has never seen. Nothing is precomputed. To run without
any API key at all, pick the `text-layer` engine in the dropdown — it is the
benchmark baseline and its output is visibly worse, deliberately.

CLI:

```bash
python3 -m soa.pipeline protocols/*.pdf --engine gemini --out outputs/gemini
./run_tests.sh                            # 28 tests, no API calls
```

---

## Architecture

```
PDF
 │
 ├── locate.py    which pages hold a schedule?          text layer only, no API
 ├── render.py    those pages → 300 DPI PNG
 ├── extract*.py  page image → cells, verbatim          swappable engine
 ├── stitch.py    pages → one table, footnotes rejoined deterministic
 ├── schema.py    → graph: nodes + edges + provenance
 └── ui/          upload, view, click a cell → source page
```

### The locator

The section heading is unreliable: of the five reference protocols only two
carry schedule-like wording on the page the table is actually on. The rest say
"Table 3. Overview of Study Assessments" or "Table 4. Opiate Agonist Phase". A
heading-driven locator finds two of five.

So pages are scored on **shape**, not words — density of cell-shaped tokens,
x-positions that repeat down the page (which works on the three borderless
tables where ruling lines do not exist), ruling lines, orientation. Headings are
worth about a quarter of the available score and only break ties.

The best-scoring page seeds a span that grows in **two phases**, because the
pages that continue a table and the pages that carry its footnotes look nothing
alike. Table pages while grid shape holds; then a footnote tail while pages read
as marker-led notes and no new section has opened. The bar to *continue* a span
is much lower than the bar to *start* one: protocol9's footnotes sit three pages
after its table begins and have no cells to recognise.

Thresholds are **relative to the best page in that document**, never absolute.
A 2011 Word table and a modern typeset one score in different ranges, so
ranking transfers where magnitude does not.

### The extractor

Page images, not the text layer. The reason is specific: superscript footnote
markers do not survive PDF text extraction with their binding intact.

```
                                    b     b     b     b     b     b
Urine tox screen      Weekly x 2    X     X     X     X     X     X
```

On the page each `b` sits on an `X`. In the text layer they are two lines with
no relationship left. Recovering it means re-deriving column geometry from
whitespace and hoping. The rendered page still shows the marker on the cell.

Rendering is 300 DPI, pre-scaled below the API's downsample threshold — letting
the API scale for us would destroy the 5pt superscripts that 300 DPI was for.

One page per call. Merging pages is a separate deterministic step, because a
model handed four page images at once tends to drop the middle two.

Responses are cached on page bytes + model + **the prompt text**, so editing the
prompt correctly invalidates everything. A cached answer from an older prompt is
a silent lie.

### The stitcher

An SoA runs across up to four pages and continues along one of two axes that
fail in opposite directions:

- **Row continuation** (protocol9 p26–28): the column header repeats, each page
  brings new assessments. Concatenate rows; map columns **by position**, because
  protocol9 restates its eleven study days three different ways
  (`Opiate Agonist Phase…`, then `1`…`11`, then `Day 1`…`Day 11`).
- **Column continuation** (protocol1 p53–54): every row label repeats, each page
  brings new visits. Merge columns onto existing rows. Concatenating here would
  duplicate all 28 assessments.

The axis is decided by row-label overlap and cross-checked against the
extractor's own read. Geometry wins on disagreement and the disagreement is
recorded.

Column identity is **exact**, never fuzzy — see "what went wrong" below.

Footnotes that spill past a page break are rejoined: a fragment arriving with no
marker after a footnote reported incomplete is a continuation. A span holding two
different schedules is split into two tables, and markers are reconciled across
them, because one page can carry the end of one table and the start of the next.

### The output schema

A graph, `nodes` and `edges` in one JSON file. Not a nested table.

```
Visit ──visit_in_period──▶ Period
Assessment ──assessment_in_category──▶ Category
Cell ──cell_of_assessment──▶ Assessment
Cell ──cell_at_visit──▶ Visit
Footnote ──footnote_annotates──▶ Cell | Assessment | Visit | Header
```

The reason is concrete. A footnote marker sits on a cell, a row, a column, **or**
a header. In nested JSON each of those needs a different home, so a single
requirement — *"we need to know that marker c on the Week 4 ECG cell points to
that footnote text"* — becomes four shapes. As edges it is one relation with
four possible targets.

The secondary reason is that the regulatory destination for this artifact is
already a graph: CDISC USDM models it as ScheduleTimeline / Encounter / Activity,
FHIR as PlanDefinition / ActivityDefinition. The node vocabulary tracks those.

Every node carries provenance — page and the engine that produced it. In a
regulated setting that is not optional.

Nothing is normalised. `3X/2 weeks` stays `3X/2 weeks`. A shaded cell is
`raw: ""` with `shaded: true`, which is not the same as absent.

---

## Results

### Locator

```
five reference protocols   12/12 pages = 100%    0 spurious
three unseen protocols      8/8  pages = 100%    9 spurious
one scanned protocol        1/1  page  = 100%    2 spurious
```

The scanned case has no text layer at all, so every text-based signal reads the
same on every page and the locator first returned **all 61 pages**. It now
renders text-poor pages small and counts long straight runs of dark pixels: a
table is long horizontal and vertical rules, and that survives having nothing to
read. 61 spans → 1 exact hit plus 2 spurious.

### Extraction, hand-verified against the printed pages

Full detail in `bench/VERIFICATION.md`.

| protocol | assessments | categories | visits | footnotes |
|---|---|---|---|---|
| protocol15 | **31 / 31** | 3 / 3 | 9 / 9 | 5 / 5, anchor counts exact |
| protocol12 | **37 / 37** | 3 / 3 | 8 / 8 | 21, 72 anchors |
| protocol1 | 28 printed → 30 emitted | — | 14 / 15 | 5, one duplicated |

Verified 3 of 5 by hand. protocol5 and protocol9 were not, and their numbers are
therefore reported but not vouched for.

### Engine comparison

`bench/BENCHMARK.md` has the detail and the per-tool rejections.

| | text-layer | Gemini |
|---|---|---|
| footnote links | 64 | **164** |
| footnotes | 10 | **53** |
| ambiguous cells | 406 | **19** |
| warnings | 159 | **38** |

text-layer reports *more* rows and cells than Gemini on every protocol, and
nearly all of the excess is garbage — footnote paragraphs read as rows, the
vertical word RANDOMIZATION split into rows `R`, `A`, `N`, `D`. Counting rows as
a score would invert the result.

---

## Generalization, and the evidence for it

Three protocols were pulled from clinicaltrials.gov **after** the pipeline was
frozen — Symphogen Sym004-09, I-Mab TJ301, Aldeyra ADX-629-CC-001. Nothing was
tuned for them. Full write-up in `bench/HOLDOUT.md`.

**First run: 62% page recall, 34 spurious.** Two were found correctly, and in
both the real SoA was the highest-scoring span in its document by a clear
margin. The third failed completely.

That failure was worth the exercise. NCT05392192 prints "Table 1: Schedule of
Assessments" and then a solid black rectangle across three pages — Poppler
renders it the same as PyMuPDF, so it is the document: **the sponsor redacted the
schedule before publishing.** Every text-layer signal scores zero on such a page.

Returning nothing is the wrong answer. "No schedule in this protocol" and "the
schedule is unreadable" are indistinguishable downstream, and one of them is
false. So a page with a schedule heading, almost no body text, and either raster
content or landscape orientation is now located on its caption alone, and the
extractor reads the rendered page to report what is there.

Fixing that also exposed a latent bug the original five never surfaced: the seed
bar was purely relative to the best page, so a document with no findable table
admitted a seed per page — ordinary prose scores 5.0–6.0 on incidental column
alignment. It now has to clear the document's own median page as well.

```
hold-out    62% recall, 34 spurious   →   100%, 10 spurious
original    100%, 0 spurious          →   unchanged
```

**What this shows:** the locator survives three unseen protocols from three
sponsors, with bullet cell markers it had never seen, five-level header stacks,
and a redacted table.

**What it does not show:** extraction correctness on those documents. Page recall
is not cell accuracy, and the vision extractors were never run on them — the
Anthropic credit was spent and Gemini's daily quota was consumed. Not estimated
in place of measured.

---

## What went wrong, and what it does when it breaks

Every heuristic here is fitted to a handful of documents and will be wrong on
some protocol nobody has seen. That is tolerable. Being wrong *silently* is not.
Two of the worst bugs in this project produced correct-looking output with no
signal at all.

So the system is built to fail loudly:

- **Conservation checks.** Pages produced N cells; the table has M; where did the
  rest go. Same for rows, footnotes, markers. On its first run it found **208
  lost cells** on protocols that were reporting a single warning.
- **Nothing is dropped.** A cell whose column will not resolve is parked on an
  explicit unresolved-visit node rather than discarded. A row that may be two
  rows is split, flagged, and its cells are *not* divided — attribution that
  cannot be recovered is not invented.
- **Deliberate discards are counted.** Grey banding on a category row is
  discarded with a reason. A category row carrying a *real* value is reported
  loudly, because that means the row was misread and an assessment is being lost.
- **Ambiguity is represented, not resolved.** 19 cells across five protocols are
  marked ambiguous rather than guessed.

### The four that mattered

**A page vanished in silence.** Gemini returned a 200 with zero output tokens.
That became `is_soa_page: None`, and the stitcher read it as "no table here" —
losing half of protocol1. Now an empty or unparseable response is a failed
attempt, not an answer, and failures are never cached.

**190 cells orphaned.** protocol9 p27 reported 12 columns for an 11-column table.
The count mismatch fell back to label matching, invented a second full set of
columns, and every cell on the page pointed into it. Now the common prefix is
aligned by position.

**Four patient visits deleted.** protocol1's merged table reported 10 visits;
both pages had extracted 7 correctly. Column merging matched labels fuzzily at
0.88, and visit labels are systematically similar by construction —
`"Visit 11 / Week 20"` against `"Visit 1 / Week -2"` scores 0.933. Visits 9, 11,
12 and 13 merged into visit 1. **No conservation check caught it**: no cells were
lost, they were piled onto the wrong columns. Only reading the printed page found
it, which is the argument for manual verification in one sentence.

**Every table gained a phantom visit.** An SoA labels its own row axis —
"Assessment", "ACTIVITY", "Trial Activity" — and the extractor read that header
cell as the first column. Now dropped when it both names the row axis and holds
no values; a real visit that happens to be called "Assessment" still carries
cells and survives.

**A prompt deleted 18 footnotes.** The extraction prompt said "if this page holds
no SoA table, return nothing". protocol12's p49 is titled "Notes on the Schedule
of Assessments". The model obeyed. The single most expensive bug in this project
was a sentence I wrote, not code.

### Known limits

- **Cell case is not always preserved.** protocol12's `Xa` came back as `x`;
  protocol15's did not. Per-page model variance.
- **Structure handled inconsistently between pages.** protocol15's RANDOMIZATION
  divider was returned as a column and explained; protocol12's identical device
  was dropped.
- **Precision on documents with no text layer is poor** — a fully scanned
  protocol yields 2 spurious page spans against 1 real one. Recall is intact and
  each spurious span costs one extractor call that reports an empty page, but
  the ratio would be worse on a longer scan.
- **~15 fitted constants** in the locator and stitcher, listed and sourced in
  `bench/HOLDOUT.md`. The vision path has almost none, which is itself the
  finding: the generalizable part of this system is the part with the fewest
  numbers in it.

### Questions for a clinical SME

Written down rather than guessed at:

1. protocol1 prints, in what appears to be one bordered cell: `Study drug record`
   / `Medications dispensed` / `Medications returned`, with one row of X marks.
   Three assessments or one three-line label? Three forms get built, or one.
2. protocol9's row labels carry parenthesised two-digit numbers —
   `Medical History (03)`. Read as CRF form identifiers and preserved in the
   label rather than parsed as footnote markers. p27 says "Form numbers may
   change", which supports that reading.

---

## Runtime

Locating is ~1s for a 100-page protocol. Extraction is 20–90s per page
end to end; a five-protocol, twelve-page run is 10–15 minutes cold and
**5 seconds** warm, since responses are cached.

## What I would build next, given two more weeks

1. **Finish verification** on protocols 5 and 9, and run the vision engines
   across the hold-out set. Those are the two claims currently unmade.
2. **Cross-model agreement as an ambiguity signal.** Two engines already read
   every page. Where they disagree on a cell is exactly where a human should
   look, and that is free signal being thrown away.
3. **Derive the geometry constants** from each page's own typography — median
   glyph height, median column pitch — instead of fixing them.
4. **A reviewer queue in the UI**, ordered by consequence. 19 ambiguous cells and
   38 warnings is already more than anyone reads top to bottom.
5. **USDM/FHIR export.** The schema was shaped for it; the mapping is not written.
6. **Actually run Docling**, so the benchmark reports it measured rather than
   researched.

## AI tools used

Built with Claude Code (Claude Opus 5) throughout, and the extraction engines
are Gemini 3.x Flash and Claude Opus 5 themselves.

**Where it helped.** Volume, mostly: the stitcher's failure modes were found by
generating hypotheses fast and testing them against cached extractions. The
28-test suite exists because writing regression tests was cheap enough to do for
every bug rather than the memorable ones.

**Where it hurt, specifically.**

The costliest mistakes in this project were all mine and all the same shape:
**trusting a rendering of the data instead of the data.**

- I added response caching *after* a full paid Anthropic run, throwing away
  twelve extractions.
- I shipped a prompt change without validating it, invalidating every cached
  extraction and turning a good run into a broken one — then discovered the
  cause was quota exhaustion, not the prompt.
- Twice during manual verification I recorded a defect that did not exist, once
  from misreading spacing and once from a bug in my own grid printer. Both are
  written up in `bench/VERIFICATION.md`, because the pattern is the finding.

The model is a fast way to be confidently wrong. Everything in this repo that is
actually trustworthy — the locator's 100%, the verified protocols, the hold-out
result — came from checking against the printed page.
