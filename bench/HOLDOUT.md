# Hold-out test: three protocols the system was never tuned against

Downloaded from clinicaltrials.gov after the pipeline was frozen. Nothing in
`locate.py`, `stitch.py` or the prompt was changed to accommodate them.

| protocol | sponsor / study | pages | SoA pages (hand-checked) | notes |
|---|---|---|---|---|
| NCT02568046 | Symphogen Sym004-09, mCRC | 122 | **35** table, **36** footnotes | "Table 2 Flow Chart – Schedule of Assessments" |
| NCT03235752 | I-Mab TJ301, ulcerative colitis | 97 | **44–45** table, **46** footnotes | "Table 1 Time and Events Schedule" |
| NCT05392192 | Aldeyra ADX-629-CC-001, chronic cough | 68 | **28–30** | **no text layer — the table is an image** |

## What is new here, versus the five it was built on

**Cell values are bullets, not X.** Both text-layer protocols mark cells with
`•`. None of the original five did. The CELL pattern already covered bullets,
which was luck rather than design.

**A three-page image-only table.** NCT05392192 prints its schedule as an
embedded image across pages 28-30 with no extractable text. The locator reads
the text layer, so it has nothing to score and will find nothing. This is a
hard failure, not a graceful one, and it is the single biggest gap the hold-out
exposed.

**Deeper header stacks.** NCT03235752 stacks five header rows -- period, week,
day, allowed window, visit number, visit name -- against two or three in the
originals.

**Footnotes keyed by letter running past the page break.** NCT03235752's notes
start on p45 under the table and continue to p46 opening at marker `h`, with no
heading and no repeat of the table.


---

# Results

Locator only. The vision extractors could not be run on these: the Anthropic
credit was spent and the Gemini free tier allows 20 requests per model per day,
which the five  protocols had already consumed. Extraction results on the
hold-out set are therefore **not** reported here rather than estimated.

## First run, before any change

```
NCT02568046   found 35, 36            + 6 spurious
NCT03235752   found 44, 45, 46        + 2 spurious
NCT05392192   found nothing           + 26 spurious
page recall 5/8 = 62%     spurious 34
```

Two honest observations from that run. The two text-layer protocols were found
correctly and in both the real SoA was the **highest-scoring span in the
document** by a clear margin (12.5 against 9.0 and 7.9). And NCT05392192 failed
completely.

## What the failure turned out to be

NCT05392192 prints "Table 1: Schedule of Assessments" on page 28 followed by a
solid black rectangle, across three pages. Two independent renderers (PyMuPDF
and Poppler) agree, so this is the document, not the renderer: **the sponsor
redacted the schedule before publishing to clinicaltrials.gov.**

There is no content to extract. But returning nothing is still the wrong
answer: a reviewer needs to be told that a schedule exists at page 28 and its
content is unreadable. Silence and "no schedule in this protocol" look
identical downstream, and one of them is false.

## Changes made in response

1. **Unreadable tables are located, not skipped.** A page carrying a
   schedule-like heading, almost no body text, and either real raster content
   or landscape orientation is now a candidate on the strength of its caption.
   The extractor works from the rendered page and gets to report what is
   actually there.
2. **Such a span expands across sparse neighbours**, since continuation pages
   of an unreadable table carry no caption and no cells -- only the same shape.
3. **The seed bar gained a noise floor.** It was purely relative to the best
   page in the document, so a protocol with no findable table admitted a seed
   per page: ordinary prose scores 5.0-6.0 through incidental column alignment.
   Seeds must now clear the document's own median page by a margin as well.
4. A portrait page with a schedule heading and nothing else is a divider sheet
   announcing the table overleaf, not a table. Excluded.

## After

```
NCT02568046   35, 36        + 6 spurious
NCT03235752   44, 45, 46    + 2 spurious
NCT05392192   28, 29, 30    + 2 spurious
HOLD-OUT page recall 8/8 = 100%    spurious 10
original five               12/12 = 100%    spurious 0
```

## What this does and does not show

It shows the locator survives three unseen protocols from three sponsors, with
bullet cell markers it had never seen, five-level header stacks, and a redacted
table -- and that the one thing it got badly wrong was fixed by a change that
also improved the original five.

It does not show the extraction is correct on these documents. Nobody has run
the vision extractor on them, and page recall is not cell accuracy. The
spurious spans are also real: ten pages that are not schedules would each cost
an extractor call before being reported as empty.
