# Hand-established ground truth (locator targets)

Established by reading all five PDFs page by page, 2026-08-30. This is the
answer key the locator is scored against.

| protocol | pages | SoA pages | continuation mode | footnote block | heading text |
|---|---|---|---|---|---|
| protocol1  | 97 | **53–54** | **columns** (same rows, visits 1–8 then 9–RT) | legend at foot of p54, applies to both pages | "Schedule of Events for Protocol H2Q-MC-LZZT(c)" / p54 "(concluded)" |
| protocol5  | 61 | **50–51** | rows end p50, notes p51 | p51, whole page | "Appendix I: Time and Events Schedule" |
| protocol9  | 57 | **26–29** | **rows** (same columns, Study Day 1–11 repeated) | p29, whole page | "Table 4. Schedule of Measures and Data Collection" / p27-29 "Table 4, Continued" |
| protocol12 | 97 | **48–50** | rows end p48, notes p49→p50 | p49 spills into p50 prose | "Table 3. Overview of Study Assessments" / p49 "Notes on the Schedule of Assessments" |
| protocol15 | 61 | **25** | single page | same page, foot of p25 | "Table 1. Overview of Study Assessments" |

## What this already proves

**1. The heading is unreliable.** Only protocol1 and protocol5 carry a
schedule-like heading on the table page itself. protocol9, 12 and 15 are titled
"Table N. <something>". A heading-driven locator finds 2 of 5.

**2. Two distinct continuation modes.** protocol1 continues across the *column*
axis — page 54 repeats every row label and supplies visits 9–RT. protocol9
continues across the *row* axis — pages 27–29 repeat the Study Day header and
supply new assessments. A stitcher that assumes row-concat duplicates all of
protocol1's rows; one that assumes column-merge drops most of protocol9's.

**3. Footnotes detach from the table.** protocol9's footnotes are on page 29,
three pages after the table starts. protocol12's run p49 → p50 with the
continuation carrying no marker and no heading. protocol1's legend sits only on
the final page but governs both.

**4. Superscript markers do not survive the text layer.** protocol15 p25 renders
the marker row and the value row as separate lines:

```
                                    b      b      b      b      b      b
Urine tox screen        Weekly x 2  X      X      X      X      X      X
```

The marker `b` has lost its binding to the cell. Recovering it from the text
layer means re-deriving column geometry from whitespace. This is the single
strongest argument for extracting from page images rather than text.

**5. Cell values are not booleans**, as promised: `3X`, `1X`, `6X`, `5X`, `8X`,
`Xa`, `Xb`, `Xc`, `Xd`, `Weekly x 2 weeks`, `for 2 weeks`, `Prior to Day 4`,
`Admission, Monday, Wednesday, Friday, Discharge and As Needed`, `Up to -35`.

**6. Near-miss traps.** protocol1 p52 and p89 are divider title pages carrying
the same words as the real table. protocol9 repeats a footer line "Form numbers
may change (small print)" on p27 and p28 which is a page footer, not a footnote.
Parenthesized numbers in protocol9 row labels — `Medical History (03)` — are CRF
form numbers, not footnote markers.

## Open question for a clinical SME

protocol9 row labels carry parenthesized two-digit numbers, e.g.
`Laboratory Assessments: Blood (06,07), Urine (08)`. These read as CRF form
identifiers rather than footnote markers, and page 27 says "Form numbers may
change". Confirmed as form IDs and preserved verbatim in the row label rather
than parsed as markers. Worth confirming.
