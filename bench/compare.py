"""Compare extraction engines on the same protocols, same pipeline.

Only the extractor changes between runs -- locate, stitch and graph are
identical -- so any difference in these numbers is attributable to the
extractor alone.

Counts are structural, not a correctness score. Correctness comes from the
by-hand pass in VERIFICATION.md; this table says what each engine *produced*,
which is what makes a dropped row visible.
"""
from __future__ import annotations

import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIELDS = ["visits", "assessments", "categories", "cells", "footnotes",
          "footnote_links", "ambiguous", "warnings"]


def load(engine: str) -> dict[str, dict]:
    out = {}
    d = ROOT / "outputs" / engine
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        j = json.loads(f.read_text())
        agg = {k: 0 for k in FIELDS}
        for s in j["stats"]:
            for k in FIELDS:
                agg[k] += s.get(k, 0)
        agg["seconds"] = j.get("seconds", 0)
        agg["pages"] = sum(len(t["pages"]) for t in j["tables"])
        out[j["protocol"]] = agg
    return out


def main(engines: list[str]) -> None:
    data = {e: load(e) for e in engines}
    protocols = sorted({p for d in data.values() for p in d})
    if not protocols:
        print("no outputs found; run the pipeline with --out outputs/<engine> first")
        return

    w = max(len(p) for p in protocols) + 1
    for field in FIELDS + ["seconds"]:
        print(f"\n{field}")
        print(f"  {'protocol':<{w}} " + " ".join(f"{e:>14}" for e in engines))
        for p in protocols:
            cells = []
            for e in engines:
                v = data[e].get(p, {}).get(field)
                cells.append("—".rjust(14) if v is None else f"{v:>14}")
            print(f"  {p:<{w}} " + " ".join(cells))
        for e in engines:
            tot = sum(data[e].get(p, {}).get(field, 0) for p in protocols)
            print(f"  {'':<{w}} " + f"{e}={round(tot, 1)}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["text-layer", "vision"])
