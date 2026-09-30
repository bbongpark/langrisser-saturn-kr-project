#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_translations.py — merge Steam auto-matches + parallel-agent batch results
into one fully-filled dedup worksheet, ready for reinsert_text.py.

Sources:
  build/worksheet_dedup_matched.json   (glossary/dialogue auto-matches; kr set, src)
  build/translate_batches/result_*.json  (agent translations; {ref: kr})

An entry's `ref` is its ids[0]. Agent results key by that ref. We fill kr for the
`src=="none"` entries from the results. Reports coverage and lists any still-missing.
Output: build/worksheet_dedup_final.json
"""
import sys, io, os, json, glob
sys.stdout.reconfigure(encoding="utf-8")
BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")


def main():
    ws = json.load(open(os.path.join(BUILD, "worksheet_dedup_matched.json"), encoding="utf-8"))
    # collect agent results
    res = {}
    for p in sorted(glob.glob(os.path.join(BUILD, "translate_batches", "result_*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
            res.update(d)
            print(f"  {os.path.basename(p)}: {len(d)} translations")
        except Exception as e:
            print(f"  {os.path.basename(p)}: ERROR {e}")
    print(f"agent translations loaded: {len(res)}")

    filled = 0
    missing = []
    for e in ws:
        if e.get("kr", "").strip():
            continue                      # already auto-matched
        ref = e["ids"][0]
        if ref in res and res[ref].strip():
            e["kr"] = res[ref]; e["src"] = "agent"; filled += 1
        else:
            missing.append(ref)

    have = sum(1 for e in ws if e.get("kr", "").strip())
    print(f"\ntotal entries: {len(ws)}")
    print(f"  now translated: {have} ({100*have/len(ws):.1f}%)")
    print(f"  filled from agents this run: {filled}")
    print(f"  still missing: {len(missing)}")
    if missing[:10]:
        print("  missing sample:", missing[:10])
    out = os.path.join(BUILD, "worksheet_dedup_final.json")
    json.dump(ws, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
