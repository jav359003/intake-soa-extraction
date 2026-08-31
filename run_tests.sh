#!/usr/bin/env bash
# Every check in one command. No API calls: the vision engines run from cache.
set -uo pipefail
cd "$(dirname "$0")"
fail=0

echo "=== stitcher unit tests"
python3 tests/test_stitch.py | tail -2 || fail=1
echo
echo "=== UI tests"
python3 tests/test_ui.py | tail -2 || fail=1
echo
echo "=== locator vs hand-built answer key (bench/GROUND_TRUTH.md)"
python3 bench/score_locator.py | grep -E "^(MISS|recall)" || fail=1
echo
echo "=== end to end, both engines"
python3 -u -m soa.pipeline --engine text-layer --out outputs/text-layer 2>/dev/null | sed 's/  */ /g'
python3 -u -m soa.pipeline --engine gemini --out outputs/gemini 2>/dev/null \
  | grep -v "Direct use" | sed 's/  */ /g'
echo
echo "=== unresolved warnings by table"
python3 - <<'PY'
import json, pathlib
for f in sorted(pathlib.Path("outputs/gemini").glob("*.json")):
    j = json.loads(f.read_text())
    for t in j["tables"]:
        n = len([w for w in t["warnings"] if not w.startswith("located by")])
        print(f"  {t['table_id']:<22} pages {str(t['pages']):<16} {n} warning(s)")
PY
exit $fail
