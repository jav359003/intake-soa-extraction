"""Score the locator against the hand-established answer key."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from soa.locate import locate

TRUTH = {                       # from bench/GROUND_TRUTH.md
    "protocol1.pdf":  [53, 54],
    "protocol5.pdf":  [50, 51],
    "protocol9.pdf":  [26, 27, 28, 29],
    "protocol12.pdf": [48, 49, 50],
    "protocol15.pdf": [25],
}

tot_missed = tot_extra = tot_truth = 0
for name, truth in sorted(TRUTH.items()):
    r = locate(f"protocols/{name}")
    got = sorted({p for t in r["tables"] for p in t["pages"]})
    missed = [p for p in truth if p not in got]
    extra  = [p for p in got if p not in truth]
    tot_missed += len(missed); tot_extra += len(extra); tot_truth += len(truth)
    flag = "OK " if not missed else "MISS"
    print(f"{flag} {name:<16} truth={truth} got={got} missed={missed} extra={extra}")
    for t in r["tables"]:
        print(f"        span {t['pages']} seed p{t['seed']} score {t['score']:.1f}")
print(f"\nrecall {tot_truth - tot_missed}/{tot_truth} = {(tot_truth-tot_missed)/tot_truth:.0%}"
      f"   spurious pages: {tot_extra}")
