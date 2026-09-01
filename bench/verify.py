"""Print an extracted table as a grid, for eyeball comparison with the page.

Manual verification is the only check that says the extraction is *correct*
rather than merely internally consistent. The conservation checks prove nothing
was lost between stages; they cannot tell whether the model read the page right
in the first place. This renders the result in the same shape as the printed
table so the two can be compared line by line.
"""
from __future__ import annotations

import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def grid(table: dict, width: int = 13) -> str:
    by_id = {n["id"]: n for n in table["nodes"]}
    of = {e["src"]: e["dst"] for e in table["edges"] if e["type"] == "cell_of_assessment"}
    at = {e["src"]: e["dst"] for e in table["edges"] if e["type"] == "cell_at_visit"}
    fn_on: dict[str, list[str]] = {}
    for e in table["edges"]:
        if e["type"] == "footnote_annotates":
            fn_on.setdefault(e["dst"], []).append(e["src"])

    visits = [n for n in table["nodes"] if n["type"] == "visit"]
    cells = {}
    for n in table["nodes"]:
        if n["type"] == "cell":
            cells[(of.get(n["id"]), at.get(n["id"]))] = n

    out = [f"TABLE {table['table_id']}  pages {table['pages']}",
           f"  {table.get('title','')}", ""]
    hdr = "".join(f"{v['label'][:width-1]:<{width}}" for v in visits)
    out.append(f"{'ASSESSMENT':<40}{hdr}")
    out.append("-" * (40 + width * len(visits)))

    for n in table["nodes"]:
        if n["type"] == "category":
            out.append(f"[{n['label'][:60]}]")
        elif n["type"] == "assessment":
            mk = "".join(f"^{m}" for m in (n["attrs"].get("markers") or []))
            row = f"{(n['label'] + mk)[:39]:<40}"
            flag = " *AMBIG" if n["ambiguous"] else ""
            for v in visits:
                c = cells.get((n["id"], v["id"]))
                if not c:
                    row += " " * width
                    continue
                val = c["label"] or ("[shaded]" if c["attrs"].get("shaded") else "")
                val += "".join(f"^{m}" for m in (c["attrs"].get("markers") or []))
                row += f"{val[:width-1]:<{width}}"
            out.append(row.rstrip() + flag)

    out.append("")
    out.append("FOOTNOTES")
    for n in table["nodes"]:
        if n["type"] == "footnote":
            anchors = sum(1 for e in table["edges"]
                          if e["type"] == "footnote_annotates" and e["src"] == n["id"])
            trunc = "" if n["attrs"].get("complete", True) else "  [TRUNCATED]"
            out.append(f"  [{n['attrs'].get('marker','')}] ({anchors} anchors){trunc} "
                       f"{n['label'][:150]}")
    ws = [w for w in table["warnings"] if not w.startswith("located by")]
    if ws:
        out.append("")
        out.append(f"WARNINGS ({len(ws)})")
        out += [f"  - {w[:200]}" for w in ws]
    return "\n".join(out)


if __name__ == "__main__":
    engine = sys.argv[2] if len(sys.argv) > 2 else "gemini"
    f = ROOT / "outputs" / engine / f"{sys.argv[1]}.json"
    j = json.loads(f.read_text())
    for t in j["tables"]:
        print(grid(t))
        print("\n" + "=" * 100 + "\n")
