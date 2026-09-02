# Extractor benchmark

Three extraction engines behind one contract. `locate`, `stitch` and the graph
are identical across runs, so every difference below is attributable to the
extractor alone. Swapping engines is one CLI flag.

```bash
python3 -m soa.pipeline --engine text-layer --out outputs/text-layer
python3 -m soa.pipeline --engine gemini     --out outputs/gemini
python3 -m soa.pipeline --engine vision     --out outputs/vision   # Anthropic
```

## What was evaluated, and what was rejected

| tool | verdict | why |
|---|---|---|
| **PyMuPDF text layer** (own implementation) | kept as the baseline | Free, instant, no key. Reconstructs the grid from word coordinates. Included because a benchmark needs a control, and because it is the honest answer to "do you actually need a model for this". |
| **Gemini 3.x Flash, vision** | **shipped default** | Free tier, strong on merged cells, reads the rendered page so superscript markers keep the cell they sit on. |
| **Claude Opus 5, vision** | supported, run once | Highest quality single page observed — it identified and explained the vertical RANDOMIZATION divider unprompted, and volunteered three uncertainties. Not benchmarked across all five: the credit ran out after one run and before response caching existed, so those numbers are not comparable and are not reported. |
| **OpenAI `gpt-5`, vision** | **run on all five** | Third engine, added specifically so this table reports three measured rather than two measured and one read about. Settles the cell-case question below, and fails in a way neither of the others does. |
| **Docling / TableFormer** | evaluated on documentation, not run | IBM's table transformer is the strongest open baseline, but its documented weakness is exactly this workload — multi-level headers and merged cells. Running it properly needed an afternoon that went into verification instead. **Not run, so not claimed.** |
| **Microsoft Table Transformer** | considered, rejected | Detects table structure as geometry with no text. Would have required building coordinate-to-text matching, which is the bug-prone glue the vision path removes entirely. Considered for the locator, dropped once the locator hit 100% page recall without it. |
| **pdfplumber** | superseded | Started here; PyMuPDF gave the same word geometry plus drawings and image info in one library. |

## Results, five protocols, three engines

| metric | text-layer | Gemini 3.x Flash | OpenAI gpt-5 |
|---|---|---|---|
| footnote links | 64 | **162** | 109 |
| footnotes captured | 10 | **53** | 46 |
| cells marked ambiguous | 406 | **19** | 182 |
| warnings | 159 | **41** | 77 |
| protocols returning a table on every located page | 5/5 | **5/5** | 4/5 |

Per table, cells extracted:

| table | text-layer | Gemini | OpenAI |
|---|---|---|---|
| protocol1 [53,54] | 243 | 139 | 141 |
| protocol12 [48–50] | 144 | 132 | 137 |
| protocol15 [25] | 243 | 128 | 119 |
| protocol5 main [50] | 145 | 123 | **0** |
| protocol5 PK [51] | — | 44 | 44 |
| protocol9 [26–29] | 249 | 202 | 226 |

Cell and row counts are deliberately **not** a score. text-layer reports *more*
than either vision engine on every protocol and nearly all of the excess is
garbage — footnote paragraphs read as rows, the vertical word RANDOMIZATION
split into rows `R`, `A`, `N`, `D`. Counting rows would invert the result. The
counts are here so the two vision engines can be compared against each other
and against the hand-verified truth in `VERIFICATION.md`, not to rank them.

## Where each one breaks, specifically

### text-layer

Measured against the hand-verified truth from `VERIFICATION.md`:

| protocol | truth | text-layer | what went wrong |
|---|---|---|---|
| protocol15 | 31 assessments, 9 visits | 48 assessments, 8 visits | footnote paragraphs parsed as rows; the vertical word RANDOMIZATION split into rows `R`, `A`, `N`, `D`… |
| protocol1 | ~30 assessments, 15 visits | 50 assessments, 8 visits | multi-line row labels split into separate rows; page 54's visits never merged |
| protocol12 | 37 assessments, 8 visits | 43 assessments, 8 visits | closest result, still inflated |
| protocol9 | ~36 assessments | 70 assessments | wrapped labels each became a row |

Three failures are structural rather than tunable:

1. **Superscript markers lose their cell.** The text layer emits the marker row
   and the value row as separate lines, so `b` and the `X` it sits on have no
   relationship left. Recovering it means re-deriving column geometry from
   whitespace. 0 footnote links on four of five protocols.
2. **Shading is invisible.** A grey "not applicable" cell and an empty cell are
   identical in the text layer.
3. **No single threshold fits five documents.** Column detection support had to
   be scaled to page density because 3 leaked label text into the grid on dense
   pages and 5 dropped real visit columns on sparse ones. That is a property of
   the approach, not a tuning failure.

### Gemini 3.x Flash

- **Free tier is 20 requests per model per day.** Exhausted twice during this
  project. The fallback chain (3.7 → 3.6 → 3.5 → 3-flash-preview) extends it to
  roughly 80, then hard-stops.
- **It degrades silently under that pressure.** When 3.7 stopped serving, three
  pages came back as unparseable JSON from the weakest fallback — and the failure
  landed on the densest pages, which have the most to lose. This forced the rule
  that an unparseable response is a failed attempt, not an answer.
- **Case is not always preserved, and this is now measured rather than guessed.**
  protocol12 prints `Xa`, `Xb`, `Xc`. Gemini returns `x` fifty times on that
  page; OpenAI returns `X` seventy-four times on the same page from the same
  prompt. So the lowercasing is a property of the model, not of the pipeline or
  the page — which is exactly the question a second vision engine was added to
  answer.
- **Structure handling is inconsistent between pages.** protocol15's
  RANDOMIZATION divider was returned as a column and explained; protocol12's
  identical device was dropped.

### Claude Opus 5

- Best single-page result observed. On protocol15 it identified the divider
  column, flagged one cell as illegible at print resolution rather than guessing,
  and noted that its shading read was approximate — three volunteered
  uncertainties, which is the behaviour the brief asks for.
- Roughly 3.4k input / 15k output tokens per page.
- Not benchmarked across all five, because the credit ran out after one full run
  and before response caching existed. That run's numbers are not comparable and
  are not reported.

### OpenAI gpt-5

- **Preserves cell case** where Gemini does not. On protocol12 it returns `X`
  where Gemini returns `x`, from the same prompt on the same page.
- **Marks illegibility rather than guessing.** It returned `?` for two cells it
  could not read at print resolution and flagged them ambiguous, which is the
  behaviour the brief asks for.
- **Failed completely on one page.** protocol5 p50 came back with **0 cells** —
  a page Gemini handled with 123. The page is landscape with twelve visit
  columns; nothing in the response explains the failure, and it is the only
  total failure by any engine on any located page.
- **Far more cells flagged ambiguous** (182 against Gemini's 19). Partly honest
  caution, partly noise: it flags whole rows where Gemini commits.
- Roughly 2.1k input / 15.9k output tokens per page, and slow — about 90
  seconds a page against Gemini's 20 to 40.

### Where the two vision engines disagree

They disagree on cell counts for every protocol, most sharply on protocol9
(226 against 202) and protocol5 (0 against 123). **That disagreement is
signal.** Two independent readings of the same page, differing on a cell, marks
exactly the cell a human should look at — and the pipeline already stores both
runs side by side. Turning that into a per-cell agreement check is the single
highest-value thing left undone here, and it is written up as such in the
README's next-steps.

## The honest summary

Vision wins decisively on the thing that is hardest and most graded — **162
footnote links against 64** — and produces correct structure where the text
layer produces inflated garbage. It costs money or quota, degrades silently
when rate-limited, and varies page to page.

Between the two vision engines: **Gemini is the better default here.** More
footnote links, a fifth the ambiguous cells, half the warnings, three times
faster, free at this volume, and it was the only engine to return a table on
every located page. OpenAI is more faithful on character case and more willing
to say it cannot read something, and it is the one to reach for when a page
matters more than the run does.

The text layer is free, instant, and wrong in ways that look right: it returns
*more* rows, which reads as better recall until you compare against the page.

**Still not measured:** Claude across all five protocols, and Docling run rather
than read about. Claude ran once, before response caching existed, and the
credit ran out; Docling's install and tuning was an afternoon that went into
manual verification instead. Neither is estimated in place of being measured,
and neither is claimed.
