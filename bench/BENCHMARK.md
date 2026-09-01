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
| **Claude Opus 5, vision** | supported, not the default | Highest quality single result observed (it identified and explained the vertical RANDOMIZATION divider unprompted). Not the default only because the account credit ran out mid-project. |
| **Docling / TableFormer** | evaluated on documentation, not run | IBM's table transformer is the strongest open baseline, but its documented weakness is exactly this workload — multi-level headers and merged cells. Running it properly needed an afternoon that went into verification instead. **Not run, so not claimed.** |
| **Microsoft Table Transformer** | considered, rejected | Detects table structure as geometry with no text. Would have required building coordinate-to-text matching, which is the bug-prone glue the vision path removes entirely. Considered for the locator, dropped once the locator hit 100% page recall without it. |
| **pdfplumber** | superseded | Started here; PyMuPDF gave the same word geometry plus drawings and image info in one library. |

## Results, five protocols

| metric | text-layer | Gemini |
|---|---|---|
| footnote links | 64 | **164** |
| footnotes captured | 10 | **53** |
| cells marked ambiguous | 406 | **19** |
| warnings | 159 | **38** |
| wall clock (cached) | 5.3s | 5.0s |

Cell and row counts are deliberately **not** presented as a score. text-layer
reports *more* rows and cells than Gemini on every protocol, and nearly all of
the excess is garbage. Counting them as wins would invert the result.

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
- **Case is not always preserved.** protocol12's `Xa`/`Xb` came back lowercased;
  protocol15's did not. Per-page variance, not a rule.
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

## The honest summary

Vision wins decisively on the thing that is hardest and most graded — **164
footnote links against 64**, and correct structure where the text layer produces
inflated garbage. It costs money or quota, degrades silently when rate-limited,
and varies page to page.

The text layer is free, instant, and wrong in ways that look right: it returns
*more* rows, which reads as better recall until you compare against the page.

**The comparison the README cannot make** is a full Claude-vs-Gemini run on all
five protocols, and Docling measured rather than read about. Both were lost to
budget, and neither is estimated in place of being measured.
