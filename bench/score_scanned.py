"""Locator on a protocol with no text layer at all.

protocol15 rasterised at 150 DPI, every page an image, zero extractable words.
The README listed scanned protocols as an untested failure mode; making one is
cheap, so it is measured rather than assumed.
"""
import sys, pathlib, subprocess
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pymupdf
from soa.locate import locate

SRC, DST, TRUTH = "protocols/protocol15.pdf", "holdout/protocol15_scanned.pdf", [25]

if not pathlib.Path(DST).exists():
    src = pymupdf.open(SRC); out = pymupdf.open()
    for pg in src:
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(150 / 72, 150 / 72), alpha=False)
        out.new_page(width=pg.rect.width, height=pg.rect.height).insert_image(pg.rect, pixmap=pix)
    out.save(DST)

d = pymupdf.open(DST)
assert len(d[TRUTH[0] - 1].get_text("words")) == 0, "expected no text layer"

r = locate(DST)
got = sorted({p for t in r["tables"] for p in t["pages"]})
missed = [p for p in TRUTH if p not in got]
print(f"{'OK ' if not missed else 'MISS'} scanned protocol15  truth={TRUTH} got={got}")
for t in r["tables"]:
    print(f"       span {t['pages']} score {t['score']:.1f} | {t['reasons'][0][:90]}")
print(f"\nSCANNED page recall {len(TRUTH)-len(missed)}/{len(TRUTH)}   "
      f"spurious pages: {len(got)-len(TRUTH)+len(missed)}")
