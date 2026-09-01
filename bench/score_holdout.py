"""Score the locator on protocols it was never tuned against."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from soa.locate import locate

TRUTH = {                      # from bench/HOLDOUT.md, established by hand
    "NCT02568046.pdf": [35, 36],
    "NCT03235752.pdf": [44, 45, 46],
    "NCT05392192.pdf": [28, 29, 30],   # content redacted; the pages must still be found
}

tm = te = tt = 0
for name, truth in sorted(TRUTH.items()):
    r = locate(f"holdout/{name}")
    got = sorted({p for t in r["tables"] for p in t["pages"]})
    missed = [p for p in truth if p not in got]
    extra = [p for p in got if p not in truth]
    tm += len(missed); te += len(extra); tt += len(truth)
    print(f"{'OK ' if not missed else 'MISS'} {name:<18} truth={truth} got={got}")
    print(f"       missed={missed} extra={extra}")
    for t in r["tables"]:
        print(f"       span {t['pages']} seed p{t['seed']} score {t['score']:.1f}")
print(f"\nHOLD-OUT page recall {tt-tm}/{tt} = {(tt-tm)/tt:.0%}   spurious pages: {te}")
