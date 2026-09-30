#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_batches.py — merge subagent out_<name>.json (key->kr) files back into
worksheet_dedup_final.json, validating each Korean string (window width / page lines /
encodability) and only applying the ones that pass. Failures are reported (left as
original Japanese so a bad line never blocks the build).

Usage: python merge_batches.py [out_glob]
"""
import sys, io, os, json, re, glob
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import kr_markup, kr_render, kr_font, kr_encoding

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")
BATCH = os.path.join(BUILD, "batches")
WS = os.path.join(BUILD, "worksheet_dedup_final.json")
WIDTH, MAX_LINES = 14, 3


def validate(kr, table):
    """Return (ok, reason). Mirrors reinsert_text's per-entry checks."""
    try:
        has = bool(re.search(r'\[(NAME|MTE|NL|PAGE|WAIT|C|RAW):?', kr))
        if has:
            p = kr_markup.parse_markup(kr_markup.rewrap_markup(kr, WIDTH, MAX_LINES, 0.5),
                                       space=kr_markup.HW_SPACE)
        else:
            p = kr_render.render_segment(kr, WIDTH, MAX_LINES, kr_markup.HW_SPACE)
        for k, v in p:
            if k == "kr":
                kr_encoding.encode_text(v, table)
        if kr_markup.max_page_lines(p) > MAX_LINES:
            return False, "page>3"
        if kr_markup.max_line_width(p) > WIDTH:
            return False, f"line>{WIDTH}"
        return True, ""
    except Exception as ex:
        return False, str(ex)[:40]


def main():
    ws = json.load(open(WS, encoding="utf-8"))
    by_id = {}
    for e in ws:
        for i in e["ids"]:
            by_id[i] = e
    # gather all out files
    outs = sorted(glob.glob(os.path.join(BATCH, "out_*.json")))
    print(f"out files: {len(outs)}")
    kmap = {}
    for f in outs:
        d = json.load(open(f, encoding="utf-8"))
        n = 0
        for k, v in d.items():
            if isinstance(v, str) and v.strip():
                kmap[k] = v; n += 1
        print(f"  {os.path.basename(f)}: {n} translations")
    print(f"total unique keys with kr: {len(kmap)}")

    # font table over EVERYTHING currently translated + incoming, for encode validation
    syl = set()
    for e in ws:
        if e.get("kr", "").strip():
            syl.update(c for c in e["kr"] if kr_encoding.is_hangul(c))
    for v in kmap.values():
        syl.update(c for c in v if kr_encoding.is_hangul(c))
    fd1 = kr_font.FontDat.load(os.path.join(BUILD, "..", "original", "LANG1_FONT.DAT"))
    table = kr_encoding.build_table(sorted(syl), fontdat=fd1)

    applied = fail = skip_have = miss = 0
    fails = []
    for k, kr in kmap.items():
        e = by_id.get(k)
        if e is None:
            miss += 1; continue
        if e.get("kr", "").strip():
            skip_have += 1; continue          # already translated (mine/steam) — keep
        ok, why = validate(kr, table)
        if ok:
            e["kr"] = kr; e["src"] = "agent"; applied += 1
        else:
            fail += 1
            if len(fails) < 20:
                fails.append((k, why, kr[:34]))
    print(f"\napplied: {applied} | validation-failed: {fail} | "
          f"already-had: {skip_have} | key-not-found: {miss}")
    for k, why, s in fails:
        print(f"  FAIL [{why}] {k}: {s!r}")
    untr = sum(1 for e in ws if not e.get("kr", "").strip())
    print(f"\nworksheet now: {len(ws)} total, {len(ws)-untr} translated, {untr} untranslated")
    json.dump(ws, open(WS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-> worksheet_dedup_final.json updated")


if __name__ == "__main__":
    main()
